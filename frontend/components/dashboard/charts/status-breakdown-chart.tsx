"use client"

import * as React from "react"
import { Bar, BarChart, Cell, XAxis, YAxis } from "recharts"

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"

/**
 * One status vocabulary recurs across every AI/ML domain on this page — DRAFT,
 * ACTIVE, ARCHIVED, FAILED, and so on mean roughly the same thing whether
 * they're a detection rule or a model version. Coloring every bar by that
 * shared meaning (not a fresh palette per card) is what makes the seven
 * widgets read as one status board instead of seven unrelated charts.
 */
const HEALTHY = new Set(["ACTIVE", "COMPLETED", "VALIDATED", "PRODUCTION", "CONFIRM"])
const IN_PROGRESS = new Set(["DRAFT", "VALIDATING", "QUEUED", "RUNNING", "EVALUATING", "CANDIDATE"])
const FAILED = new Set(["FAILED", "REJECTED", "CANCELLED", "FALSE_POSITIVE"])

function colorFor(status: string): string {
  if (HEALTHY.has(status)) return "var(--color-healthy)"
  if (IN_PROGRESS.has(status)) return "var(--color-in_progress)"
  if (FAILED.has(status)) return "var(--color-failed)"
  return "var(--color-neutral)"
}

const CONFIG: ChartConfig = {
  count: { label: "Jumlah" },
  healthy: { label: "Sehat", color: "var(--risk-low)" },
  in_progress: { label: "Berjalan", color: "var(--risk-medium)" },
  failed: { label: "Gagal", color: "var(--destructive)" },
  neutral: { label: "Nonaktif", color: "var(--muted-foreground)" },
}

export function StatusBreakdownChart({ data }: { data: Record<string, number> }) {
  const rows = React.useMemo(
    () =>
      Object.entries(data)
        .map(([status, count]) => ({ status, count, fill: colorFor(status) }))
        .sort((a, b) => b.count - a.count),
    [data],
  )

  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">Belum ada data.</p>
  }

  return (
    <ChartContainer config={CONFIG} className="aspect-auto w-full" style={{ height: rows.length * 28 + 8 }}>
      <BarChart data={rows} layout="vertical" margin={{ left: 0, right: 12, top: 0, bottom: 0 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="status"
          tickLine={false}
          axisLine={false}
          width={92}
          tick={{ fontSize: 11 }}
        />
        <ChartTooltip content={<ChartTooltipContent hideLabel />} />
        <Bar dataKey="count" radius={4} barSize={14}>
          {rows.map((row) => (
            <Cell key={row.status} fill={row.fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}
