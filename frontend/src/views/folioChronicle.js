/**
 * Folio I — Live Activity (symmetric open-book spread):
 *  - Verso (left page):  § I   Top 10 Roman-indexed article ledger
 *  - Recto (right page): § II  Copperplate Nightingale Compass Rose (Most Active Wikis)
 *                        § III & § IV Engraved surveyor ratio scales (Bots & Anons)
 */

import { computeCompassWedges, polarToCartesian } from "../lib/compassRose.js";
import { createRatioGauge, renderLedgerRows } from "../lib/ui.js";

const SVG_NS = "http://www.w3.org/2000/svg";

const ROSE_W = 580;
const ROSE_H = 336;
const CX = 290;
const CY = 168;
const INNER_R = 36;
const MAX_R = 132;
const LABEL_R = 148;

const ROSE_STYLES = [
  { wash: "#7a2220", opacity: 0.78, pattern: "hatch-diag-light", border: "#4d1412" },
  { wash: "#9e7c52", opacity: 0.50, pattern: "hatch-diag", border: "#4b3824" },
  { wash: "#738368", opacity: 0.46, pattern: "hatch-cross", border: "#34422a" },
  { wash: "#567085", opacity: 0.46, pattern: "hatch-horiz", border: "#253848" },
  { wash: "#b58b5b", opacity: 0.48, pattern: "hatch-rev", border: "#5b4122" },
  { wash: "#9c6252", opacity: 0.48, pattern: "hatch-stipple", border: "#582c21" },
  { wash: "#8c7a62", opacity: 0.44, pattern: "hatch-diag", border: "#4a3e2e" },
  { wash: "#a59678", opacity: 0.46, pattern: "hatch-rev", border: "#554a36" },
  { wash: "#7c877c", opacity: 0.44, pattern: "hatch-horiz", border: "#3d473d" },
  { wash: "#b39879", opacity: 0.44, pattern: "hatch-stipple", border: "#5d4932" },
];

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    el.setAttribute(k, String(v));
  }
  return el;
}

function buildEngravingDefs(uid) {
  const defs = svgEl("defs");

  const pDiag = svgEl("pattern", {
    id: `${uid}-hatch-diag`, width: 7, height: 7, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)",
  });
  pDiag.append(svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 7, stroke: "#2c2116", "stroke-opacity": 0.16, "stroke-width": 0.9 }));

  const pDiagLight = svgEl("pattern", {
    id: `${uid}-hatch-diag-light`, width: 7, height: 7, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)",
  });
  pDiagLight.append(svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 7, stroke: "#f5ebd6", "stroke-opacity": 0.16, "stroke-width": 0.9 }));

  const pRev = svgEl("pattern", {
    id: `${uid}-hatch-rev`, width: 7, height: 7, patternUnits: "userSpaceOnUse", patternTransform: "rotate(-45)",
  });
  pRev.append(svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 7, stroke: "#2c2116", "stroke-opacity": 0.15, "stroke-width": 0.9 }));

  const pCross = svgEl("pattern", {
    id: `${uid}-hatch-cross`, width: 9, height: 9, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)",
  });
  pCross.append(
    svgEl("line", { x1: 0, y1: 0, x2: 0, y2: 9, stroke: "#2c2116", "stroke-opacity": 0.13, "stroke-width": 0.85 }),
    svgEl("line", { x1: 0, y1: 0, x2: 9, y2: 0, stroke: "#2c2116", "stroke-opacity": 0.13, "stroke-width": 0.85 }),
  );

  const pHoriz = svgEl("pattern", {
    id: `${uid}-hatch-horiz`, width: 6, height: 6, patternUnits: "userSpaceOnUse",
  });
  pHoriz.append(svgEl("line", { x1: 0, y1: 3, x2: 6, y2: 3, stroke: "#2c2116", "stroke-opacity": 0.14, "stroke-width": 0.85 }));

  const pStipple = svgEl("pattern", {
    id: `${uid}-hatch-stipple`, width: 6, height: 6, patternUnits: "userSpaceOnUse",
  });
  pStipple.append(
    svgEl("circle", { cx: 1.8, cy: 1.8, r: 0.65, fill: "#2c2116", "fill-opacity": 0.22 }),
    svgEl("circle", { cx: 4.8, cy: 4.8, r: 0.55, fill: "#2c2116", "fill-opacity": 0.16 }),
  );

  defs.append(pDiag, pDiagLight, pRev, pCross, pHoriz, pStipple);
  return defs;
}

