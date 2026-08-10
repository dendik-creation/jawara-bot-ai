/**
 * Control Panel navigation, mirroring 08_Dashboard/01_Control_Panel_Overview.md §2.
 *
 * There is deliberately no "Analytics" or "Infrastructure Analytics" entry —
 * both are Deferred (05_Product_Scope_and_Roadmap §6).
 *
 * `href: null` marks a screen that is specified but not built. It renders as a
 * disabled row with a "Belum tersedia" badge instead of a link to an empty page,
 * so the navigation shows the whole product without pretending it exists.
 */

export type NavItem = {
  label: string
  href: string | null
}

export type NavSection = {
  title: string | null
  items: NavItem[]
}

export const NAVIGATION: NavSection[] = [
  {
    title: null,
    items: [{ label: "Command Center", href: "/" }],
  },
  {
    title: "Monitoring",
    items: [
      { label: "Live Activity", href: "/" },
      { label: "Threats", href: null },
      { label: "Messages", href: "/messages" },
      { label: "Incidents", href: null },
    ],
  },
  {
    title: "Users",
    items: [
      { label: "Users", href: null },
      { label: "Risk Profiles", href: null },
      { label: "Blocklist", href: null },
    ],
  },
  {
    title: "Security",
    items: [
      { label: "Policies", href: null },
      { label: "Detection Rules", href: null },
      { label: "Alerts", href: null },
      { label: "Audit Logs", href: null },
    ],
  },
  {
    title: "AI / ML",
    items: [
      { label: "Overview", href: null },
      { label: "Knowledge Base", href: null },
      { label: "Datasets", href: null },
      { label: "Training Jobs", href: null },
      { label: "Models", href: null },
      { label: "Evaluation", href: null },
    ],
  },
  {
    title: "System",
    items: [{ label: "Service Health", href: "/system/service-health" }],
  },
]
