/**
 * Pre-baked antique parchment patina & rag-paper grain textures.
 *
 * Renders organic watercolor stains, oxidized perimeter/corner wear, and archival
 * foxing ONCE onto a static bitmap `<canvas>` per folio instead of live DOM SVG
 * `feTurbulence`/`feDisplacementMap`/`feGaussianBlur` filters. During page-turn
 * animations the browser simply clips and composites a cached GPU texture.
 */

const CANVAS_W = 960;
const CANVAS_H = 600;
const SCALE_X = CANVAS_W / 1440;
const SCALE_Y = CANVAS_H / 900;

const FOLIO_PATINA = [
  {
    seed: 11,
    splotches: [
      { cx: 120, cy: 760, rx: 165, ry: 110, rot: -14, rgb: "158, 107, 36", op: 0.14 },
      { cx: 1330, cy: 130, rx: 155, ry: 100, rot: 20, rgb: "150, 99, 30", op: 0.13 },
      { cx: 1295, cy: 815, rx: 185, ry: 120, rot: -22, rgb: "138, 87, 24", op: 0.16 },
      { cx: 92, cy: 98, rx: 145, ry: 95, rot: 26, rgb: "143, 92, 28", op: 0.15 },
      { cx: 310, cy: 205, rx: 135, ry: 82, rot: 12, rgb: "176, 125, 50", op: 0.085 },
      { cx: 880, cy: 650, rx: 155, ry: 98, rot: -10, rgb: "158, 109, 40", op: 0.075 },
      { cx: 525, cy: 520, rx: 120, ry: 74, rot: 18, rgb: "178, 130, 56", op: 0.06 },
    ],
    flecks: [
      [84, 212, 1.5], [142, 690, 1.9], [218, 824, 1.2], [390, 118, 1.3], [612, 795, 1.1],
      [845, 132, 1.5], [1048, 224, 1.2], [1220, 742, 1.8], [1346, 610, 1.4], [1368, 265, 1.6],
      [195, 448, 1.0], [462, 742, 1.0], [964, 798, 1.4], [1162, 92, 1.3], [1288, 845, 1.7],
      [62, 540, 1.4], [312, 628, 1.0], [1095, 470, 1.1], [790, 846, 1.3], [534, 82, 1.2],
    ],
  },
  {
    seed: 29,
    splotches: [
      { cx: 1345, cy: 775, rx: 175, ry: 112, rot: -18, rgb: "141, 90, 26", op: 0.15 },
      { cx: 108, cy: 135, rx: 158, ry: 102, rot: 16, rgb: "152, 102, 34", op: 0.14 },
      { cx: 165, cy: 820, rx: 170, ry: 108, rot: 11, rgb: "140, 89, 25", op: 0.15 },
      { cx: 1315, cy: 96, rx: 140, ry: 90, rot: -24, rgb: "143, 93, 30", op: 0.14 },
      { cx: 1020, cy: 185, rx: 140, ry: 85, rot: -15, rgb: "173, 123, 50", op: 0.08 },
      { cx: 430, cy: 615, rx: 145, ry: 88, rot: 22, rgb: "162, 113, 44", op: 0.075 },
    ],
    flecks: [
      [96, 148, 1.7], [168, 764, 1.4], [280, 94, 1.3], [548, 820, 1.2], [648, 165, 1.1],
      [818, 745, 1.5], [984, 118, 1.6], [1185, 688, 1.3], [1344, 488, 1.7], [1374, 152, 1.5],
      [114, 462, 1.2], [386, 378, 1.0], [1045, 818, 1.4], [1258, 286, 1.2], [1310, 824, 1.8],
      [74, 712, 1.5], [492, 232, 1.0], [1142, 392, 1.1], [860, 290, 1.0], [230, 610, 1.3],
    ],
  },
  {
    seed: 47,
    splotches: [
      { cx: 135, cy: 790, rx: 178, ry: 114, rot: -12, rgb: "139, 88, 25", op: 0.15 },
      { cx: 1320, cy: 795, rx: 170, ry: 108, rot: 18, rgb: "145, 93, 28", op: 0.15 },
      { cx: 1285, cy: 112, rx: 152, ry: 96, rot: -20, rgb: "154, 103, 34", op: 0.14 },
      { cx: 95, cy: 115, rx: 142, ry: 92, rot: 22, rgb: "146, 96, 30", op: 0.14 },
      { cx: 590, cy: 230, rx: 140, ry: 82, rot: -14, rgb: "170, 120, 48", op: 0.075 },
      { cx: 940, cy: 560, rx: 155, ry: 94, rot: 16, rgb: "159, 110, 42", op: 0.075 },
    ],
    flecks: [
      [72, 180, 1.6], [156, 810, 1.8], [244, 146, 1.2], [472, 790, 1.3], [610, 110, 1.1],
      [832, 178, 1.4], [1024, 760, 1.6], [1202, 204, 1.3], [1352, 540, 1.6], [1362, 198, 1.4],
      [126, 512, 1.3], [344, 682, 1.0], [1110, 840, 1.5], [1292, 360, 1.2], [1328, 842, 1.7],
      [88, 340, 1.2], [520, 448, 1.0], [960, 315, 1.1], [775, 792, 1.2], [202, 286, 1.1],
    ],
  },
];

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Paint a soft, irregular multi-lobe watercolor stain without live SVG filters. */
function drawOrganicSplotch(ctx, s, rand) {
  const cx = s.cx * SCALE_X;
  const cy = s.cy * SCALE_Y;
  const rx = s.rx * SCALE_X;
  const ry = s.ry * SCALE_Y;
  const baseRad = (s.rot * Math.PI) / 180;

  // Layer 4 slightly offset, softly feathered ellipses so stains read organic, never geometric.
  for (let lobe = 0; lobe < 4; lobe += 1) {
    const ox = (rand() - 0.5) * rx * 0.42;
    const oy = (rand() - 0.5) * ry * 0.42;
    const lrx = rx * (0.68 + rand() * 0.48);
    const lry = ry * (0.68 + rand() * 0.48);
    const angle = baseRad + (rand() - 0.5) * 0.65;
    const alpha = s.op * (lobe === 0 ? 0.52 : 0.28);

    ctx.save();
    ctx.translate(cx + ox, cy + oy);
    ctx.rotate(angle);
    ctx.scale(1, lry / lrx);

    const grad = ctx.createRadialGradient(0, 0, lrx * 0.08, 0, 0, lrx);
    grad.addColorStop(0, `rgba(${s.rgb}, ${alpha.toFixed(4)})`);
    grad.addColorStop(0.55, `rgba(${s.rgb}, ${(alpha * 0.58).toFixed(4)})`);
    grad.addColorStop(1, `rgba(${s.rgb}, 0)`);

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(0, 0, lrx, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

/** Paint uneven sepia-amber perimeter oxidation and thumb-worn corners. */
function drawEdgePatina(ctx, rand) {
  const edges = [
    ctx.createLinearGradient(0, 0, 0, 44),
    ctx.createLinearGradient(0, CANVAS_H, 0, CANVAS_H - 44),
    ctx.createLinearGradient(0, 0, 44, 0),
    ctx.createLinearGradient(CANVAS_W, 0, CANVAS_W - 44, 0),
  ];
  for (const grad of edges) {
    grad.addColorStop(0, "rgba(124, 79, 24, 0.22)");
    grad.addColorStop(0.45, "rgba(124, 79, 24, 0.07)");
    grad.addColorStop(1, "rgba(124, 79, 24, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  }

  // Organic corner thumb-wear darkening
  const corners = [
    [0, 0, 74, 0.2],
    [CANVAS_W, 0, 80, 0.2],
    [0, CANVAS_H, 88, 0.24],
    [CANVAS_W, CANVAS_H, 92, 0.25],
  ];
  for (const [x, y, r, alpha] of corners) {
    const jitterR = r * (0.92 + rand() * 0.16);
    const grad = ctx.createRadialGradient(x, y, 0, x, y, jitterR);
    grad.addColorStop(0, `rgba(102, 60, 16, ${alpha})`);
    grad.addColorStop(0.55, `rgba(110, 67, 18, ${(alpha * 0.4).toFixed(3)})`);
    grad.addColorStop(1, "rgba(110, 67, 18, 0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
  }
}

export function createAntiquePaperOverlay(folioIndex = 0) {
  const variant = FOLIO_PATINA[folioIndex % FOLIO_PATINA.length];
  const canvas = document.createElement("canvas");
  canvas.className = "folio-antique-overlay";
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;
  canvas.setAttribute("aria-hidden", "true");

  const ctx = canvas.getContext("2d");
  if (!ctx) return canvas;

  const rand = mulberry32(variant.seed);

  for (const s of variant.splotches) {
    drawOrganicSplotch(ctx, s, rand);
  }

  drawEdgePatina(ctx, rand);

  // Delicate archival foxing flecks
  variant.flecks.forEach(([x, y, r], i) => {
    ctx.fillStyle =
      i % 5 === 0
        ? `rgba(130, 32, 26, ${i % 3 === 0 ? 0.14 : 0.09})`
        : `rgba(108, 67, 24, ${i % 3 === 0 ? 0.14 : 0.09})`;
    ctx.beginPath();
    ctx.arc(x * SCALE_X, y * SCALE_Y, Math.max(0.8, r * SCALE_X), 0, Math.PI * 2);
    ctx.fill();
  });

  return canvas;
}

const grainUrlCache = new Map();

/**
 * Bake a tiny seamless rag-paper micro-grain tile once (128x128 PNG data URL).
 * Reused by CSS parchment backgrounds and the page-curl SVG `<pattern>` so zero
 * live `feTurbulence` noise is ever evaluated during animations.
 */
export function createPaperGrainDataUrl(size = 128) {
  const cached = grainUrlCache.get(size);
  if (cached) return cached;

  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return "";

  const img = ctx.createImageData(size, size);
  const data = img.data;
  const rand = mulberry32(9017);

  for (let i = 0; i < data.length; i += 4) {
    const n = rand();
    // Subtle warm iron-gall / raw-umber paper fiber speckle
    const warm = n > 0.5;
    data[i] = warm ? 112 : 68;
    data[i + 1] = warm ? 78 : 44;
    data[i + 2] = warm ? 34 : 16;
    data[i + 3] = Math.floor(Math.abs(n - 0.5) * 38);
  }

  ctx.putImageData(img, 0, 0);
  const url = canvas.toDataURL("image/png");
  grainUrlCache.set(size, url);
  return url;
}
