import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/book.css";
import "./styles/masthead.css";
import "./styles/views.css";

import { createAntiquePaperOverlay, createPaperGrainDataUrl } from "./lib/antiquePaper.js";
import { PageCurlAnimator } from "./lib/pageCurl.js";
import { subscribeSSE } from "./lib/sse.js";
import { createChronicleView } from "./views/folioChronicle.js";
import { createCodexView } from "./views/folioCodex.js";
import { createModerationView } from "./views/folioModeration.js";
import { createMastheadHub } from "./views/masthead.js";

const FOLIOS = [
  { id: "chronicle", roman: "Folio I", label: "Live Activity", shortLabel: "Live Activity" },
  { id: "moderation", roman: "Folio II", label: "Live Moderation", shortLabel: "Moderation" },
  { id: "codex", roman: "Folio III", label: "Moderation Rules", shortLabel: "Rules" },
];

function prefersReducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

async function postConfig(patch) {
  try {
    const resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!resp.ok) {
      console.warn(`toggle update returned HTTP ${resp.status}; SSE preserves live state`);
      return null;
    }
    const data = await resp.json();
    return data?.toggles ?? null;
  } catch {
    console.warn("toggle update failed; SSE preserves live state");
    return null;
  }
}

/**
 * Symmetric Verso | Recto folio footer living inside each moving full-viewport leaf.
 * Keeps the center spine gutter completely clear of text or ornaments.
 */
function createFolioFooter(index, onNavigate) {
  const cur = FOLIOS[index];
  const prev = index > 0 ? FOLIOS[index - 1] : null;
  const next = index < FOLIOS.length - 1 ? FOLIOS[index + 1] : null;

  const footer = document.createElement("footer");
  footer.className = "folio-foot";
  footer.setAttribute("aria-label", `${cur.roman} navigation`);

  const versoHalf = document.createElement("div");
  versoHalf.className = "folio-foot-half folio-foot-verso";

  if (prev) {
    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "page-turn-btn is-prev";
    prevBtn.innerHTML = `<span class="turn-arrow" aria-hidden="true">‹</span><span>${prev.roman} · ${prev.label}</span>`;
    prevBtn.addEventListener("click", () => onNavigate(index - 1));
    versoHalf.append(prevBtn);
  } else {
    const note = document.createElement("span");
    note.className = "folio-edge-note";
    note.textContent = "First folio";
    versoHalf.append(note);
  }

  const versoNum = document.createElement("span");
  versoNum.className = "folio-page-mark";
  versoNum.textContent = `${cur.roman} of ${FOLIOS.length} · Verso`;
  versoHalf.append(versoNum);

  const rectoHalf = document.createElement("div");
  rectoHalf.className = "folio-foot-half folio-foot-recto";

  const rectoHint = document.createElement("span");
  rectoHint.className = "folio-page-mark folio-key-hint";
  rectoHint.textContent = "Recto · ← / → turn page";
  rectoHalf.append(rectoHint);

  if (next) {
    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "page-turn-btn is-next";
    nextBtn.innerHTML = `<span>${next.roman} · ${next.label}</span><span class="turn-arrow" aria-hidden="true">›</span>`;
    nextBtn.addEventListener("click", () => onNavigate(index + 1));
    rectoHalf.append(nextBtn);
  } else {
    const note = document.createElement("span");
    note.className = "folio-edge-note";
    note.textContent = "Last folio";
    rectoHalf.append(note);
  }

  footer.append(versoHalf, rectoHalf);
  return footer;
}

