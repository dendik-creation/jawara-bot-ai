import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

type ClassMetric = {
  precision?: unknown
  recall?: unknown
  "f1-score"?: unknown
  support?: unknown
}

type ClassificationReport = {
  accuracy?: unknown
  sample_count?: unknown
  macro_avg?: unknown
  weighted_avg?: unknown
  per_class?: unknown
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function pct(value: unknown): string {
  return isFiniteNumber(value) ? `${(value * 100).toFixed(1)}%` : "—"
}

function count(value: unknown): string {
  return isFiniteNumber(value) ? value.toLocaleString("id-ID") : "—"
}

/** F1 quality reuses the app's risk badge vocabulary: low f1 reads as high risk. */
function f1Variant(value: unknown): "low" | "medium" | "high" | "unknown" {
  if (!isFiniteNumber(value)) return "unknown"
  if (value >= 0.85) return "low"
  if (value >= 0.7) return "medium"
  return "high"
}

function parseReport(metrics: Record<string, unknown>): ClassificationReport | null {
  const perClass = metrics.per_class
  const macroAvg = metrics.macro_avg
  const weightedAvg = metrics.weighted_avg
  const hasReportShape = isPlainObject(perClass) || isPlainObject(macroAvg) || isPlainObject(weightedAvg)
  if (!hasReportShape) return null
  return metrics as ClassificationReport
}

function MetricRow({ label, metric, emphasis }: { label: string; metric: ClassMetric; emphasis?: boolean }) {
  const f1 = metric["f1-score"]
  return (
    <TableRow>
      <TableCell className={cn("text-xs", emphasis ? "font-semibold text-foreground" : "text-muted-foreground")}>
        {label}
      </TableCell>
      <TableCell className="text-right font-mono text-xs tabular-nums">{pct(metric.precision)}</TableCell>
      <TableCell className="text-right font-mono text-xs tabular-nums">{pct(metric.recall)}</TableCell>
      <TableCell className="text-right">
        <Badge variant={f1Variant(f1)} className="font-mono tabular-nums">
          {pct(f1)}
        </Badge>
      </TableCell>
      <TableCell className="text-right font-mono text-xs tabular-nums text-muted-foreground">
        {count(metric.support)}
      </TableCell>
    </TableRow>
  )
}

export function MetricsSummary({ metrics }: { metrics: Record<string, unknown> | null }) {
  if (!metrics) return null

  const report = parseReport(metrics)
  if (!report) {
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-xs text-muted-foreground">Metrics</span>
        <pre className="max-h-48 overflow-auto rounded-lg border border-border bg-muted/40 p-2.5 font-mono text-xs whitespace-pre-wrap break-words text-foreground">
          {JSON.stringify(metrics, null, 2)}
        </pre>
      </div>
    )
  }

  const perClass = isPlainObject(report.per_class) ? report.per_class : {}
  const classLabels = Object.keys(perClass).sort()

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Metrics</span>
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono text-lg font-semibold tabular-nums">{pct(report.accuracy)}</span>
          <span className="text-xs text-muted-foreground">akurasi</span>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-xs">Kelas</TableHead>
              <TableHead className="text-right text-xs">Presisi</TableHead>
              <TableHead className="text-right text-xs">Recall</TableHead>
              <TableHead className="text-right text-xs">F1</TableHead>
              <TableHead className="text-right text-xs">Support</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {classLabels.map((label) => (
              <MetricRow key={label} label={label} metric={perClass[label] as ClassMetric} />
            ))}
            {isPlainObject(report.macro_avg) ? (
              <MetricRow label="Macro avg" metric={report.macro_avg as ClassMetric} emphasis />
            ) : null}
            {isPlainObject(report.weighted_avg) ? (
              <MetricRow label="Weighted avg" metric={report.weighted_avg as ClassMetric} emphasis />
            ) : null}
          </TableBody>
        </Table>
      </div>

      {isFiniteNumber(report.sample_count) ? (
        <span className="text-right text-xs text-muted-foreground">
          {count(report.sample_count)} sampel diuji
        </span>
      ) : null}
    </div>
  )
}
