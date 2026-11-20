import assert from "node:assert/strict";
import test from "node:test";

import { createPaperGrainDataUrl } from "../src/lib/antiquePaper.js";
import { computeCompassWedges } from "../src/lib/compassRose.js";
import { HAZARD_CATALOG, hazardLabel } from "../src/lib/hazardLabels.js";
import {
  computeCurlGeometry,
  easePaper,
  toCssPolygon,
  toSvgPoints,
} from "../src/lib/pageCurl.js";
import { subscribeSSE } from "../src/lib/sse.js";
import {
  createRatioGauge,
  DEFAULT_TOGGLES,
  formatClockUtc,
  renderLedgerRows,
  safeWikiUrl,
} from "../src/lib/ui.js";

/** Minimal in-memory DOM shim for testing pure DOM builders with zero external deps. */
function withMockDom(fn) {
  class MockNode {
    constructor(tag) {
      this.tagName = tag;
      this.className = "";
      this.children = [];
      this.attrs = {};
      this.dataset = {};
      this.style = {};
      this.textContent = "";
      const classes = new Set();
      this.classList = {
        toggle: (name, force) => {
          if (force) classes.add(name);
          else classes.delete(name);
        },
        has: (name) => classes.has(name),
      };
    }
    setAttribute(k, v) {
      this.attrs[k] = v;
    }
    append(...nodes) {
      this.children.push(...nodes);
    }
    replaceChildren(...nodes) {
      const next = [];
      for (const n of nodes) {
        if (n?.tagName === "#fragment") next.push(...n.children);
        else next.push(n);
      }
      this.children = next;
    }
    findByClass(name) {
      if (this.className.split(/\s+/).includes(name)) return this;
      for (const child of this.children) {
        if (child instanceof MockNode) {
          const hit = child.findByClass(name);
          if (hit) return hit;
        }
      }
      return null;
    }
  }

  let canvasCalls = 0;
  const origDoc = globalThis.document;
  globalThis.document = {
    createElement: (tag) => {
      if (tag === "canvas") {
        canvasCalls += 1;
        const el = new MockNode(tag);
        el.getContext = () => ({
          createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
          putImageData: () => {},
        });
        el.toDataURL = () => `data:image/png;base64,size-${el.width}x${el.height}-call-${canvasCalls}`;
        return el;
      }
      return new MockNode(tag);
    },
    createDocumentFragment: () => new MockNode("#fragment"),
    createTextNode: (text) => ({ nodeType: 3, textContent: text }),
  };

  try {
    return fn({ MockNode, getCanvasCalls: () => canvasCalls });
  } finally {
    globalThis.document = origDoc;
  }
}

test("computeCompassWedges produces sorted wedges with valid paths and percentages", () => {
  const items = [
    { key: "eswiki", value: 12 },
    { key: "enwiki", value: 50 },
    { key: "wikidatawiki", value: 38 },
  ];
  const { wedges, total } = computeCompassWedges(items);

  assert.equal(total, 100);
  assert.equal(wedges.length, 3);
  assert.equal(wedges[0].key, "enwiki");
  assert.equal(wedges[0].pct, "50.0");
  assert.ok(wedges[0].outerR > wedges[1].outerR);
  assert.ok(wedges[1].outerR > wedges[2].outerR);
  for (const w of wedges) {
    assert.ok(w.path.startsWith("M ") && w.path.endsWith(" Z"));
  }
});

test("computeCompassWedges handles empty and zero-value inputs cleanly", () => {
  assert.deepEqual(computeCompassWedges([]), { wedges: [], total: 0 });
  assert.deepEqual(computeCompassWedges([{ key: "a", value: 0 }]), { wedges: [], total: 0 });
});

test("hazardLabel resolves active semantic codes, heuristics, and legacy fallbacks", () => {
  assert.equal(HAZARD_CATALOG.length, 7);
  assert.equal(hazardLabel("vandalism"), "Vandalism & Hoaxes");
  assert.equal(hazardLabel("heur:blanking"), "Page Blanking");
  assert.equal(hazardLabel("S10"), "Hate");
  assert.equal(hazardLabel("unknown_code"), "unknown_code");
});

test("computeCurlGeometry peels symmetrically from bottom-right and mirrored bottom-left", () => {
  const W = 1200;
  const H = 600;

  const flat = computeCurlGeometry(W, H, 0, "right");
  assert.equal(flat.keepPoly.length, 4);
  assert.equal(flat.curlPoly.length, 0);

  const rightPeek = computeCurlGeometry(W, H, 0.07, "right");
  const leftPeek = computeCurlGeometry(W, H, 0.07, "left");
  assert.equal(rightPeek.keepPoly.length, 5);
  assert.equal(leftPeek.keepPoly.length, 5);
  assert.equal(rightPeek.curlPoly.length, 3);
  assert.equal(leftPeek.curlPoly.length, 3);
  assert.ok(toCssPolygon(leftPeek.keepPoly).startsWith("polygon("));
  assert.ok(toSvgPoints(leftPeek.curlPoly).length > 0);

  for (let i = 0; i < rightPeek.curlPoly.length; i += 1) {
    assert.ok(Math.abs(rightPeek.curlPoly[i][0] + leftPeek.curlPoly[i][0] - W) < 1e-6);
    assert.ok(Math.abs(rightPeek.curlPoly[i][1] - leftPeek.curlPoly[i][1]) < 1e-6);
  }

  assert.equal(computeCurlGeometry(W, H, 1, "right").keepPoly.length, 0);
  assert.equal(computeCurlGeometry(W, H, 1, "left").keepPoly.length, 0);
});

