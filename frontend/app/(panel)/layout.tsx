import { RequireAuth } from "@/components/auth/require-auth"
import { AppShell } from "@/components/layout/app-shell"

/** Everything in this route group is Control Panel: signed in, inside the shell. */
export default function PanelLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  )
}
