/** Inline SVG sparkline — area + line, last point marked. No chart library. */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  color = "var(--accent)",
  label,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  label?: string;
}) {
  const v = values.length > 1 ? values : [0, ...(values.length ? values : [0])];
  const max = Math.max(...v, 1);
  const min = Math.min(...v, 0);
  const span = max - min || 1;
  const step = width / (v.length - 1);
  const pts = v.map((y, i) => [i * step, height - 3 - ((y - min) / span) * (height - 6)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width},${height} L0,${height} Z`;
  const [lx, ly] = pts[pts.length - 1];
  const id = `sg-${Math.round(v.reduce((a, b) => a * 31 + b, 7)) % 99991}-${width}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label ?? "Trend"} className="overflow-visible">
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.16" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="2.25" fill={color} />
    </svg>
  );
}

/** Tiny bar strip for categorical counts. */
export function MiniBars({
  values,
  width = 96,
  height = 28,
  color = "var(--accent)",
  label,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  label?: string;
}) {
  const max = Math.max(...values, 1);
  const gap = 2;
  const bw = values.length ? (width - gap * (values.length - 1)) / values.length : 0;
  return (
    <svg width={width} height={height} role="img" aria-label={label ?? "Distribution"}>
      {values.map((v, i) => {
        const h = v === 0 ? 2 : Math.max(3, (v / max) * (height - 2));
        return (
          <rect
            key={i}
            x={i * (bw + gap)}
            y={height - h}
            width={bw}
            height={h}
            rx="1.5"
            fill={color}
            opacity={v === 0 ? 0.18 : 0.35 + 0.65 * (v / max)}
          />
        );
      })}
    </svg>
  );
}