test("easePaper is continuous and monotonic across the midpoint", () => {
  assert.equal(easePaper(0), 0);
  assert.equal(easePaper(0.5), 0.5);
  assert.equal(easePaper(1), 1);
  assert.ok(Math.abs(easePaper(0.4999) - easePaper(0.5001)) < 0.001);
});

test("ui helpers sanitize URLs, format UTC clocks, and freeze default toggles", () => {
  assert.equal(
    safeWikiUrl("https://es.wikipedia.org/wiki/Madrid"),
    "https://es.wikipedia.org/wiki/Madrid",
  );
  assert.equal(safeWikiUrl("javascript:alert(1)"), null);
  assert.equal(safeWikiUrl("not-a-url"), null);
  assert.equal(safeWikiUrl(null), null);

  assert.equal(formatClockUtc("2026-11-20T14:35:09Z", "—"), "14:35:09");
  assert.equal(formatClockUtc(null, "—"), "—");
  assert.equal(formatClockUtc("raw-label", "—"), "raw-label");
  assert.equal(formatClockUtc(0), "00:00:00");
  assert.equal(formatClockUtc(Number.NaN), "--:--:--");

  assert.equal(Object.isFrozen(DEFAULT_TOGGLES), true);
  assert.equal(DEFAULT_TOGGLES.detect_edits, true);
});

test("subscribeSSE deduplicates identical frames and ignores malformed JSON", () => {
  let instance = null;
  let closed = false;
  const origEventSource = globalThis.EventSource;
  globalThis.EventSource = class MockEventSource {
    constructor(url) {
      this.url = url;
      this.onmessage = null;
      this.onerror = null;
      instance = this;
    }
    close() {
      closed = true;
    }
  };

  try {
    const received = [];
    const unsubscribe = subscribeSSE("/api/stream", (msg) => received.push(msg));
    assert.equal(instance.url, "/api/stream");

    instance.onmessage({ data: '{"a":1}' });
    instance.onmessage({ data: '{"a":1}' }); // duplicate skipped
    instance.onmessage({ data: "not-json" }); // malformed ignored
    instance.onmessage({ data: '{"a":2}' });

    assert.deepEqual(received, [{ a: 1 }, { a: 2 }]);
    unsubscribe();
    assert.equal(closed, true);
  } finally {
    globalThis.EventSource = origEventSource;
  }
});

test("createRatioGauge builds expected structure and updates muted/percent state", () => {
  withMockDom(() => {
    const gauge = createRatioGauge({
      glyph: "§ III",
      title: "Edits",
      kicker: "flagged · last 24 h",
      tone: "rubric",
      sub: "flagged",
      primaryLabel: "Flagged",
      secondaryLabel: "Clean",
    });

    assert.equal(gauge.el.className, "folio-block ratio-block ratio-rubric");

    gauge.set({
      pctText: "12.5%",
      fillPct: 12.5,
      subText: "flagged",
      primaryCount: 5,
      secondaryCount: 35,
      muted: false,
    });
    assert.equal(gauge.el.classList.has("is-muted"), false);
    assert.equal(gauge.el.findByClass("ratio-pct").textContent, "12.5%");
    assert.equal(gauge.el.findByClass("ratio-fill").style.width, "12.5%");

    gauge.set({
      pctText: "—",
      fillPct: 0,
      subText: "off",
      primaryCount: 0,
      secondaryCount: 0,
      muted: true,
    });
    assert.equal(gauge.el.classList.has("is-muted"), true);
    assert.equal(gauge.el.findByClass("ratio-sub").textContent, "off");
  });
});

test("renderLedgerRows creates Roman-indexed rows with safe links and proportional bars", () => {
  withMockDom(({ MockNode }) => {
    const ol = new MockNode("ol");
    renderLedgerRows(ol, [
      { label: "Python", count: 20, href: "https://en.wikipedia.org/wiki/Python" },
      { label: "BadLink", count: 10, href: "javascript:alert(1)" },
    ]);

    assert.equal(ol.children.length, 2);
    const [first, second] = ol.children;
    assert.equal(first.dataset.roman, "I");
    assert.equal(first.findByClass("ledger-title").tagName, "a");
    assert.equal(first.findByClass("ledger-title").href, "https://en.wikipedia.org/wiki/Python");
    assert.equal(first.findByClass("ledger-fill").style.width, "100%");
    assert.equal(first.findByClass("ledger-num").textContent, "20");

    assert.equal(second.dataset.roman, "II");
    assert.equal(second.findByClass("ledger-title").tagName, "span");
    assert.equal(second.findByClass("ledger-fill").style.width, "50%");
  });
});

test("createPaperGrainDataUrl caches generated PNG data URLs per tile size", () => {
  withMockDom(({ getCanvasCalls }) => {
    const a1 = createPaperGrainDataUrl(32);
    const a2 = createPaperGrainDataUrl(32);
    const b1 = createPaperGrainDataUrl(64);

    assert.equal(a1, a2);
    assert.notEqual(a1, b1);
    assert.equal(getCanvasCalls(), 2);
  });
});
