import { cn } from "@/lib/utils"

/** Keeps page content readable on ultrawide monitors without capping small screens. */
export function PageContainer({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1600px] px-4 py-6 lg:px-8", className)}>{children}</div>
  )
}
