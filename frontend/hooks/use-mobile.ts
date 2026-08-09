import * as React from "react"

const MOBILE_BREAKPOINT = 768
const QUERY = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

/**
 * Viewport width as an external store.
 *
 * The shadcn original synchronised the media query into state inside an effect,
 * which this project's lint rules reject (`react-hooks/set-state-in-effect`) —
 * and rightly: it renders once at the wrong width, then again at the right one.
 * `useSyncExternalStore` reads the real value during render instead, and the
 * server snapshot is `false` so SSR always produces the desktop markup.
 */
function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(QUERY)
  mql.addEventListener("change", onChange)
  return () => mql.removeEventListener("change", onChange)
}

export function useIsMobile(): boolean {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false,
  )
}
