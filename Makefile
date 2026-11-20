.DEFAULT_GOAL := help

.PHONY: help up up-gpu down redis llm llm-gpu ingestor analyzer api frontend test lint bench clean

LLM_HF_REPO ?= unsloth/gemma-4-E4B-it-qat-mobile-GGUF:UD-Q2_K_XL
LLM_GPU_HF_REPO ?= unsloth/gemma-4-E4B-it-qat-GGUF:UD-Q4_K_XL
LLM_MODEL ?= gemma-4-e4b-qat
LLM_GPU_PARALLEL ?= 4
LLM_THREADS ?= 8

help: ## Print available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Available targets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

up: ## Start full stack (universal CPU default, mobile Q2 QAT)
	docker compose up --build -d

up-gpu: ## Start full stack with NVIDIA CUDA GPU (Q4 QAT)
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d

down: ## Stop Docker Compose stack
	docker compose down

# --- Local development (uv + Docker for Redis & LLM) ---

redis: ## Start Redis Stack in Docker (:6379, RedisInsight :8001)
	@docker start wp-redis 2>/dev/null || \
		docker run -d --name wp-redis -p 6379:6379 -p 8001:8001 \
			-v wp-redis-data:/data \
			redis/redis-stack:7.4.0-v7 redis-stack-server --save 60 1 --dir /data

llm: ## Start Gemma 4 E4B mobile Q2 QAT in llama-server (CPU, :8080)
	@docker start wp-llm 2>/dev/null || \
		docker run -d --name wp-llm -p 8080:8000 \
			-e LLAMA_CACHE=/models/cache \
			-v wp-llm-cache:/models/cache \
			ghcr.io/ggml-org/llama.cpp:server \
			--hf-repo $(LLM_HF_REPO) --alias $(LLM_MODEL) \
			--host 0.0.0.0 --port 8000 --threads $(LLM_THREADS) \
			--ctx-size 4096 --parallel 1 \
			--cache-reuse 256 --jinja --reasoning off

llm-gpu: ## Start Gemma 4 E4B Q4 QAT in llama-server (NVIDIA CUDA, :8080)
	@docker start wp-llm 2>/dev/null || \
		docker run -d --name wp-llm --gpus all -p 8080:8000 \
			-e LLAMA_CACHE=/models/cache \
			-v wp-llm-cache:/models/cache \
			ghcr.io/ggml-org/llama.cpp:server-cuda \
			--hf-repo $(LLM_GPU_HF_REPO) --alias $(LLM_MODEL) \
			--host 0.0.0.0 --port 8000 --n-gpu-layers 99 \
			--ctx-size 16384 --parallel $(LLM_GPU_PARALLEL) --cont-batching \
			--flash-attn on --cache-reuse 256 --jinja --reasoning off

ingestor: ## Run direct Wikimedia SSE ingestor locally
	uv run python -m wikipulse.ingestor

analyzer: ## Run concurrent Gemma 4 E4B analyzer locally
	LLM_URL=http://localhost:8080/v1/chat/completions uv run python -m wikipulse.analyzer

api: ## Run FastAPI backend with auto-reload (:8000)
	uv run uvicorn wikipulse.api.app:app --reload --host 0.0.0.0 --port 8000

frontend: ## Run Vite dev server (:5173)
	cd frontend && npm run dev

test: ## Run full test suite
	uv run pytest

lint: ## Lint codebase with ruff
	uv run ruff check wikipulse tests bench

bench: ## Run offline ingestor benchmark
	uv run python -m bench.bench_ingestor

clean: ## Stop standalone local Docker helpers (wp-redis, wp-llm)
	@docker stop wp-redis wp-llm 2>/dev/null || true
	@docker rm wp-redis wp-llm 2>/dev/null || true
