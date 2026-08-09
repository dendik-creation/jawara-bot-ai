"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import * as React from "react"
import { Menu, ShieldCheck } from "lucide-react"

import { NAVIGATION } from "@/components/layout/navigation"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [open, setOpen] = React.useState(false)

  return (
    <div className="flex min-h-svh flex-col lg:flex-row">
      <header className="flex items-center justify-between border-b border-border px-4 py-3 lg:hidden">
        <Brand />
        <Button variant="ghost" size="icon" aria-label="Buka navigasi" onClick={() => setOpen(!open)}>
          <Menu />
        </Button>
      </header>

      <nav
        className={cn(
          "border-b border-border px-4 py-4 lg:w-64 lg:shrink-0 lg:border-r lg:border-b-0 lg:px-4 lg:py-6",
          open ? "block" : "hidden lg:block",
        )}
      >
        <div className="mb-6 hidden lg:block">
          <Brand />
        </div>

        <div className="flex flex-col gap-5">
          {NAVIGATION.map((section) => (
            <div key={section.title ?? "root"} className="flex flex-col gap-1">
              {section.title ? (
                <p className="px-2 text-[0.7rem] font-medium tracking-wide text-muted-foreground uppercase">
                  {section.title}
                </p>
              ) : null}

              {section.items.map((item) =>
                item.href ? (
                  <Link
                    key={item.label}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-muted",
                      pathname === item.href && "bg-muted font-medium",
                    )}
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span
                    key={item.label}
                    aria-disabled
                    className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm text-muted-foreground/60"
                  >
                    {item.label}
                    <Badge variant="outline">belum tersedia</Badge>
                  </span>
                ),
              )}
            </div>
          ))}
        </div>
      </nav>

      <main className="min-w-0 flex-1 px-4 py-6 lg:px-8">{children}</main>
    </div>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <ShieldCheck className="size-5" />
      <div className="leading-tight">
        <p className="text-sm font-semibold">JAWARA</p>
        <p className="text-[0.7rem] text-muted-foreground">Control Panel</p>
      </div>
    </div>
  )
}
