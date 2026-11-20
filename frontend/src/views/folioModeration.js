/**
 * Folio II — Live Moderation (symmetric 50/50 open-book spread):
 *  - Verso (left page):  § I   Scrollable manuscript feed of analyzed edits & images
 *  - Recto (right page): § II  Ranked 24h hazard breakdown ledger
 *                        § III & § IV Engraved surveyor scales for 24h edit & image rates
 */

import { hazardLabel } from "../lib/hazardLabels.js";
import {
  createRatioGauge,
  DEFAULT_TOGGLES,
  formatClockUtc,
  renderLedgerRows,
  safeWikiUrl,
} from "../lib/ui.js";

export function createModerationView(uid = "mod") {
  const el = document.createElement("div");
  el.className = "folio-spread moderation-spread";
  el.innerHTML = `
    <div class="open-book-spread">
      <div class="book-page book-verso">
        <section class="folio-block folio-block-scroll" aria-labelledby="${uid}-feed-h">
          <div class="block-head">
            <h2 id="${uid}-feed-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ I</span>
              Live Review Feed
            </h2>
            <span class="block-kicker">flagged in crimson</span>
          </div>
          <p class="archive-empty" data-role="feed-empty">Waiting for analyzed edits and images…</p>
          <div class="chronicle-scroll" data-role="feed-list" role="region" tabindex="0" aria-label="Recently reviewed edits and images" hidden></div>
        </section>
      </div>

      <div class="book-page book-recto book-recto-balanced">
        <section class="folio-block folio-block-scroll" aria-labelledby="${uid}-haz-h">
          <div class="block-head">
            <h2 id="${uid}-haz-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ II</span>
              Flagged Categories
            </h2>
            <span class="block-kicker">last 24 h · flagged only</span>
          </div>
          <p class="archive-empty" data-role="haz-empty">No issues flagged in the last 24 hours.</p>
          <div class="page-scroll" data-role="haz-wrap" hidden>
            <ol class="ledger-list hazard-ledger" role="list" data-role="haz-list"></ol>
          </div>
        </section>

        <hr class="folio-divider" />

        <div class="ratio-pair" data-role="ratio-pair"></div>
      </div>
    </div>
  `;

  const feedEmpty = el.querySelector('[data-role="feed-empty"]');
  const feedList = el.querySelector('[data-role="feed-list"]');
  const hazEmpty = el.querySelector('[data-role="haz-empty"]');
  const hazWrap = el.querySelector('[data-role="haz-wrap"]');
  const hazList = el.querySelector('[data-role="haz-list"]');
  const ratioPair = el.querySelector('[data-role="ratio-pair"]');

  const editGauge = createRatioGauge({
    glyph: "§ III",
    title: "Edits",
    kicker: "flagged · last 24 h",
    tone: "rubric",
    sub: "flagged",
    primaryLabel: "Flagged",
    secondaryLabel: "Clean",
  });
  const imgGauge = createRatioGauge({
    glyph: "§ IV",
    title: "Images",
    kicker: "flagged · last 24 h",
    tone: "rubric",
    sub: "off",
    primaryLabel: "Flagged",
    secondaryLabel: "Clean",
  });
  const imgWrap = document.createElement("div");
  imgWrap.className = "ratio-pair-divider";
  imgWrap.append(imgGauge.el);
  ratioPair.append(editGauge.el, imgWrap);

  let currentToggles = { ...DEFAULT_TOGGLES };
  let lastData = null;

  function renderGauge(gauge, enabled, flagged, analyzed) {
    const total = analyzed ?? 0;
    const marked = flagged ?? 0;
    const clean = Math.max(0, total - marked);
    const pct = total > 0 ? Math.round((marked / total) * 1000) / 10 : 0;

    gauge.set({
      muted: !enabled,
      pctText: enabled ? `${pct.toFixed(1)}%` : "—",
      subText: enabled ? "flagged" : "off",
      fillPct: enabled ? pct : 0,
      primaryCount: marked,
      secondaryCount: clean,
    });
  }

  let lastFeedSig = "";
  let lastHazSig = "";

  function renderFeed(items = [], showSummary = false) {
    const sig = `${showSummary}|${items
      .map(
        (it) =>
          `${it.ts ?? 0}:${it.rev_id ?? it.title ?? ""}:${it.flagged ? 1 : 0}:${it.summary ? 1 : 0}`,
      )
      .join(",")}`;
    if (sig === lastFeedSig) return;
    lastFeedSig = sig;

    if (items.length === 0) {
      feedEmpty.hidden = false;
      feedList.hidden = true;
      return;
    }

    const prevScroll = feedList.scrollTop;
    feedEmpty.hidden = true;
    feedList.hidden = false;

    const frag = document.createDocumentFragment();
    for (const item of items) {
      const flagged = !!item.flagged;
      const article = document.createElement("article");
      article.className = flagged ? "chronicle-entry is-flagged" : "chronicle-entry";

      const meta = document.createElement("div");
      meta.className = "entry-meta";

      const kind = document.createElement("span");
      kind.className = "entry-kind";
      kind.textContent = item.type === "image" ? "Image" : "Edit";
      meta.append(kind);

      if (flagged) {
        const seal = document.createElement("span");
        seal.className = "entry-seal";
        seal.textContent = "Flagged";
        meta.append(seal);
      }

      const user = document.createElement("span");
      user.className = "entry-user";
      user.textContent = item.user || "anonymous";

      const dot = document.createElement("span");
      dot.className = "ink-dot";
      dot.setAttribute("aria-hidden", "true");
      dot.textContent = "·";

      const wiki = document.createElement("span");
      wiki.className = "entry-wiki";
      wiki.textContent = item.wiki || "";

      const timeEl = document.createElement("time");
      timeEl.className = "entry-time";
      timeEl.textContent = `${formatClockUtc((item.ts || 0) * 1000)} UTC`;

      meta.append(user, dot, wiki, timeEl);

      const href = safeWikiUrl(item.link);
      let link;
      if (href) {
        link = document.createElement("a");
        link.href = href;
        link.target = "_blank";
        link.rel = "noreferrer";
      } else {
        link = document.createElement("span");
      }
      link.className = "entry-title";
      link.textContent = item.title || "(untitled)";

      article.append(meta, link);

      if (showSummary && item.summary) {
        const summary = document.createElement("p");
        summary.className = "entry-summary";
        summary.textContent = `“${item.summary}”`;
        article.append(summary);
      }

      const tags = [
        ...(item.categories ?? []).map((c) => hazardLabel(c)),
        ...(item.heur_flags ?? []).map((h) => hazardLabel(`heur:${h}`)),
      ];
      if (flagged && tags.length > 0) {
        const tagsWrap = document.createElement("div");
        tagsWrap.className = "entry-tags";
        for (const tag of tags) {
          const span = document.createElement("span");
          span.className = "entry-tag";
          span.textContent = `❖ ${tag}`;
          tagsWrap.append(span);
        }
        article.append(tagsWrap);
      }

      frag.append(article);
    }

    feedList.replaceChildren(frag);
    feedList.scrollTop = prevScroll;
  }

  function renderHazards(breakdown = {}) {
    const rows = Object.entries(breakdown)
      .map(([code, count]) => ({ code, label: hazardLabel(code), count: Number(count) || 0 }))
      .filter((r) => r.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);

    const sig = JSON.stringify(rows);
    if (sig === lastHazSig) return;
    lastHazSig = sig;

    if (rows.length === 0) {
      hazEmpty.hidden = false;
      hazWrap.hidden = true;
      return;
    }

    hazEmpty.hidden = true;
    hazWrap.hidden = false;
    renderLedgerRows(
      hazList,
      rows.map((row) => ({ label: row.label, count: row.count })),
    );
  }

  renderGauge(editGauge, true, 0, 0);
  renderGauge(imgGauge, false, 0, 0);

  function setToggles(toggles) {
    if (!toggles) return;
    currentToggles = { ...currentToggles, ...toggles };
    renderGauge(editGauge, !!currentToggles.detect_edits, lastData?.flagged_edits, lastData?.analyzed);
    renderGauge(
      imgGauge,
      !!currentToggles.detect_images,
      lastData?.flagged_images,
      lastData?.images_analyzed,
    );
    if (lastData) {
      renderFeed(lastData.recent_analyzed ?? [], !!currentToggles.summarize);
    }
  }

  function update(data) {
    if (!data) return;
    lastData = data;
    currentToggles = { ...currentToggles, ...(data.toggles ?? {}) };
    renderGauge(editGauge, !!currentToggles.detect_edits, data.flagged_edits, data.analyzed);
    renderGauge(imgGauge, !!currentToggles.detect_images, data.flagged_images, data.images_analyzed);
    renderFeed(data.recent_analyzed ?? [], !!currentToggles.summarize);
    renderHazards(data.hazard_breakdown ?? {});
  }

  return { el, update, setToggles };
}
