"use client"

import * as React from "react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"

const INTENT_CONFIG: ChartConfig = {
  count: { label: "Jumlah pesan", color: "var(--chart-1)" },
}

/** Real data — from the same `dashboard/summary` response the stat tiles already use. */
export function IntentBarChart({
  breakdown,
}: {
  breakdown: Record<string, number> | null | undefined
}) {
  const data = React.useMemo(() => {
    if (!breakdown) return []
    return Object.entries(breakdown)
      .filter(([, count]) => count > 0)
      .map(([intent, count]) => ({ intent, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8)
  }, [breakdown])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Klasifikasi Intent</CardTitle>
        <CardDescription>Pesan yang dianalisis pada window aktif, per detected_intent.</CardDescription>
      </CardHeader>
      <CardContent>
        {data.length ? (
          <ChartContainer config={INTENT_CONFIG} className="max-h-64 w-full">
            <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
              <CartesianGrid horizontal={false} />
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="intent"
                tickLine={false}
                axisLine={false}
                width={100}
                tick={{ fontSize: 11 }}
              />
              <ChartTooltip content={<ChartTooltipContent hideLabel />} />
              <Bar dataKey="count" fill="var(--color-count)" radius={4} />
            </BarChart>
          </ChartContainer>
        ) : (
          <p className="py-10 text-center text-sm text-muted-foreground">Belum ada data untuk window ini.</p>
        )}
      </CardContent>
    </Card>
  )
}
