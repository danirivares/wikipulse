/**
 * Shared DOM, formatting, and state primitives reused across folio views.
 */

export const ROMAN_RANKS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];

export const DEFAULT_TOGGLES = Object.freeze({
  detect_edits: true,
  detect_images: false,
  summarize: false,
  exclude_bots: true,
  only_anon_new: false,
});

/** Return a canonical http/https URL string, or null if unsafe/malformed. */
export function safeWikiUrl(raw) {
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") {
      return parsed.href;
    }
  } catch {
    // Malformed URL falls through to null.
  }
  return null;
}

/** Format an ISO string or epoch-ms timestamp as `HH:MM:SS` (UTC). */
export function formatClockUtc(value, fallback = "--:--:--") {
  if (value === null || value === undefined || value === "") return fallback;
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) {
    return typeof value === "string" ? value : fallback;
  }
  return d.toISOString().slice(11, 19);
}

/**
 * Render a ranked Roman-numeral manuscript ledger list (`<ol class="ledger-list">`).
 * Each row has `{ label: string, count: number, href?: string | null }`.
 */
export function renderLedgerRows(listEl, rows) {
  const max = rows[0]?.count || 1;
  const frag = document.createDocumentFragment();

  rows.forEach((row, idx) => {
    const li = document.createElement("li");
    li.className = "ledger-row";
    li.dataset.roman = ROMAN_RANKS[idx] ?? String(idx + 1);

    const href = safeWikiUrl(row.href);
    let title;
    if (href) {
      title = document.createElement("a");
      title.href = href;
      title.target = "_blank";
      title.rel = "noreferrer";
    } else {
      title = document.createElement("span");
    }
    title.className = "ledger-title";
    title.textContent = row.label;

    const leader = document.createElement("span");
    leader.className = "ledger-leader";
    leader.setAttribute("aria-hidden", "true");

    const meter = document.createElement("span");
    meter.className = "ledger-meter";

    const track = document.createElement("span");
    track.className = "ledger-track";

    const fill = document.createElement("span");
    fill.className = "ledger-fill";
    fill.style.width = `${(row.count / max) * 100}%`;
    track.append(fill);

    const num = document.createElement("span");
    num.className = "ledger-num";
    num.textContent = String(row.count);

    meter.append(track, num);
    li.append(title, leader, meter);
    frag.append(li);
  });

  listEl.replaceChildren(frag);
}

/**
 * Create a reusable Engraved Surveyor Ratio Gauge (`<section class="folio-block ratio-block">`).
 * Shared across Folio I (Bots/Anons) and Folio II (Edits/Images) with identical DOM structure.
 */
export function createRatioGauge({
  glyph,
  title,
  kicker,
  tone = "ink",
  sub = "",
  primaryLabel,
  secondaryLabel,
}) {
  const root = document.createElement("section");
  root.className = `folio-block ratio-block ratio-${tone}`;

  const head = document.createElement("div");
  head.className = "block-head block-head-compact";

  const heading = document.createElement("h2");
  heading.className = "block-title";
  const glyphSpan = document.createElement("span");
  glyphSpan.className = "section-glyph";
  glyphSpan.setAttribute("aria-hidden", "true");
  glyphSpan.textContent = glyph;
  heading.append(glyphSpan, document.createTextNode(title));

  const kickerEl = document.createElement("span");
  kickerEl.className = "block-kicker";
  kickerEl.textContent = kicker;
  head.append(heading, kickerEl);

  const headline = document.createElement("div");
  headline.className = "ratio-headline";
  const pctEl = document.createElement("span");
  pctEl.className = "ratio-pct";
  pctEl.textContent = "0.0%";
  const subEl = document.createElement("span");
  subEl.className = "ratio-sub";
  subEl.textContent = sub;
  headline.append(pctEl, subEl);

  const scale = document.createElement("div");
  scale.className = "ratio-scale";
  scale.setAttribute("aria-hidden", "true");
  const rule = document.createElement("div");
  rule.className = "ratio-rule";
  const fillEl = document.createElement("span");
  fillEl.className = "ratio-fill";
  fillEl.style.width = "0%";
  rule.append(fillEl);
  const ticks = document.createElement("div");
  ticks.className = "ratio-ticks";
  for (let i = 0; i < 5; i += 1) {
    ticks.append(document.createElement("span"));
  }
  scale.append(rule, ticks);

  const legend = document.createElement("div");
  legend.className = "ratio-legend";
  const primaryWrap = document.createElement("span");
  const primaryVal = document.createElement("strong");
  primaryVal.textContent = "0";
  primaryWrap.append(`${primaryLabel} · `, primaryVal);
  const secondaryWrap = document.createElement("span");
  const secondaryVal = document.createElement("strong");
  secondaryVal.textContent = "0";
  secondaryWrap.append(`${secondaryLabel} · `, secondaryVal);
  legend.append(primaryWrap, secondaryWrap);

  root.append(head, headline, scale, legend);

  function set({ pctText, fillPct, subText, primaryCount, secondaryCount, muted = false }) {
    root.classList.toggle("is-muted", muted);
    pctEl.textContent = pctText;
    if (subText !== undefined) subEl.textContent = subText;
    fillEl.style.width = `${fillPct}%`;
    primaryVal.textContent = (primaryCount ?? 0).toLocaleString("en-US");
    secondaryVal.textContent = (secondaryCount ?? 0).toLocaleString("en-US");
  }

  return { el: root, set };
}
