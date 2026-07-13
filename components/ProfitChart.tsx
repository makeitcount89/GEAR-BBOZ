"use client";

import { useMemo, useRef, useState } from "react";
import type { ChartPoint } from "@/lib/types";
import { formatCurrency, formatDate } from "@/lib/utils";

const WIDTH = 720;
const HEIGHT = 280;
const PAD = { top: 24, right: 20, bottom: 32, left: 68 };

export default function ProfitChart({ data }: { data: ChartPoint[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;

  const points = useMemo(() => data.filter((d) => d.date !== null), [data]);

  const { minY, maxY, xFor, yFor } = useMemo(() => {
    const values = points.map((p) => p.cumulativeProfit);
    const rawMin = Math.min(0, ...values);
    const rawMax = Math.max(0, ...values);
    const span = rawMax - rawMin || 1;
    const pad = span * 0.12;
    const minY = rawMin - pad;
    const maxY = rawMax + pad;
    const xFor = (i: number) =>
      points.length <= 1 ? PAD.left : PAD.left + (i / (points.length - 1)) * innerW;
    const yFor = (v: number) => PAD.top + innerH - ((v - minY) / (maxY - minY)) * innerH;
    return { minY, maxY, xFor, yFor };
  }, [points, innerH, innerW]);

  if (points.length === 0) {
    return (
      <div className="flex h-[280px] flex-col items-center justify-center gap-2 rounded-lg border border-base-700 bg-base-850 text-center">
        <p className="text-sm text-[var(--text-secondary)]">
          No ledger history yet — the equity curve appears after the first scheduled engine run.
        </p>
      </div>
    );
  }

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i).toFixed(2)} ${yFor(p.cumulativeProfit).toFixed(2)}`)
    .join(" ");

  const zeroY = yFor(0);
  const areaPath =
    `M ${xFor(0).toFixed(2)} ${zeroY.toFixed(2)} ` +
    points.map((p, i) => `L ${xFor(i).toFixed(2)} ${yFor(p.cumulativeProfit).toFixed(2)}`).join(" ") +
    ` L ${xFor(points.length - 1).toFixed(2)} ${zeroY.toFixed(2)} Z`;

  const gridSteps = 4;
  const gridValues = Array.from({ length: gridSteps + 1 }, (_, i) => minY + ((maxY - minY) * i) / gridSteps);

  const last = points[points.length - 1];
  const lastPositive = last.cumulativeProfit >= 0;

  function handleMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const fracX = (e.clientX - rect.left) / rect.width;
    const dataX = fracX * WIDTH;
    let closest = 0;
    let closestDist = Infinity;
    points.forEach((_, i) => {
      const dist = Math.abs(xFor(i) - dataX);
      if (dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    });
    setHoverIdx(closest);
  }

  const hovered = hoverIdx !== null ? points[hoverIdx] : null;

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full touch-none"
        onMouseMove={handleMove}
        onMouseLeave={() => setHoverIdx(null)}
        role="img"
        aria-label="Cumulative profit over the 30-week backtest window"
      >
        {gridValues.map((v, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yFor(v)}
              y2={yFor(v)}
              stroke="var(--gridline)"
              strokeWidth={1}
            />
            <text x={PAD.left - 10} y={yFor(v)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill="var(--text-muted)">
              {formatCurrency(v)}
            </text>
          </g>
        ))}

        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={zeroY}
          y2={zeroY}
          stroke="var(--baseline)"
          strokeWidth={1}
        />

        <path d={areaPath} fill="var(--series-profit)" opacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke="var(--series-profit)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

        {[0, points.length - 1].map((i) => (
          <text key={i} x={xFor(i)} y={HEIGHT - PAD.bottom + 18} textAnchor={i === 0 ? "start" : "end"} fontSize={11} fill="var(--text-muted)">
            {formatDate(points[i].date)}
          </text>
        ))}

        <circle
          cx={xFor(points.length - 1)}
          cy={yFor(last.cumulativeProfit)}
          r={4}
          fill={lastPositive ? "var(--status-good)" : "var(--status-critical)"}
          stroke="var(--surface-1)"
          strokeWidth={2}
        />
        <text
          x={xFor(points.length - 1) - 6}
          y={yFor(last.cumulativeProfit) - 12}
          textAnchor="end"
          fontSize={12}
          fontWeight={600}
          fill={lastPositive ? "var(--status-good)" : "var(--status-critical)"}
        >
          {formatCurrency(last.cumulativeProfit)}
        </text>

        {hovered && (
          <g>
            <line
              x1={xFor(hoverIdx!)}
              x2={xFor(hoverIdx!)}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              stroke="var(--baseline)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <circle
              cx={xFor(hoverIdx!)}
              cy={yFor(hovered.cumulativeProfit)}
              r={4}
              fill="var(--series-profit)"
              stroke="var(--surface-1)"
              strokeWidth={2}
            />
          </g>
        )}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute top-2 rounded-md border border-base-600 bg-base-900/95 px-3 py-2 text-xs shadow-lg"
          style={{
            left: `${Math.min(85, Math.max(2, (xFor(hoverIdx!) / WIDTH) * 100))}%`,
          }}
        >
          <div className="text-[var(--text-secondary)]">{formatDate(hovered.date)}</div>
          <div className="mt-1 font-semibold tabular text-[var(--text-primary)]">
            {formatCurrency(hovered.portfolioValue)}
          </div>
          <div
            className={`tabular ${hovered.cumulativeProfit >= 0 ? "text-[var(--status-good)]" : "text-[var(--status-critical)]"}`}
          >
            {hovered.cumulativeProfit >= 0 ? "+" : ""}
            {formatCurrency(hovered.cumulativeProfit)} P/L
          </div>
        </div>
      )}
    </div>
  );
}
