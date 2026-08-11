"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import * as React from "react"
import { ChevronsUpDown, KeyRound, LogOut, Moon, ShieldCheck, Sun } from "lucide-react"
import { useTheme } from "next-themes"

import { useAuth } from "@/components/auth/auth-provider"
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"
import { PageContainer } from "@/components/layout/page-container"
import { NAVIGATION } from "@/components/layout/navigation"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from "@/components/ui/sidebar"

/**
 * Control Panel shell: collapsible sidebar, current-screen highlight, and the
 * signed-in operator with a way out.
 *
 * The navigation lists the whole product, including screens that do not exist
 * yet — those render as disabled rows with a "belum tersedia" badge rather than
 * links to empty pages (see `navigation.ts`).
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" render={<Link href="/" />} tooltip="JAWARA Control Panel">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                  <ShieldCheck className="size-4" />
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-semibold">JAWARA</span>
                  <span className="truncate text-xs text-muted-foreground">Control Panel</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent>
          {NAVIGATION.map((section) => (
            <SidebarGroup key={section.title ?? "root"}>
              {section.title ? <SidebarGroupLabel>{section.title}</SidebarGroupLabel> : null}
              <SidebarGroupContent>
                <SidebarMenu>
                  {section.items.map((item) => (
                    <SidebarMenuItem key={`${section.title ?? "root"}-${item.label}`}>
                      {item.href ? (
                        <SidebarMenuButton
                          render={<Link href={item.href} />}
                          isActive={pathname === item.href}
                          tooltip={item.label}
                        >
                          <span>{item.label}</span>
                        </SidebarMenuButton>
                      ) : (
                        <SidebarMenuButton
                          aria-disabled
                          disabled
                          tooltip={`${item.label} — belum tersedia`}
                          className="text-muted-foreground/60"
                        >
                          <span>{item.label}</span>
                          <Badge variant="outline" className="ml-auto group-data-[collapsible=icon]:hidden">
                            belum
                          </Badge>
                        </SidebarMenuButton>
                      )}
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>

        <SidebarFooter>
          <OperatorMenu />
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>

      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <SidebarTrigger />
        </header>
        <div className="min-w-0 flex-1">
          <PageContainer>{children}</PageContainer>
        </div>
      </SidebarInset>
    </SidebarProvider>
  )
}

function OperatorMenu() {
  const { operator, signOut } = useAuth()
  const { resolvedTheme, setTheme } = useTheme()
  const [signingOut, setSigningOut] = React.useState(false)
  const [changingPassword, setChangingPassword] = React.useState(false)

  if (!operator) return null

  // Safe to read directly: this menu's content only mounts once the dropdown
  // opens, well after hydration, so there is no SSR/client theme mismatch to
  // guard against here.
  const isDark = resolvedTheme === "dark"

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton size="lg">
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-muted text-xs font-medium">
                  {initials(operator.full_name)}
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-medium">{operator.full_name}</span>
                  <span className="truncate text-xs text-muted-foreground">{operator.email}</span>
                </div>
                <ChevronsUpDown className="ml-auto size-4" />
              </SidebarMenuButton>
            }
          />
          <DropdownMenuContent side="top" align="start" className="w-56">
            <DropdownMenuGroup>
              <DropdownMenuLabel className="font-normal">
                <span className="block text-sm font-medium">{operator.full_name}</span>
                <span className="block text-xs text-muted-foreground">{operator.email}</span>
              </DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => setChangingPassword(true)}>
              <KeyRound className="size-4" />
              Ganti kata sandi
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme(isDark ? "light" : "dark")}>
              {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
              {isDark ? "Mode terang" : "Mode gelap"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              disabled={signingOut}
              onClick={() => {
                setSigningOut(true)
                void signOut()
              }}
            >
              <LogOut className="size-4" />
              {signingOut ? "Keluar…" : "Keluar"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
      <ChangePasswordDialog open={changingPassword} onOpenChange={setChangingPassword} />
    </SidebarMenu>
  )
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?"
}
