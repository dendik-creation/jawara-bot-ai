"use client"

import * as React from "react"
import { Cell, Pie, PieChart } from "recharts"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"

const SEVERITY_CONFIG: ChartConfig = {
  HIGH: { label: "Tinggi", color: "var(--destructive)" },
  MEDIUM: { label: "Sedang", color: "var(--risk-medium)" },
  LOW: { label: "Rendah", color: "var(--risk-low)" },
  UNKNOWN: { label: "Belum diketahui", color: "var(--muted-foreground)" },
}

/** Real data — from the same `dashboard/summary` response the stat tiles already use. */
export function SeverityDonutChart({
  breakdown,
}: {
  breakdown: Record<string, number> | null | undefined
}) {
  const data = React.useMemo(() => {
    if (!breakdown) return []
    return Object.entries(breakdown)
      .filter(([, count]) => count > 0)
      .map(([key, count]) => ({
        name: key,
        value: count,
        fill: `var(--color-${key in SEVERITY_CONFIG ? key : "UNKNOWN"})`,
      }))
  }, [breakdown])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribusi Tingkat Risiko</CardTitle>
        <CardDescription>Pesan yang dianalisis pada window aktif, per risk_score.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length ? (
          <ChartContainer config={SEVERITY_CONFIG} className="mx-auto aspect-square max-h-64">
            <PieChart>
              <ChartTooltip content={<ChartTooltipContent nameKey="name" hideLabel />} />
              <Pie data={data} dataKey="value" nameKey="name" innerRadius={55} strokeWidth={2}>
                {data.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Pie>
            </PieChart>
          </ChartContainer>
        ) : (
          <p className="py-10 text-center text-sm text-muted-foreground">Belum ada data untuk window ini.</p>
        )}
      </CardContent>
    </Card>
  )
}
