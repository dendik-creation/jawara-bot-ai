import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        default: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-muted-foreground",
        // Risk colours follow the WhatsApp reply's own status indicators:
        // red / amber / green, with a distinct neutral for "not checked".
        high: "border-transparent bg-destructive/15 text-destructive",
        medium: "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400",
        low: "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
        unknown: "border-border text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant, className }))} {...props} />
}

/** Maps `risk_level_enum` onto a badge variant. UNKNOWN is never green. */
function riskVariant(risk: string | null | undefined): VariantProps<typeof badgeVariants>["variant"] {
  switch (risk) {
    case "HIGH":
      return "high"
    case "MEDIUM":
      return "medium"
    case "LOW":
      return "low"
    default:
      return "unknown"
  }
}

export { Badge, badgeVariants, riskVariant }
