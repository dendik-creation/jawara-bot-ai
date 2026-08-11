"use client"

import Image from "next/image"
import Link from "next/link"
import { usePathname } from "next/navigation"
import * as React from "react"
import { ChevronsUpDown, KeyRound, LogOut, Moon, Sun, UserPen } from "lucide-react"
import { useTheme } from "next-themes"

import { useAuth } from "@/components/auth/auth-provider"
import { ChangePasswordDialog } from "@/components/auth/change-password-dialog"
import { EditProfileDialog } from "@/components/auth/edit-profile-dialog"
import { PageContainer } from "@/components/layout/page-container"
import { NAVIGATION, type NavItem } from "@/components/layout/navigation"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
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

  const activeSectionTitle = React.useMemo(() => {
    const section = NAVIGATION.find(
      (s) => s.title && s.items.some((item) => item.href === pathname)
    )
    return section?.title ?? null
  }, [pathname])

  // Sections the operator opened/closed by hand. The section containing the
  // active route is folded in at render time below, so it always stays open —
  // no effect needed to "catch up" state when the route changes.
  const [toggledSections, setToggledSections] = React.useState<string[]>([])

  const openSections = React.useMemo(() => {
    const set = new Set(toggledSections)
    if (activeSectionTitle) set.add(activeSectionTitle)
    return [...set]
  }, [toggledSections, activeSectionTitle])

  return (
    <SidebarProvider>
      <Sidebar collapsible="offcanvas">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" render={<Link href="/" />} tooltip="JAWARA Control Panel">
                <div className="flex aspect-square size-8 items-center justify-center overflow-hidden rounded-lg bg-background p-1 ring-1 ring-sidebar-border">
                  <Image src="/icon.png" alt="" width={24} height={24} className="size-full object-contain" priority />
                </div>
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate text-sm font-semibold">JAWARA</span>
                  <span className="truncate text-xs text-muted-foreground">Control Panel</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>

        <SidebarContent className="gap-2">
          {NAVIGATION.filter((section) => !section.title).map((section) => (
            <SidebarGroup key="root">
              <SidebarGroupContent>
                <SidebarMenu className="gap-1">
                  {section.items.map((item) => (
                    <NavMenuItem key={item.label} item={item} pathname={pathname} />
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}

          <SidebarGroup>
            <SidebarGroupContent>
              <Accordion
                multiple
                value={openSections}
                onValueChange={(value) => setToggledSections(value as string[])}
                className="gap-1"
              >
                {NAVIGATION.filter((section) => section.title).map((section) => (
                  <AccordionItem key={section.title} value={section.title as string} className="border-none">
                    <AccordionTrigger className="rounded-md px-2.5 py-2.5 text-meta font-medium text-sidebar-foreground/70 no-underline! hover:bg-sidebar-accent hover:text-sidebar-accent-foreground hover:no-underline! focus-visible:bg-sidebar-accent">
                      {section.title}
                    </AccordionTrigger>
                    <AccordionContent className="px-0 pt-1 pb-1.5">
                      <SidebarMenu className="gap-1">
                        {section.items.map((item) => (
                          <NavMenuItem key={item.label} item={item} pathname={pathname} />
                        ))}
                      </SidebarMenu>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            </SidebarGroupContent>
          </SidebarGroup>
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

function NavMenuItem({ item, pathname }: { item: NavItem; pathname: string }) {
  const Icon = item.icon

  return (
    <SidebarMenuItem>
      {item.href ? (
        <SidebarMenuButton
          className="h-10 gap-3 px-3 text-nav no-underline!"
          render={<Link href={item.href} />}
          isActive={pathname === item.href}
          tooltip={item.label}
        >
          <Icon className="size-[18px]" />
          <span>{item.label}</span>
        </SidebarMenuButton>
      ) : (
        <SidebarMenuButton
          aria-disabled
          disabled
          tooltip={`${item.label} — belum tersedia`}
          className="h-10 gap-3 px-3 text-nav text-muted-foreground/60"
        >
          <Icon className="size-[18px]" />
          <span>{item.label}</span>
          <Badge variant="outline" className="ml-auto">
            belum
          </Badge>
        </SidebarMenuButton>
      )}
    </SidebarMenuItem>
  )
}

function OperatorMenu() {
  const { operator, signOut } = useAuth()
  const { resolvedTheme, setTheme } = useTheme()
  const [signingOut, setSigningOut] = React.useState(false)
  const [changingPassword, setChangingPassword] = React.useState(false)
  const [editingProfile, setEditingProfile] = React.useState(false)

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
            <DropdownMenuItem onClick={() => setEditingProfile(true)}>
              <UserPen className="size-4" />
              Edit profil
            </DropdownMenuItem>
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
      <EditProfileDialog open={editingProfile} onOpenChange={setEditingProfile} />
      <ChangePasswordDialog open={changingPassword} onOpenChange={setChangingPassword} />
    </SidebarMenu>
  )
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?"
}
