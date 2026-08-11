"use client"

import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"

const TREND_CONFIG: ChartConfig = {
  messages: { label: "Pesan diproses", color: "var(--chart-1)" },
  threats: { label: "Ancaman terdeteksi", color: "var(--destructive)" },
}

/**
 * Illustrative shape only — the gateway has no hourly time-series endpoint yet
 * (no `date_trunc`/bucketed query exists in `dashboard.py`). These numbers are
 * a fixed placeholder pattern, not sampled from any real window, and must never
 * be read as production volume. Swap for a real endpoint once one exists.
 */
const DEMO_TREND_DATA = [
  { hour: "00:00", messages: 42, threats: 3 },
  { hour: "02:00", messages: 28, threats: 1 },
  { hour: "04:00", messages: 19, threats: 1 },
  { hour: "06:00", messages: 35, threats: 2 },
  { hour: "08:00", messages: 88, threats: 6 },
  { hour: "10:00", messages: 132, threats: 9 },
  { hour: "12:00", messages: 156, threats: 11 },
  { hour: "14:00", messages: 149, threats: 8 },
  { hour: "16:00", messages: 121, threats: 7 },
  { hour: "18:00", messages: 97, threats: 5 },
  { hour: "20:00", messages: 74, threats: 4 },
  { hour: "22:00", messages: 51, threats: 3 },
]

export function DemoTrendChart() {
  return (
    <Card className="border-dashed">
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Tren per Jam</CardTitle>
          <Badge variant="outline">Demo data</Badge>
        </div>
        <CardDescription>
          Backend belum punya endpoint time-series per jam — pola di bawah ini ilustratif, bukan data
          produksi.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={TREND_CONFIG} className="max-h-64 w-full">
          <AreaChart data={DEMO_TREND_DATA} margin={{ left: 0, right: 12 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="hour" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
            <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
            <Area
              dataKey="messages"
              type="monotone"
              fill="var(--color-messages)"
              fillOpacity={0.2}
              stroke="var(--color-messages)"
              strokeWidth={2}
            />
            <Area
              dataKey="threats"
              type="monotone"
              fill="var(--color-threats)"
              fillOpacity={0.2}
              stroke="var(--color-threats)"
              strokeWidth={2}
            />
          </AreaChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}
