/**
 * Control Panel navigation, mirroring 08_Dashboard/01_Control_Panel_Overview.md §2.
 *
 * There is deliberately no "Analytics" or "Infrastructure Analytics" entry —
 * both are Deferred (05_Product_Scope_and_Roadmap §6).
 *
 * `href: null` marks a screen that is specified but not built. It renders as a
 * disabled row with a "Belum tersedia" badge instead of a link to an empty page,
 * so the navigation shows the whole product without pretending it exists.
 *
 * "Live Activity" is not a nav entry: it's the activity feed embedded in
 * Command Center, not a distinct route — linking it here would just be a
 * second name for `/`.
 *
 * "Risk Profiles" and "Blocklist" are not separate nav entries either: both
 * are the same `user_subscriptions` row set as "Users", viewed through a
 * preset filter (risk tier, or `blocked=true`) rather than a different
 * dataset — see `/users`. Two more pages that show the same rows would be
 * the same redundant-screen problem "Live Activity" was.
 */

import {
  Activity,
  Bell,
  BookOpen,
  Boxes,
  Cpu,
  Database,
  FileCheck2,
  Gauge,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  ScrollText,
  ShieldAlert,
  Siren,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react"

export type NavItem = {
  label: string
  href: string | null
  icon: LucideIcon
}

export type NavSection = {
  title: string | null
  items: NavItem[]
}

export const NAVIGATION: NavSection[] = [
  {
    title: null,
    items: [{ label: "Command Center", href: "/", icon: LayoutDashboard }],
  },
  {
    title: "Monitoring",
    items: [
      { label: "Threats", href: "/threats", icon: ShieldAlert },
      { label: "Messages", href: "/messages", icon: MessageSquare },
      { label: "Incidents", href: "/incidents", icon: Siren },
    ],
  },
  {
    title: "Identity",
    items: [{ label: "Users", href: "/users", icon: Users }],
  },
  {
    title: "Security",
    items: [
      { label: "Policies", href: "/policies", icon: FileCheck2 },
      { label: "Detection Rules", href: "/detection-rules", icon: ListChecks },
      { label: "Alerts", href: "/alerts", icon: Bell },
      { label: "Audit Logs", href: "/audit-log", icon: ScrollText },
    ],
  },
  {
    title: "AI / ML",
    items: [
      { label: "Overview", href: "/ai-ml-overview", icon: Sparkles },
      { label: "Knowledge Base", href: "/knowledge-base", icon: BookOpen },
      { label: "Datasets", href: "/datasets", icon: Database },
      { label: "Training Jobs", href: "/training-jobs", icon: Cpu },
      { label: "Models", href: "/models", icon: Boxes },
      { label: "Evaluation", href: "/evaluation", icon: Gauge },
    ],
  },
  {
    title: "System",
    items: [{ label: "Service Health", href: "/system/service-health", icon: Activity }],
  },
]
