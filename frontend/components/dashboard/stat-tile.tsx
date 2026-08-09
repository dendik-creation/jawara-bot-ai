import { cn } from "@/lib/utils"

/**
 * One Command Center metric.
 *
 * `value === null` renders "belum tersedia", never `0`. A zero and a missing
 * data source look identical on a dashboard, and an operator reading "0 threats"
 * off a broken query is worse off than one who reads "not available".
 */
export function StatTile({
  label,
  value,
  hint,
  emphasis,
}: {
  label: string
  value: number | string | null | undefined
  hint?: string
  emphasis?: boolean
}) {
  const missing = value === null || value === undefined

  return (
    <div className="flex flex-col gap-1 rounded-xl border border-border bg-card p-4">
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
      <p
        className={cn(
          "text-2xl font-semibold tabular-nums",
          missing && "text-base font-normal text-muted-foreground",
          emphasis && !missing && "text-destructive",
        )}
      >
        {missing ? "belum tersedia" : typeof value === "number" ? value.toLocaleString("id-ID") : value}
      </p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}