function boot() {
  const grainUrl = createPaperGrainDataUrl();
  if (grainUrl) {
    document.documentElement.style.setProperty("--paper-grain-url", `url("${grainUrl}")`);
    document.getElementById("page-curl-grain-img")?.setAttribute("href", grainUrl);
  }

  const stageEl = document.getElementById("folio-stage");
  const slots = [
    document.getElementById("folio-slot-0"),
    document.getElementById("folio-slot-1"),
    document.getElementById("folio-slot-2"),
  ];

  const chronicleView = createChronicleView("chr");
  const moderationView = createModerationView("mod");
  const codexView = createCodexView("cdx");
  const views = [chronicleView.el, moderationView.el, codexView.el];

  const curl = new PageCurlAnimator({
    stageEl,
    overlaySvg: document.getElementById("page-curl-svg"),
    underShadowEl: document.getElementById("page-curl-under-shadow"),
    underShadowGradEl: document.getElementById("page-curl-under-grad"),
    keepClipPolyEl: document.getElementById("page-curl-keep-poly"),
    curlBackEl: document.getElementById("page-curl-back"),
    curlGrainEl: document.getElementById("page-curl-grain"),
    curlShadowEl: document.getElementById("page-curl-shadow"),
    curlShadowGradEl: document.getElementById("page-curl-flap-shadow-grad"),
    curlGradEl: document.getElementById("page-curl-grad"),
  });

  const cornerPrevHotspot = document.getElementById("corner-prev-hotspot");
  const cornerNextHotspot = document.getElementById("corner-turn-hotspot");

  let activePage = 0;
  let windowSize = "5m";
  let paused = false;
  let peekCorner = null;
  let latestMetrics = null;
  let latestMalice = null;
  const viewDirty = [false, false];
  let closeMetricsSSE = null;
  let closeMaliceSSE = null;

  function hydrateView(index) {
    if (!viewDirty[index]) return;
    viewDirty[index] = false;
    if (index === 0) chronicleView.update(latestMetrics);
    else if (index === 1) moderationView.update(latestMalice);
  }

  function prepareFolio(index) {
    mastheadHub.syncHeader(index);
    hydrateView(index);
  }

  function syncChrome(index) {
    const cur = FOLIOS[index];
    stageEl.setAttribute("aria-label", `${cur.roman}: ${cur.label}`);
    cornerPrevHotspot.hidden = index <= 0;
    cornerNextHotspot.hidden = index >= FOLIOS.length - 1;
  }

  function settleLayers(index) {
    slots.forEach((slot, idx) => {
      const isCurrent = idx === index;
      slot.classList.toggle("is-active", isCurrent);
      slot.classList.remove("is-under", "is-peeling");
      slot.style.clipPath = "";
      slot.inert = !isCurrent;
    });
  }

  function goToPage(nextIndex) {
    const target = Math.max(0, Math.min(FOLIOS.length - 1, nextIndex));
    if (target === activePage) return;

    peekCorner = null;
    const prevIndex = activePage;

    if (curl.isAnimating) {
      curl.cancel(slots[prevIndex]);
      settleLayers(prevIndex);
    }

    activePage = target;
    mastheadHub.setActiveIndex(target);
    prepareFolio(target);
    syncChrome(target);

    if (prefersReducedMotion()) {
      settleLayers(target);
      return;
    }

    // Full-viewport top-to-bottom peel: bottom-right (forward) or mirrored bottom-left (backward)
    const corner = target > prevIndex ? "right" : "left";

    slots.forEach((slot, idx) => {
      slot.classList.remove("is-active", "is-under", "is-peeling");
      slot.style.clipPath = "";
      slot.inert = true;
      if (idx === target) slot.classList.add("is-under");
      if (idx === prevIndex) slot.classList.add("is-peeling");
    });

    curl.animatePeel(slots[prevIndex], corner, () => {
      settleLayers(activePage);
    });
  }

  const mastheadHub = createMastheadHub(FOLIOS, {
    onSelectFolio: (idx) => goToPage(idx),
    onSelectWindow: (nextWin) => {
      if (!nextWin || nextWin === windowSize) return;
      windowSize = nextWin;
      mastheadHub.setWindow(windowSize);
      connectMetricsStream();
    },
    onTogglePause: () => {
      paused = !paused;
      mastheadHub.setPaused(paused);
      connectStreams();
    },
    onToggleModeration: async (patch) => {
      const updated = await postConfig(patch);
      if (updated) {
        mastheadHub.setModerationToggles(updated);
        moderationView.setToggles(updated);
        if (latestMalice) {
          latestMalice = { ...latestMalice, toggles: updated };
        }
      }
    },
  });

  // Mount each full-viewport moving folio leaf: antique deckle/splotches + masthead + spread + footer
  slots.forEach((slot, idx) => {
    slot.append(
      createAntiquePaperOverlay(idx),
      mastheadHub.createHeader(idx),
      views[idx],
      createFolioFooter(idx, goToPage),
    );
  });

  // Symmetric interactive dog-ear hover previews on both real bottom corners
  function startPeek(corner) {
    if (curl.isAnimating) return;
    const neighborIdx = corner === "right" ? activePage + 1 : activePage - 1;
    if (neighborIdx < 0 || neighborIdx >= FOLIOS.length) return;
    if (prefersReducedMotion()) return;

    prepareFolio(neighborIdx);
    peekCorner = corner;
    slots[neighborIdx].inert = true;
    slots[neighborIdx].classList.add("is-under");
    slots[activePage].classList.add("is-peeling");
    curl.animatePeek(slots[activePage], 0.08, corner);
  }

  function endPeek(corner) {
    if (peekCorner !== corner || curl.isAnimating) return;
    peekCorner = null;
    const curIdx = activePage;
    const neighborIdx = corner === "right" ? curIdx + 1 : curIdx - 1;
    curl.animatePeek(slots[curIdx], 0, corner, () => {
      if (!curl.isAnimating && activePage === curIdx) {
        slots[curIdx].classList.remove("is-peeling");
        slots[curIdx].style.clipPath = "";
        if (slots[neighborIdx]) slots[neighborIdx].classList.remove("is-under");
      }
    });
  }

  cornerNextHotspot.addEventListener("pointerenter", () => startPeek("right"));
  cornerNextHotspot.addEventListener("pointerleave", () => endPeek("right"));
  cornerNextHotspot.addEventListener("click", () => {
    peekCorner = null;
    goToPage(activePage + 1);
  });

  cornerPrevHotspot.addEventListener("pointerenter", () => startPeek("left"));
  cornerPrevHotspot.addEventListener("pointerleave", () => endPeek("left"));
  cornerPrevHotspot.addEventListener("click", () => {
    peekCorner = null;
    goToPage(activePage - 1);
  });

  window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (event.target?.closest?.('[role="toolbar"]')) return;
    if (event.key === "ArrowRight") goToPage(activePage + 1);
    else if (event.key === "ArrowLeft") goToPage(activePage - 1);
  });

  function connectMetricsStream() {
    if (closeMetricsSSE) {
      closeMetricsSSE();
      closeMetricsSSE = null;
    }
    if (paused) return;

    closeMetricsSSE = subscribeSSE(`/api/stream?window=${windowSize}`, (payload) => {
      latestMetrics = payload;
      mastheadHub.updateMeta(payload.meta);
      mastheadHub.updatePulse(payload.pulse);
      viewDirty[0] = true;
      hydrateView(activePage);
    });
  }

  function connectMaliceStream() {
    if (closeMaliceSSE) {
      closeMaliceSSE();
      closeMaliceSSE = null;
    }
    if (paused) return;

    closeMaliceSSE = subscribeSSE("/api/malice", (payload) => {
      latestMalice = payload;
      mastheadHub.setModerationToggles(payload?.toggles);
      viewDirty[1] = true;
      hydrateView(activePage);
    });
  }

  function connectStreams() {
    connectMetricsStream();
    connectMaliceStream();
  }

  settleLayers(0);
  mastheadHub.setActiveIndex(0);
  syncChrome(0);
  connectStreams();
}

boot();
