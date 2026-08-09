/**
 * Where the operator session token lives in the browser.
 *
 * `localStorage`, deliberately, and with a known trade-off: the gateway is a
 * separate origin from this app, so an httpOnly cookie set by the gateway would
 * never be sent by the browser without either same-site hosting or a Next.js
 * route handler proxying every Control Panel call. Both are larger changes than
 * this screen needs today. The cost is that a successful XSS in the panel can
 * read the token — mitigated, not solved, by the 8-hour server-side expiry and
 * by revocation on logout. Recorded as an open decision in the vault.
 *
 * This module is the only place that knows the storage key, so moving to
 * cookies later means changing this file and nothing else.
 */

const TOKEN_KEY = "jawara.session.token"

type Listener = () => void

const listeners = new Set<Listener>()

export function getToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token)
  notify()
}

export function clearToken(): void {
  if (typeof window === "undefined") return
  window.localStorage.removeItem(TOKEN_KEY)
  notify()
}

/**
 * Called by the API client when the gateway rejects a token.
 *
 * Clearing here rather than in each screen means a session that expires
 * mid-poll drops the operator on the login page once, not once per widget.
 */
export function onUnauthorized(): void {
  if (getToken() !== null) clearToken()
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function notify(): void {
  for (const listener of listeners) listener()
}
