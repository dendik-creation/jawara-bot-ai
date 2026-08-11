"use client"

import { ChevronLeftIcon } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect } from "react"

import { Button } from "@/components/ui/button"

export type PageTitleProps = {
  title: string
  description?: string
  back?: boolean
}

/**
 * The page itself declares `back` explicitly — it is never inferred from
 * pathname depth, since that broke down once a route (e.g. `/messages`)
 * needed no back button despite being one segment deep.
 */
export function PageTitle({ title, description, back }: PageTitleProps) {
  const router = useRouter()

  useEffect(() => {
    document.title = `${title} · JAWARA Control Panel`
  }, [title])

  return (
    <div className="mb-6 flex items-start gap-4">
      {back ? (
        <Button
          onClick={() => router.back()}
          className="size-9 shrink-0"
          size="icon"
          variant="outline"
          aria-label="Kembali"
        >
          <ChevronLeftIcon />
        </Button>
      ) : null}

      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="truncate text-xl font-semibold text-foreground md:text-2xl">{title}</h1>
        {description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground md:line-clamp-1">{description}</p>
        ) : null}
      </div>
    </div>
  )
}
