/**
 * Exact geometric paper-peel engine from the real bottom-right corner (`right`,
 * turning forward) or the mirrored bottom-left corner (`left`, turning backward).
 *
 * At every animation frame:
 *  - The crease is the perpendicular bisector between the lifted corner C and
 *    pulled tip P moving along an organic hand-peel arc.
 *  - Sutherland-Hodgman half-plane clipping splits the full folio sheet into:
 *      1. `keepPoly` (remaining flat portion of the outgoing sheet -> CSS clip-path)
 *      2. `peelPoly` (lifted region revealing the next/previous folio underneath)
 *  - Reflecting `peelPoly` across the crease gives `curlPoly` (the curled-back
 *    parchment underside) with an exact flush crease seam and gently bowed free
 *    outer edges, plus cylindrical roll & cast-under-page shadow gradients.
 */

const EPS = 1e-6;

function clipPolygonHalfPlane(poly, mx, my, nx, ny, keepNegative) {
  if (poly.length === 0) return [];
  const out = [];
  const sign = keepNegative ? -1 : 1;

  for (let i = 0; i < poly.length; i += 1) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    const da = sign * ((a[0] - mx) * nx + (a[1] - my) * ny);
    const db = sign * ((b[0] - mx) * nx + (b[1] - my) * ny);
    const aIn = da >= -EPS;
    const bIn = db >= -EPS;

    if (aIn && bIn) {
      out.push(b);
    } else if (aIn && !bIn) {
      const denom = da - db;
      if (Math.abs(denom) > EPS) {
        const k = da / denom;
        out.push([a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1])]);
      }
    } else if (!aIn && bIn) {
      const denom = da - db;
      if (Math.abs(denom) > EPS) {
        const k = da / denom;
        out.push([a[0] + k * (b[0] - a[0]), a[1] + k * (b[1] - a[1])]);
      }
      out.push(b);
    }
  }
  return out;
}

function reflectPoint(x, y, mx, my, nx, ny, nLen2) {
  const dot = (x - mx) * nx + (y - my) * ny;
  const factor = (2 * dot) / nLen2;
  return [x - factor * nx, y - factor * ny];
}

function mirrorPolyX(poly, width) {
  return poly.map(([x, y]) => [width - x, y]);
}

function flatGeometry(rect, width, height, isLeft) {
  const originX = isLeft ? 0 : width;
  return {
    keepPoly: rect,
    peelPoly: [],
    curlPoly: [],
    gradStart: [originX, height],
    gradEnd: [originX, height],
    underGradStart: [originX, height],
    underGradEnd: [originX, height],
    creaseMid: [originX, height],
    creaseNormal: [isLeft ? -1 : 1, 0],
    shadowStrength: 0,
  };
}

/**
 * Compute exact page-curl polygons and lighting axes for progress `u` in [0, 1]
 * from either `corner = "right"` (bottom-right -> upper-left) or `corner = "left"`
 * (exact horizontal mirror: bottom-left -> upper-right).
 */
export function computeCurlGeometry(width, height, u, corner = "right") {
  const t = Math.max(0, Math.min(1, u));
  const rect = [
    [0, 0],
    [width, 0],
    [width, height],
    [0, height],
  ];

  const isLeft = corner === "left";

  if (t <= 0.001 || width <= 0 || height <= 0) {
    return flatGeometry(rect, width, height, isLeft);
  }

  // Natural full-page hand-peel arc from exact (W, H) sweeping all the way past (0, 0)
  // on any viewport aspect ratio (guaranteed px^2 > W^2 + H^2 at t = 1).
  const diag = Math.hypot(width, height);
  const px = width - (width + diag * 1.15) * t;
  const lift = Math.sin(Math.min(1, t * 1.1) * Math.PI) * height * 0.24;
  const py = height * (1 - 0.66 * t) - lift;

  const cx = width;
  const cy = height;
  const mx = (cx + px) * 0.5;
  const my = (cy + py) * 0.5;
  const nx = cx - px;
  const ny = cy - py;
  const nLen2 = nx * nx + ny * ny;

  if (nLen2 < EPS) {
    return flatGeometry(rect, width, height, isLeft);
  }

  let keepPoly = clipPolygonHalfPlane(rect, mx, my, nx, ny, true);
  let peelPoly = clipPolygonHalfPlane(rect, mx, my, nx, ny, false);
  let curlPoly = peelPoly.map(([x, y]) => reflectPoint(x, y, mx, my, nx, ny, nLen2));

  const nLen = Math.sqrt(nLen2);
  const ux = -nx / nLen;
  const uy = -ny / nLen;
  const span = Math.min(nLen * 0.52, Math.hypot(width, height) * 0.45);
  const underSpan = Math.min(nLen * 0.34, Math.max(44, width * 0.085));

  let gradStart = [mx, my];
  let gradEnd = [mx + ux * span, my + uy * span];
  let underGradStart = [mx, my];
  let underGradEnd = [mx - ux * underSpan, my - uy * underSpan];
  let creaseMid = [mx, my];
  let creaseNormal = [nx / nLen, ny / nLen];

  if (isLeft) {
    keepPoly = mirrorPolyX(keepPoly, width);
    peelPoly = mirrorPolyX(peelPoly, width);
    curlPoly = mirrorPolyX(curlPoly, width);
    gradStart = [width - gradStart[0], gradStart[1]];
    gradEnd = [width - gradEnd[0], gradEnd[1]];
    underGradStart = [width - underGradStart[0], underGradStart[1]];
    underGradEnd = [width - underGradEnd[0], underGradEnd[1]];
    creaseMid = [width - creaseMid[0], creaseMid[1]];
    creaseNormal = [-creaseNormal[0], creaseNormal[1]];
  }

  const shadowStrength = Math.sin(Math.min(1, t) * Math.PI) * 0.92 + (t < 0.16 ? t * 2.4 : 0);

  return {
    keepPoly,
    peelPoly,
    curlPoly,
    gradStart,
    gradEnd,
    underGradStart,
    underGradEnd,
    creaseMid,
    creaseNormal,
    shadowStrength: Math.min(1, shadowStrength),
  };
}

