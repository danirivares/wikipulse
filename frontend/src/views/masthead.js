/**
 * Multi-folio open-book masthead hub: each moving `.folio-layer` owns its own
 * Verso | Recto header so page-turn animations sweep seamlessly from y=0 to y=100%.
 *
 * Uses per-header dirty version tracking so steady-state 1s SSE ticks only mutate
 * the active folio's DOM, while `syncHeader(idx)` hydrates any neighbor sheet right
 * before a corner peek or page turn reveals it.
 */

import { DEFAULT_TOGGLES, formatClockUtc } from "../lib/ui.js";

const WIDTH = 700;
const BASE_Y = 70;
const PAD_TOP = 8;

const MOD_DETECTORS = [
  { key: "detect_edits", label: "Edits", title: "Flag vandalism and abuse in article edits" },
  { key: "detect_images", label: "Images", title: "Flag unsafe newly uploaded images" },
  { key: "summarize", label: "Summaries", title: "Generate one-sentence summaries of changes and images" },
];

const MOD_FILTERS = [
  { key: "exclude_bots", label: "Skip bots", title: "Ignore automated bot accounts" },
  { key: "only_anon_new", label: "Anon only", title: "Analyze only anonymous (temporary) accounts" },
];

function formatArchivalDate(iso) {
  const d = iso ? new Date(iso) : new Date();
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/**
 * Roving-tabindex fallback for horizontal `role="toolbar"` containers when
 * native HTML `focusgroup` is unsupported.
 */
function installToolbarFallback(bar) {
  if (!bar || "focusGroup" in HTMLElement.prototype) return;
  const items = [...bar.querySelectorAll("button")];
  if (items.length === 0) return;

  const activeIdx = Math.max(
    0,
    items.findIndex((btn) => btn.getAttribute("aria-pressed") === "true"),
  );
  items.forEach((btn, idx) => {
    btn.tabIndex = idx === activeIdx ? 0 : -1;
  });

  bar.addEventListener("focusin", ({ target }) => {
    if (!items.includes(target)) return;
    items.forEach((btn) => {
      btn.tabIndex = btn === target ? 0 : -1;
    });
  });

  bar.addEventListener("keydown", (event) => {
    const curIdx = items.indexOf(document.activeElement);
    if (curIdx === -1) return;

    const rtl = getComputedStyle(bar).direction === "rtl";
    let nextIdx = -1;
    if (event.key === "ArrowRight") {
      nextIdx = (curIdx + (rtl ? -1 : 1) + items.length) % items.length;
    } else if (event.key === "ArrowLeft") {
      nextIdx = (curIdx + (rtl ? 1 : -1) + items.length) % items.length;
    } else if (event.key === "Home") {
      nextIdx = 0;
    } else if (event.key === "End") {
      nextIdx = items.length - 1;
    }

    if (nextIdx !== -1) {
      event.preventDefault();
      event.stopPropagation();
      items[nextIdx].focus();
    }
  });
}

function renderToggleButtonsHtml(defs, state) {
  return defs
    .map(({ key, label, title }) => {
      const on = !!state[key];
      return `
        <button type="button" class="ink-toggle" data-toggle="${key}" title="${title}" aria-pressed="${on}">
          <span class="ink-diamond" aria-hidden="true">${on ? "◈" : "◇"}</span>
          <span>${label}</span>
        </button>
      `;
    })
    .join("");
}

function renderRectoRibbonHtml(folioId, toggleState) {
  if (folioId === "moderation") {
    return `
      <div
        class="masthead-ribbon-half masthead-ribbon-controls masthead-ribbon-moderation"
        role="toolbar"
        focusgroup="toolbar wrap"
        aria-label="Moderation controls"
      >
        <div class="toggle-cluster" role="group" aria-label="Active detectors">
          ${renderToggleButtonsHtml(MOD_DETECTORS, toggleState)}
        </div>
        <span class="toolbar-sep" role="separator" aria-orientation="vertical"></span>
        <div class="toggle-cluster" role="group" aria-label="Edit filters">
          ${renderToggleButtonsHtml(MOD_FILTERS, toggleState)}
        </div>
      </div>
    `;
  }

  if (folioId === "codex") {
    return `
      <div class="masthead-ribbon-half masthead-ribbon-controls">
        <span class="ribbon-context-note">How edits &amp; images are flagged</span>
        <span class="ribbon-context-note">AI + metadata rules</span>
      </div>
    `;
  }

  return `
    <div
      class="masthead-ribbon-half masthead-ribbon-controls"
      role="toolbar"
      focusgroup="toolbar wrap"
      aria-label="Aggregation window"
    >
      <div class="window-inline" role="group" aria-label="Sliding window">
        <span class="control-kicker">Window</span>
        <button type="button" class="ink-choice" data-window="1m" aria-pressed="false">1m</button>
        <button type="button" class="ink-choice" data-window="5m" aria-pressed="true">5m</button>
        <button type="button" class="ink-choice" data-window="15m" aria-pressed="false">15m</button>
      </div>
      <span class="ribbon-context-note">live sliding window</span>
    </div>
  `;
}

function renderSeismographSvgHtml({ gradId, topOpacity, areaRole, lineRole, interactive }) {
  const gridLines = interactive
    ? `
      <line x1="0" y1="24" x2="700" y2="24" stroke="var(--ink-rule-soft)" stroke-dasharray="2 6" stroke-width="0.75" />
      <line x1="0" y1="48" x2="700" y2="48" stroke="var(--ink-rule-soft)" stroke-dasharray="2 6" stroke-width="0.65" />
      <line x1="0" y1="70" x2="700" y2="70" stroke="var(--ink-rule)" stroke-width="0.9" />
    `
    : `<line x1="0" y1="70" x2="700" y2="70" stroke="var(--ink-rule-soft)" stroke-width="0.8" />`;

  const cursor = interactive
    ? `
      <g data-role="pulse-cursor" hidden>
        <line
          data-role="pulse-cursor-line"
          x1="0" y1="4" x2="0" y2="70"
          stroke="var(--oxblood)" stroke-width="1" stroke-dasharray="2 3"
          vector-effect="non-scaling-stroke"
        />
        <circle
          data-role="pulse-cursor-dot"
          cx="0" cy="0" r="3.2"
          fill="var(--oxblood)" stroke="var(--vellum)" stroke-width="1.2"
          vector-effect="non-scaling-stroke"
        />
      </g>
    `
    : "";

  const svgAttrs = interactive
    ? 'role="img" aria-label="Edits per second over the last 30 minutes"'
    : "";

  return `
    <svg class="seismograph-svg" viewBox="0 0 700 80" preserveAspectRatio="none" ${svgAttrs}>
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--oxblood)" stop-opacity="${topOpacity}" />
          <stop offset="100%" stop-color="var(--oxblood)" stop-opacity="0.01" />
        </linearGradient>
      </defs>
      ${gridLines}
      <path data-role="${areaRole}" fill="url(#${gradId})" />
      <path
        data-role="${lineRole}"
        fill="none"
        stroke="var(--ink)"
        stroke-width="${interactive ? "1.25" : "1.2"}"
        stroke-linejoin="round"
        stroke-linecap="round"
        vector-effect="non-scaling-stroke"
        opacity="${interactive ? "0.82" : "0.72"}"
      />
      ${cursor}
    </svg>
  `;
}

function bindSeismographScrubber(refs, getCoords) {
  refs.seismographEl.addEventListener("pointermove", (event) => {
    const coords = getCoords();
    if (coords.length === 0) return;
    const rect = refs.seismographEl.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const pt = coords[Math.round(ratio * (coords.length - 1))];
    if (!pt) return;

    refs.cursorLineEl.setAttribute("x1", pt.x.toFixed(1));
    refs.cursorLineEl.setAttribute("x2", pt.x.toFixed(1));
    refs.cursorDotEl.setAttribute("cx", pt.x.toFixed(1));
    refs.cursorDotEl.setAttribute("cy", pt.y.toFixed(1));
    refs.cursorGroupEl.removeAttribute("hidden");

    refs.readoutTimeEl.textContent = `${formatClockUtc(pt.ts)} UTC`;
    refs.readoutValEl.textContent = `${pt.value.toFixed(1)} edits/s`;
    refs.readoutEl.hidden = false;
  });

  refs.seismographEl.addEventListener("pointerleave", () => {
    refs.cursorGroupEl.setAttribute("hidden", "");
    refs.readoutEl.hidden = true;
  });
}

export function createMastheadHub(
  folios,
  { onSelectFolio, onSelectWindow, onTogglePause, onToggleModeration },
) {
  const instances = [];
  let activeIndex = 0;

  let coords = [];
  let lastFingerprint = "";
  let pulseLineD = "";
  let pulseAreaD = "";
  let pulseVer = 0;

  let metaState = { eps: "0.0", updated: "—", dateText: "UTC" };
  let metaVer = 0;

  let currentWindow = "5m";
  let currentPaused = false;
  let currentToggles = { ...DEFAULT_TOGGLES };
  let controlsVer = 0;

  function syncHeader(index) {
    const r = instances[index];
    if (!r) return;

    if (r.metaVer !== metaVer) {
      r.metaVer = metaVer;
      r.dateEl.textContent = metaState.dateText;
      r.epsEl.textContent = metaState.eps;
      r.updatedEl.textContent = metaState.updated;
    }

    if (r.pulseVer !== pulseVer) {
      r.pulseVer = pulseVer;
      r.linePathEl.setAttribute("d", pulseLineD);
      r.areaPathEl.setAttribute("d", pulseAreaD);
      r.lineVersoEl.setAttribute("d", pulseLineD);
      r.areaVersoEl.setAttribute("d", pulseAreaD);
    }

    if (r.controlsVer !== controlsVer) {
      r.controlsVer = controlsVer;
      for (const btn of r.windowButtons) {
        btn.setAttribute("aria-pressed", String(btn.dataset.window === currentWindow));
      }
      for (const btn of r.toggleButtons) {
        const key = btn.dataset.toggle;
        const on = !!currentToggles[key];
        btn.setAttribute("aria-pressed", String(on));
        const diamond = btn.querySelector(".ink-diamond");
        if (diamond) diamond.textContent = on ? "◈" : "◇";
      }
      r.pauseBtn.classList.toggle("is-paused", currentPaused);
      r.pauseBtn.setAttribute("aria-pressed", String(currentPaused));
      r.pauseBtn.textContent = currentPaused ? "▸ Resume" : "‖ Pause";
    }
  }

  function createHeader(folioIndex) {
    const folio = folios[folioIndex];
    const header = document.createElement("header");
    header.className = "archive-masthead";

    const tabsHtml = folios
      .map((f, idx) => {
        const isCurrent = idx === folioIndex;
        return `
          <button
            type="button"
            class="folio-tab${isCurrent ? " is-active" : ""}"
            data-folio="${idx}"
            ${isCurrent ? 'aria-current="page"' : ""}
          >
            <span class="folio-roman">${f.roman}</span>
            <span class="folio-name">${f.shortLabel}</span>
          </button>
        `;
      })
      .join("");

    header.innerHTML = `
      <div class="masthead-open-book">
        <!-- VERSO (Left Page) -->
        <div class="masthead-half masthead-verso">
          <div class="masthead-meta-line">
            <span class="masthead-stamp">
              <span class="corner-ornament" aria-hidden="true">❦</span>
              <span class="masthead-folio-mark">${folio.roman}</span>
              <span class="ink-dot" aria-hidden="true">·</span>
              <span>Verso</span>
            </span>
            <span class="masthead-substamp">Global Edit Monitor</span>
          </div>

          <div class="masthead-banner masthead-title-banner">
            <div class="masthead-seismograph masthead-seismograph-flank" aria-hidden="true">
              <div class="seismograph-masked">
                ${renderSeismographSvgHtml({
                  gradId: `pulse-fill-verso-${folioIndex}`,
                  topOpacity: "0.22",
                  areaRole: "pulse-area-verso",
                  lineRole: "pulse-line-verso",
                  interactive: false,
                })}
              </div>
            </div>

            <h1 class="masthead-title">Wiki<em>Pulse</em></h1>
          </div>

          <p class="masthead-subtitle">
            <span class="subtitle-ornament" aria-hidden="true">❧</span>
            <span>Live Wikipedia stream · <code>stream.wikimedia.org</code></span>
            <span class="subtitle-ornament" aria-hidden="true">☙</span>
          </p>

          <div class="masthead-ribbon-half">
            <nav class="folio-tabs" aria-label="Folio pages">${tabsHtml}</nav>
          </div>
        </div>

        <!-- RECTO (Right Page) -->
        <div class="masthead-half masthead-recto">
          <div class="masthead-meta-line">
            <span class="masthead-substamp">Edit rate · last 30 min</span>
            <span class="masthead-date">
              <span data-role="date">UTC</span>
              <span class="corner-ornament" aria-hidden="true">❦</span>
            </span>
          </div>

          <div class="masthead-banner masthead-pulse-banner">
            <div data-role="seismograph" class="masthead-seismograph masthead-seismograph-full">
              ${renderSeismographSvgHtml({
                gradId: `pulse-fill-grad-${folioIndex}`,
                topOpacity: "0.24",
                areaRole: "pulse-area",
                lineRole: "pulse-line",
                interactive: true,
              })}
              <div data-role="pulse-readout" class="seismograph-readout" hidden>
                <span data-role="pulse-readout-time"></span>
                <span aria-hidden="true">·</span>
                <strong data-role="pulse-readout-val"></strong>
              </div>
            </div>
          </div>

          <div class="ribbon-telemetry">
            <span class="telemetry-item">
              <strong data-role="meta-eps">0.0</strong>
              <span>edits/s</span>
            </span>
            <span class="ink-dot" aria-hidden="true">·</span>
            <span class="telemetry-item">
              <span>updated</span>
              <strong data-role="meta-updated">—</strong>
            </span>
            <span class="ink-dot" aria-hidden="true">·</span>
            <button type="button" data-role="pause-btn" class="ink-action telemetry-pause" aria-pressed="false">‖ Pause</button>
          </div>

          ${renderRectoRibbonHtml(folio.id, currentToggles)}
        </div>
      </div>
    `;

    const refs = {
      dateEl: header.querySelector('[data-role="date"]'),
      epsEl: header.querySelector('[data-role="meta-eps"]'),
      updatedEl: header.querySelector('[data-role="meta-updated"]'),
      seismographEl: header.querySelector('[data-role="seismograph"]'),
      areaPathEl: header.querySelector('[data-role="pulse-area"]'),
      linePathEl: header.querySelector('[data-role="pulse-line"]'),
      areaVersoEl: header.querySelector('[data-role="pulse-area-verso"]'),
      lineVersoEl: header.querySelector('[data-role="pulse-line-verso"]'),
      cursorGroupEl: header.querySelector('[data-role="pulse-cursor"]'),
      cursorLineEl: header.querySelector('[data-role="pulse-cursor-line"]'),
      cursorDotEl: header.querySelector('[data-role="pulse-cursor-dot"]'),
      readoutEl: header.querySelector('[data-role="pulse-readout"]'),
      readoutTimeEl: header.querySelector('[data-role="pulse-readout-time"]'),
      readoutValEl: header.querySelector('[data-role="pulse-readout-val"]'),
      windowButtons: [...header.querySelectorAll("[data-window]")],
      toggleButtons: [...header.querySelectorAll("[data-toggle]")],
      pauseBtn: header.querySelector('[data-role="pause-btn"]'),
      metaVer: 0,
      pulseVer: 0,
      controlsVer: 0,
    };

    header.querySelectorAll(".folio-tab").forEach((btn) => {
      btn.addEventListener("click", () => onSelectFolio(Number(btn.dataset.folio)));
    });

    refs.windowButtons.forEach((btn) => {
      btn.addEventListener("click", () => onSelectWindow(btn.dataset.window));
    });

    refs.toggleButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.toggle;
        if (key && onToggleModeration) {
          onToggleModeration({ [key]: !currentToggles[key] });
        }
      });
    });

    installToolbarFallback(header.querySelector('[role="toolbar"]'));
    refs.pauseBtn.addEventListener("click", () => onTogglePause());
    bindSeismographScrubber(refs, () => coords);

    instances[folioIndex] = refs;
    return header;
  }

  function setActiveIndex(index) {
    activeIndex = index;
    syncHeader(index);
  }

  function updateMeta(meta) {
    metaState = {
      eps: (meta?.events_per_sec ?? 0).toFixed(1),
      updated: formatClockUtc(meta?.last_update, "—"),
      dateText: `${formatArchivalDate(meta?.last_update)} · UTC`,
    };
    metaVer += 1;
    syncHeader(activeIndex);
  }

  function updatePulse(points = []) {
    const last = points[points.length - 1];
    const fingerprint =
      points.length === 0 ? "0" : `${points.length}|${points[0].ts}|${last.ts}|${last.value}`;
    if (fingerprint === lastFingerprint) return;
    lastFingerprint = fingerprint;

    if (points.length < 2) {
      coords = [];
      pulseLineD = "";
      pulseAreaD = "";
    } else {
      const maxVal = Math.max(...points.map((p) => p.value), 1);
      const minTs = points[0].ts;
      const rawSpan = last.ts - minTs;
      const usableH = BASE_Y - PAD_TOP;

      coords = points.map((p, idx) => {
        const x =
          rawSpan > 0 ? ((p.ts - minTs) / rawSpan) * WIDTH : (idx / (points.length - 1)) * WIDTH;
        const y = BASE_Y - (p.value / maxVal) * usableH;
        return { x, y, ts: p.ts, value: p.value };
      });

      pulseLineD = coords
        .map((pt, i) => `${i === 0 ? "M" : "L"}${pt.x.toFixed(1)},${pt.y.toFixed(1)}`)
        .join(" ");
      pulseAreaD = `${pulseLineD} L${WIDTH},${BASE_Y} L0,${BASE_Y} Z`;
    }

    pulseVer += 1;
    syncHeader(activeIndex);
  }

  function setWindow(windowSize) {
    currentWindow = windowSize;
    controlsVer += 1;
    syncHeader(activeIndex);
  }

  function setModerationToggles(toggles) {
    if (!toggles) return;
    currentToggles = { ...currentToggles, ...toggles };
    controlsVer += 1;
    syncHeader(activeIndex);
  }

  function setPaused(paused) {
    currentPaused = paused;
    controlsVer += 1;
    syncHeader(activeIndex);
  }

  return {
    createHeader,
    setActiveIndex,
    syncHeader,
    updateMeta,
    updatePulse,
    setWindow,
    setModerationToggles,
    setPaused,
  };
}
