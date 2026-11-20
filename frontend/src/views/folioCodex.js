/**
 * Folio III — Moderation Rules:
 *  - § I   Illuminated moderation categories reference
 *  - § II  Structural metadata checks
 */

import { HAZARD_CATALOG, HEURISTIC_CATALOG } from "../lib/hazardLabels.js";

function renderDefinitionList(items) {
  const dl = document.createElement("dl");
  dl.className = "codex-list";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "codex-entry";

    const dt = document.createElement("dt");
    dt.className = "codex-term";
    const name = document.createElement("span");
    name.className = "codex-name";
    name.textContent = item.label;
    const code = document.createElement("code");
    code.className = "codex-code";
    code.textContent = item.code;
    dt.append(name, code);

    const dd = document.createElement("dd");
    dd.className = "codex-desc";
    dd.textContent = item.scope;

    row.append(dt, dd);
    dl.append(row);
  }
  return dl;
}

export function createCodexView(uid = "cdx") {
  const el = document.createElement("div");
  el.className = "folio-spread codex-spread";
  el.innerHTML = `
    <div class="open-book-spread spread-codex">
      <div class="book-page book-verso">
        <section class="folio-block folio-block-scroll" aria-labelledby="${uid}-haz-h">
          <div class="block-head">
            <h2 id="${uid}-haz-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ I</span>
              Moderation Categories
            </h2>
            <span class="block-kicker">AI check · encyclopedic context</span>
          </div>
          <p class="codex-preface">
            Neutral encyclopedic coverage of history, medicine, biographies, or conflict is allowed.
            Only edits and images that add vandalism, abuse, or harmful content are flagged.
          </p>
          <div class="page-scroll" data-role="codex-hazards"></div>
        </section>
      </div>

      <div class="book-page book-recto">
        <section class="folio-block folio-block-scroll" aria-labelledby="${uid}-heur-h">
          <div class="block-head">
            <h2 id="${uid}-heur-h" class="block-title">
              <span class="section-glyph" aria-hidden="true">§ II</span>
              Structural Checks
            </h2>
            <span class="block-kicker">instant metadata rules</span>
          </div>
          <p class="codex-preface">
            Instant metadata checks run on every edit without calling the AI model, catching mass
            removals and unexplained changes right away.
          </p>
          <div class="page-scroll" data-role="codex-heuristics"></div>
        </section>
      </div>
    </div>
  `;

  el.querySelector('[data-role="codex-hazards"]').append(renderDefinitionList(HAZARD_CATALOG));
  el.querySelector('[data-role="codex-heuristics"]').append(renderDefinitionList(HEURISTIC_CATALOG));

  return { el };
}