export function toCssPolygon(poly) {
  if (!poly || poly.length < 3) return "polygon(0 0, 0 0, 0 0)";
  return `polygon(${poly.map(([x, y]) => `${x.toFixed(1)}px ${y.toFixed(1)}px`).join(", ")})`;
}

export function toSvgPoints(poly) {
  if (!poly || poly.length < 3) return "";
  return poly.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
}

/** Smooth C1-continuous cubic ease-in-out curve for natural paper momentum. */
export function easePaper(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/**
 * Drives symmetric bottom-right (forward) and bottom-left (backward) corner curls.
 */
export class PageCurlAnimator {
  constructor({
    stageEl,
    overlaySvg,
    underShadowEl,
    underShadowGradEl,
    keepClipPolyEl,
    curlBackEl,
    curlGrainEl,
    curlShadowEl,
    curlShadowGradEl,
    curlGradEl,
  }) {
    this._stage = stageEl;
    this._svg = overlaySvg;
    this._underShadow = underShadowEl;
    this._underShadowGrad = underShadowGradEl;
    this._keepClipPoly = keepClipPolyEl;
    this._curlBack = curlBackEl;
    this._curlGrain = curlGrainEl;
    this._curlShadow = curlShadowEl;
    this._curlShadowGrad = curlShadowGradEl;
    this._curlGrad = curlGradEl;
    this._raf = null;
    this._currentU = 0;
    this._currentCorner = "right";
    this._active = false;
    this._topLayer = null;
    this._stageW = 0;
    this._stageH = 0;
  }

  get isAnimating() {
    return this._active;
  }

  _measureStage() {
    const rect = this._stage.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      if (rect.width !== this._stageW || rect.height !== this._stageH) {
        this._stageW = rect.width;
        this._stageH = rect.height;
        this._svg.setAttribute(
          "viewBox",
          `0 0 ${this._stageW.toFixed(1)} ${this._stageH.toFixed(1)}`,
        );
      }
    }
    return this._stageW > 0 && this._stageH > 0;
  }

  _clearOverlay() {
    this._svg.style.opacity = "0";
    this._curlBack.setAttribute("points", "");
    this._curlShadow.setAttribute("points", "");
    this._curlShadow.setAttribute("opacity", "0");
    if (this._keepClipPoly) this._keepClipPoly.setAttribute("points", "");
    if (this._curlGrain) {
      this._curlGrain.setAttribute("points", "");
      this._curlGrain.setAttribute("opacity", "0");
    }
    if (this._underShadow) {
      this._underShadow.setAttribute("points", "");
      this._underShadow.setAttribute("opacity", "0");
    }
  }

  _apply(topLayerEl, u, corner) {
    const w = this._stageW;
    const h = this._stageH;
    if (w <= 0 || h <= 0) return;

    const geom = computeCurlGeometry(w, h, u, corner);

    if (topLayerEl) {
      topLayerEl.style.clipPath = u <= 0.001 ? "" : toCssPolygon(geom.keepPoly);
    }

    const curlPts = toSvgPoints(geom.curlPoly);
    if (!curlPts || u <= 0.001 || u >= 0.998) {
      this._clearOverlay();
      return;
    }

    this._svg.style.opacity = "1";
    this._curlBack.setAttribute("points", curlPts);
    if (this._curlGrain) {
      this._curlGrain.setAttribute("points", curlPts);
      this._curlGrain.setAttribute("opacity", "1");
    }

    // Cast soft directional shadow under the overhanging flap, strictly clipped to keepPoly.
    const shiftX = corner === "left" ? 18 : -18;
    const shiftY = -10;
    const shadowPoly = geom.curlPoly.map(([x, y]) => [x + shiftX, y + shiftY]);
    if (this._keepClipPoly) this._keepClipPoly.setAttribute("points", toSvgPoints(geom.keepPoly));
    this._curlShadow.setAttribute("points", toSvgPoints(shadowPoly));
    this._curlShadow.setAttribute("opacity", (geom.shadowStrength * 0.92).toFixed(3));
    if (this._curlShadowGrad) {
      this._curlShadowGrad.setAttribute("x1", geom.gradStart[0].toFixed(1));
      this._curlShadowGrad.setAttribute("y1", geom.gradStart[1].toFixed(1));
      this._curlShadowGrad.setAttribute("x2", (geom.gradEnd[0] + shiftX).toFixed(1));
      this._curlShadowGrad.setAttribute("y2", (geom.gradEnd[1] + shiftY).toFixed(1));
    }

    this._curlGrad.setAttribute("x1", geom.gradStart[0].toFixed(1));
    this._curlGrad.setAttribute("y1", geom.gradStart[1].toFixed(1));
    this._curlGrad.setAttribute("x2", geom.gradEnd[0].toFixed(1));
    this._curlGrad.setAttribute("y2", geom.gradEnd[1].toFixed(1));

    if (this._underShadow && this._underShadowGrad) {
      this._underShadow.setAttribute("points", toSvgPoints(geom.peelPoly));
      this._underShadow.setAttribute("opacity", (geom.shadowStrength * 0.9).toFixed(3));
      this._underShadowGrad.setAttribute("x1", geom.underGradStart[0].toFixed(1));
      this._underShadowGrad.setAttribute("y1", geom.underGradStart[1].toFixed(1));
      this._underShadowGrad.setAttribute("x2", geom.underGradEnd[0].toFixed(1));
      this._underShadowGrad.setAttribute("y2", geom.underGradEnd[1].toFixed(1));
    }
  }

  cancel(topLayerEl) {
    if (this._raf !== null) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    this._active = false;
    this._currentU = 0;
    if (this._topLayer) {
      this._topLayer.style.clipPath = "";
      this._topLayer = null;
    }
    if (topLayerEl) topLayerEl.style.clipPath = "";
    this._clearOverlay();
  }

  /** Smoothly animate a subtle dog-ear hover lift on either `"right"` or `"left"` real corner. */
  animatePeek(topLayerEl, targetU, corner, onDone) {
    if (this._active) return;
    if (this._raf !== null) cancelAnimationFrame(this._raf);
    if (!this._measureStage()) return;
    this._topLayer = topLayerEl;

    const startU = this._currentCorner === corner ? this._currentU : 0;
    this._currentCorner = corner;
    const startTime = performance.now();
    const duration = 210;

    const step = (now) => {
      const p = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      this._currentU = startU + (targetU - startU) * eased;
      this._apply(topLayerEl, this._currentU, corner);
      if (p < 1) {
        this._raf = requestAnimationFrame(step);
      } else {
        this._raf = null;
        if (onDone) onDone();
      }
    };
    this._raf = requestAnimationFrame(step);
  }

  /**
   * Peel the active outgoing page cleanly off from the real `"right"` (forward)
   * or `"left"` (backward) bottom corner, revealing the target folio underneath.
   */
  animatePeel(topLayerEl, corner, onComplete) {
    if (this._raf !== null) cancelAnimationFrame(this._raf);
    if (!this._measureStage()) {
      onComplete();
      return;
    }
    this._active = true;
    this._topLayer = topLayerEl;

    const fromU = this._currentCorner === corner ? Math.max(this._currentU, 0.025) : 0.025;
    this._currentCorner = corner;
    const duration = 660;
    const startTime = performance.now();

    const step = (now) => {
      const raw = Math.min(1, (now - startTime) / duration);
      const eased = easePaper(raw);
      this._currentU = fromU + (1 - fromU) * eased;
      this._apply(topLayerEl, this._currentU, corner);

      if (raw < 1) {
        this._raf = requestAnimationFrame(step);
      } else {
        this._raf = null;
        this._active = false;
        this._currentU = 0;
        this._topLayer = null;
        if (topLayerEl) topLayerEl.style.clipPath = "";
        this._clearOverlay();
        onComplete();
      }
    };

    this._apply(topLayerEl, fromU, corner);
    this._raf = requestAnimationFrame(step);
  }
}
