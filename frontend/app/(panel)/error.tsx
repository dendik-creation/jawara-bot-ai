"use client"

import { useEffect } from "react"
import { ShieldAlert } from "lucide-react"

import { Button } from "@/components/ui/button"

/** Route-level fallback for unhandled render errors inside the Control Panel shell. */
export default function PanelError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
      <ShieldAlert className="size-10 text-muted-foreground" />
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground">Terjadi kesalahan</h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          Halaman ini gagal dimuat. Coba lagi, atau kembali ke Command Center kalau masalah berlanjut.
        </p>
      </div>
      <Button variant="outline" onClick={reset}>
        Coba lagi
      </Button>
    </div>
  )
}