/** Build the persistent SVG scaffold for the compass rose once (zero per-second rebuild of static chrome). */
function createCompassScaffold(uid) {
  const svg = svgEl("svg", {
    class: "rose-svg",
    viewBox: `0 0 ${ROSE_W} ${ROSE_H}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "group",
    "aria-label": "Radial chart of edit share across top active wikis",
  });

  svg.append(buildEngravingDefs(uid));

  const ringsGroup = svgEl("g", { "aria-hidden": "true" });
  for (const frac of [0.33, 0.66, 1]) {
    const r = INNER_R + frac * (MAX_R - INNER_R);
    ringsGroup.append(
      svgEl("circle", {
        cx: CX,
        cy: CY,
        r: r.toFixed(1),
        fill: "none",
        stroke: "var(--ink-rule-soft)",
        "stroke-width": frac === 1 ? 0.9 : 0.7,
        "stroke-dasharray": frac === 1 ? "none" : "2 4",
      }),
    );
  }
  ringsGroup.append(
    svgEl("circle", {
      cx: CX,
      cy: CY,
      r: (MAX_R + 7).toFixed(1),
      fill: "none",
      stroke: "var(--ink-rule-soft)",
      "stroke-width": 0.6,
    }),
  );
  for (let deg = 0; deg < 360; deg += 15) {
    const rad = (deg * Math.PI) / 180;
    const major = deg % 90 === 0;
    const [x1, y1] = polarToCartesian(CX, CY, MAX_R + (major ? 2 : 4), rad);
    const [x2, y2] = polarToCartesian(CX, CY, MAX_R + (major ? 10 : 7), rad);
    ringsGroup.append(
      svgEl("line", {
        x1: x1.toFixed(1),
        y1: y1.toFixed(1),
        x2: x2.toFixed(1),
        y2: y2.toFixed(1),
        stroke: "var(--ink-rule)",
        "stroke-width": major ? 1 : 0.55,
        "stroke-opacity": major ? 0.65 : 0.4,
      }),
    );
  }

  const wedgesGroup = svgEl("g", { "data-role": "wedges", role: "list" });

  const centerVal = svgEl("text", {
    x: CX,
    y: CY - 1,
    "text-anchor": "middle",
    class: "rose-center-val",
  });
  const centerSub = svgEl("text", {
    x: CX,
    y: CY + 13,
    "text-anchor": "middle",
    class: "rose-center-sub",
  });

  // Preserve exact SVG paint order: rings -> dynamic wedges -> central medallion on top.
  svg.append(
    ringsGroup,
    wedgesGroup,
    svgEl("circle", {
      cx: CX,
      cy: CY,
      r: INNER_R,
      fill: "var(--vellum)",
      stroke: "var(--ink-rule-strong)",
      "stroke-width": 1.1,
    }),
    svgEl("circle", {
      cx: CX,
      cy: CY,
      r: INNER_R - 3.5,
      fill: "none",
      stroke: "var(--ink-rule-soft)",
      "stroke-width": 0.6,
    }),
    centerVal,
    centerSub,
  );

  return { svg, wedgesGroup, centerVal, centerSub };
}

export function createChronicleView(uid = "chr") {
  const el = document.createElement("div");
  el.className = "folio-spread chronicle-spread";
  el.innerHTML = `
    <div class="open-book-spread">
      <div class="book-page book-verso">
        <section class="folio-block folio-block-fill" aria-labelledby="${uid}-top-h">
          <div class="block-head">
            <h2 id="${uid}-top-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ I</span>
              Most Edited Articles
            </h2>
            <span class="block-kicker">Top 10 · main articles · excl. Wikidata &amp; Commons</span>
          </div>
          <p class="archive-empty" data-role="top-empty">Waiting for incoming edits…</p>
          <ol class="ledger-list ledger-list-spread" role="list" data-role="top-list" hidden></ol>
        </section>
      </div>

      <div class="book-page book-recto book-recto-balanced">
        <section class="folio-block rose-block" aria-labelledby="${uid}-wiki-h">
          <div class="block-head">
            <h2 id="${uid}-wiki-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ II</span>
              Most Active Wikis
            </h2>
            <span class="block-kicker" data-role="wiki-kicker">Top 10 · edit share</span>
          </div>
          <p class="archive-empty" data-role="wiki-empty">Waiting for wiki activity…</p>
          <div class="rose-plate" data-role="wiki-plate" hidden></div>
        </section>

        <hr class="folio-divider" />

        <div class="ratio-pair" data-role="ratio-pair"></div>
      </div>
    </div>
  `;

  const topEmpty = el.querySelector('[data-role="top-empty"]');
  const topList = el.querySelector('[data-role="top-list"]');
  const wikiKicker = el.querySelector('[data-role="wiki-kicker"]');
  const wikiEmpty = el.querySelector('[data-role="wiki-empty"]');
  const wikiPlate = el.querySelector('[data-role="wiki-plate"]');
  const ratioPair = el.querySelector('[data-role="ratio-pair"]');

  const botGauge = createRatioGauge({
    glyph: "§ III",
    title: "Bots vs. Humans",
    kicker: "flagged as bot",
    tone: "ink",
    sub: "bots",
    primaryLabel: "Bots",
    secondaryLabel: "Humans",
  });
  const anonGauge = createRatioGauge({
    glyph: "§ IV",
    title: "Anonymous vs. Registered",
    kicker: "temp accounts (~YYYY-N-N)",
    tone: "rubric",
    sub: "anonymous",
    primaryLabel: "Anonymous",
    secondaryLabel: "Registered",
  });
  const anonWrap = document.createElement("div");
  anonWrap.className = "ratio-pair-divider";
  anonWrap.append(anonGauge.el);
  ratioPair.append(botGauge.el, anonWrap);

  const rose = createCompassScaffold(uid);
  wikiPlate.append(rose.svg);

  let lastTopJson = "";
  let lastWikiJson = "";
  let currentTotal = 0;
  let activeWikiKey = null;
  let wedgeEntries = [];

  function applyDefaultRoseReadout() {
    wikiKicker.textContent = `Top 10 · ${currentTotal.toLocaleString("en-US")} edits`;
    rose.centerVal.textContent = currentTotal.toLocaleString("en-US");
    rose.centerSub.textContent = "EDITS";
    for (const entry of wedgeEntries) {
      entry.node.setAttribute("opacity", "1");
    }
  }

  function highlightWiki(wikiKey) {
    const match = wedgeEntries.find((entry) => entry.data.key === wikiKey);
    if (!match) {
      activeWikiKey = null;
      applyDefaultRoseReadout();
      return;
    }
    activeWikiKey = wikiKey;
    const { data: w, node } = match;
    wikiKicker.textContent = `${w.key} · ${w.value.toLocaleString("en-US")} edits (${w.pct}%)`;
    rose.centerVal.textContent = `${w.pct}%`;
    rose.centerSub.textContent = w.key.toUpperCase().slice(0, 10);
    for (const entry of wedgeEntries) {
      entry.node.setAttribute("opacity", entry.node === node ? "1" : "0.38");
    }
  }

  // Delegated wedge interactions: 3 persistent listeners total instead of 30 recreated every second.
  rose.wedgesGroup.addEventListener("pointerover", (event) => {
    const key = event.target?.closest?.(".rose-wedge")?.dataset?.wikiKey;
    if (key && key !== activeWikiKey) highlightWiki(key);
  });

  rose.wedgesGroup.addEventListener("focusin", (event) => {
    const key = event.target?.closest?.(".rose-wedge")?.dataset?.wikiKey;
    if (key) highlightWiki(key);
  });

  rose.wedgesGroup.addEventListener("focusout", (event) => {
    if (!rose.wedgesGroup.contains(event.relatedTarget)) {
      activeWikiKey = null;
      applyDefaultRoseReadout();
    }
  });

  rose.svg.addEventListener("pointerleave", () => {
    activeWikiKey = null;
    applyDefaultRoseReadout();
  });

  function renderTopArticles(articles = []) {
    const rows = articles.slice(0, 10);
    const sig = JSON.stringify(rows);
    if (sig === lastTopJson) return;
    lastTopJson = sig;

    if (rows.length === 0) {
      topEmpty.hidden = false;
      topList.hidden = true;
      return;
    }

    topEmpty.hidden = true;
    topList.hidden = false;
    renderLedgerRows(
      topList,
      rows.map((row) => ({ label: row.title, count: row.count, href: row.link })),
    );
  }

  function renderCompassRose(langCounts = {}) {
    const items = Object.entries(langCounts)
      .map(([key, value]) => ({ key, value: Number(value) || 0 }))
      .filter((item) => item.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);

    const sig = JSON.stringify(items);
    if (sig === lastWikiJson) return;
    lastWikiJson = sig;

    const { wedges, total } = computeCompassWedges(items, {
      cx: CX,
      cy: CY,
      innerR: INNER_R,
      maxR: MAX_R,
      labelR: LABEL_R,
    });

    currentTotal = total;

    if (wedges.length === 0) {
      wikiEmpty.hidden = false;
      wikiPlate.hidden = true;
      wikiKicker.textContent = "Top 10 · edit share";
      activeWikiKey = null;
      wedgeEntries = [];
      rose.wedgesGroup.replaceChildren();
      return;
    }

    wikiEmpty.hidden = true;
    wikiPlate.hidden = false;

    // Preserve keyboard focus across live 1s data ticks.
    const prevFocusedKey = rose.wedgesGroup.contains(document.activeElement)
      ? document.activeElement?.dataset?.wikiKey ?? null
      : null;

    const frag = document.createDocumentFragment();
    const nextEntries = [];

    wedges.forEach((w, idx) => {
      const style = ROSE_STYLES[idx % ROSE_STYLES.length];
      const g = svgEl("g", {
        class: "rose-wedge",
        tabindex: "0",
        role: "listitem",
        "data-wiki-key": w.key,
        "aria-label": `${w.key}: ${w.value} edits (${w.pct}%)`,
      });

      const titleEl = svgEl("title");
      titleEl.textContent = `${w.key} — ${w.value.toLocaleString("en-US")} edits (${w.pct}%)`;
      g.append(titleEl);

      g.append(
        svgEl("path", { d: w.path, fill: style.wash, "fill-opacity": style.opacity }),
        svgEl("path", { d: w.path, fill: `url(#${uid}-${style.pattern})` }),
        svgEl("path", {
          d: w.path,
          fill: "none",
          stroke: style.border,
          "stroke-width": idx === 0 ? 1.25 : 0.9,
          "stroke-opacity": 0.78,
        }),
      );

      const [elbowX, elbowY] = polarToCartesian(CX, CY, LABEL_R - 4, w.midAngle);
      const tickX = w.anchor === "start" ? elbowX + 12 : w.anchor === "end" ? elbowX - 12 : elbowX;
      g.append(
        svgEl("polyline", {
          points: `${w.edgeX.toFixed(1)},${w.edgeY.toFixed(1)} ${elbowX.toFixed(1)},${elbowY.toFixed(1)} ${tickX.toFixed(1)},${elbowY.toFixed(1)}`,
          fill: "none",
          stroke: "var(--ink-rule)",
          "stroke-width": 0.7,
          "stroke-opacity": 0.55,
        }),
      );

      const textX = w.anchor === "start" ? tickX + 5 : w.anchor === "end" ? tickX - 5 : elbowX;
      const textY = w.anchor === "middle" ? (elbowY < CY ? elbowY - 7 : elbowY + 13) : elbowY + 3;

      const labelEl = svgEl("text", {
        x: textX.toFixed(1),
        y: textY.toFixed(1),
        "text-anchor": w.anchor,
        class: idx === 0 ? "rose-label is-lead" : "rose-label",
      });
      labelEl.textContent = `${w.key} `;
      const pctSpan = svgEl("tspan", { class: "rose-label-pct" });
      pctSpan.textContent = `${w.pct}%`;
      labelEl.append(pctSpan);
      g.append(labelEl);

      nextEntries.push({ data: w, node: g });
      frag.append(g);
    });

    wedgeEntries = nextEntries;
    rose.wedgesGroup.replaceChildren(frag);

    if (prevFocusedKey) {
      const focused = wedgeEntries.find((entry) => entry.data.key === prevFocusedKey);
      if (focused) {
        focused.node.focus({ preventScroll: true });
      }
    }

    if (activeWikiKey) {
      highlightWiki(activeWikiKey);
    } else {
      applyDefaultRoseReadout();
    }
  }

  function renderRatio(gauge, ratioData, trueKey, falseKey) {
    const a = ratioData?.[trueKey] ?? 0;
    const b = ratioData?.[falseKey] ?? 0;
    const total = a + b;
    const pct = total > 0 ? Math.round((ratioData?.ratio ?? 0) * 1000) / 10 : 0;
    gauge.set({
      pctText: `${pct.toFixed(1)}%`,
      fillPct: pct,
      primaryCount: a,
      secondaryCount: b,
    });
  }

  function update(data) {
    if (!data) return;
    renderTopArticles(data.top_articles);
    renderCompassRose(data.lang_counts);
    renderRatio(botGauge, data.bot_ratio, "bot", "human");
    renderRatio(anonGauge, data.anon_ratio, "anon", "registered");
  }

  return { el, update };
}
