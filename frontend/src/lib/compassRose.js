/**
 * Polar geometry for the Nightingale Coxcomb / Archival Compass Rose chart.
 *
 * Computes equal-angle radial wedges around a central hub with area-proportional
 * radius `r = innerR + sqrt(value / max) * (outerR - innerR)` so each wiki's
 * visual area reflects its edit share accurately while staying legible at every scale.
 */

export function polarToCartesian(cx, cy, radius, angleRad) {
  return [cx + radius * Math.cos(angleRad), cy + radius * Math.sin(angleRad)];
}

export function wedgePath(cx, cy, innerR, outerR, startAngle, endAngle) {
  const [x1, y1] = polarToCartesian(cx, cy, innerR, startAngle);
  const [x2, y2] = polarToCartesian(cx, cy, outerR, startAngle);
  const [x3, y3] = polarToCartesian(cx, cy, outerR, endAngle);
  const [x4, y4] = polarToCartesian(cx, cy, innerR, endAngle);
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;

  return [
    `M ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    `L ${x2.toFixed(2)} ${y2.toFixed(2)}`,
    `A ${outerR.toFixed(2)} ${outerR.toFixed(2)} 0 ${largeArc} 1 ${x3.toFixed(2)} ${y3.toFixed(2)}`,
    `L ${x4.toFixed(2)} ${y4.toFixed(2)}`,
    `A ${innerR.toFixed(2)} ${innerR.toFixed(2)} 0 ${largeArc} 0 ${x1.toFixed(2)} ${y1.toFixed(2)}`,
    "Z",
  ].join(" ");
}

/**
 * Compute wedges, label anchor points, and leader lines for up to 10 wikis.
 */
export function computeCompassWedges(
  items,
  { cx = 300, cy = 175, innerR = 30, maxR = 128, labelR = 148 } = {},
) {
  const positive = items
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);

  const total = positive.reduce((sum, item) => sum + item.value, 0);
  if (positive.length === 0 || total <= 0) {
    return { wedges: [], total: 0 };
  }

  const maxVal = positive[0].value;
  const n = positive.length;
  const step = (Math.PI * 2) / n;
  const gap = Math.min(0.045, step * 0.08);
  // Start at 12 o'clock (-PI/2) so the #1 wiki crowns the top of the rose.
  const baseAngle = -Math.PI / 2 - step / 2;

  const wedges = positive.map((item, idx) => {
    const startAngle = baseAngle + idx * step + gap / 2;
    const endAngle = baseAngle + (idx + 1) * step - gap / 2;
    const midAngle = (startAngle + endAngle) / 2;
    const norm = Math.sqrt(item.value / maxVal);
    const outerR = innerR + Math.max(0.16, norm) * (maxR - innerR);

    const [edgeX, edgeY] = polarToCartesian(cx, cy, Math.max(outerR + 4, innerR + 24), midAngle);
    const [labelX, labelY] = polarToCartesian(cx, cy, labelR, midAngle);
    const cos = Math.cos(midAngle);
    const anchor = Math.abs(cos) < 0.22 ? "middle" : cos > 0 ? "start" : "end";

    return {
      key: item.key,
      value: item.value,
      pct: ((item.value / total) * 100).toFixed(1),
      rank: idx,
      outerR,
      midAngle,
      path: wedgePath(cx, cy, innerR, outerR, startAngle, endAngle),
      edgeX,
      edgeY,
      labelX,
      labelY,
      anchor,
    };
  });

  return { wedges, total };
}
