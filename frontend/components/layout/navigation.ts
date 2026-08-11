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
      { label: "Threats", href: "/threats" },
      { label: "Messages", href: "/messages" },
      { label: "Incidents", href: "/incidents" },
    ],
  },
  {
    title: "Identity",
    items: [{ label: "Users", href: "/users" }],
  },
  {
    title: "Security",
    items: [
      { label: "Policies", href: "/policies" },
      { label: "Detection Rules", href: "/detection-rules" },
      { label: "Alerts", href: "/alerts" },
      { label: "Audit Logs", href: "/audit-log" },
    ],
  },
  {
    title: "AI / ML",
    items: [
      { label: "Overview", href: "/ai-ml-overview" },
      { label: "Knowledge Base", href: "/knowledge-base" },
      { label: "Datasets", href: "/datasets" },
      { label: "Training Jobs", href: "/training-jobs" },
      { label: "Models", href: "/models" },
      { label: "Evaluation", href: "/evaluation" },
    ],
  },
  {
    title: "System",
    items: [{ label: "Service Health", href: "/system/service-health" }],
  },
]
