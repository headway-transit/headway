/**
 * The browser binding for a federated sign-in (migration 0043, handoff 0046).
 *
 * WHY ANYTHING AT ALL IS IN sessionStorage HERE. src/auth/session.ts keeps
 * the bearer token in JS memory only, deliberately, and that rule is
 * unchanged — nothing in this file is a credential. Headway's SPA holds a
 * bearer token rather than a cookie, so the API has no cookie to bind the
 * OIDC `state` to. Instead it mints a high-entropy `browser_token`, stores
 * only its SHA-256, and refuses any callback that cannot present the token
 * itself. An attacker who tricks a victim's browser into replaying the
 * attacker's authorization response does not have the victim's token, so the
 * callback is refused: the no-cookie equivalent of state-bound-to-session.
 *
 * That value has to survive a full-page hop out to the identity provider and
 * back, which rules out module memory. sessionStorage is per-tab and dies
 * with the tab, which is exactly the lifetime of one sign-in attempt.
 *
 * It grants nothing on its own — presenting it proves only that this browser
 * is the one that started this sign-in. It is written once, read exactly
 * once, and removed at the moment it is read, whether that read ends in a
 * session or a refusal, so an abandoned attempt leaves nothing behind.
 *
 * It is NEVER logged, never rendered, and never put in a URL.
 */

const BROWSER_TOKEN_KEY = "headway-sso-browser-token";

/**
 * Hold the binding for the length of the redirect. Deliberately NOT
 * defensive: if this browser refuses to store it, the sign-in cannot be
 * completed, and the caller must find that out here rather than after
 * sending someone to their identity provider for nothing.
 */
export function rememberBrowserToken(token: string): void {
  window.sessionStorage.setItem(BROWSER_TOKEN_KEY, token);
}

/**
 * Read the binding AND remove it in the same breath — single use on this
 * side too, matching the server's single-use `state`. Returns null when
 * there is nothing to read: an attempt that was never started in this tab,
 * one already finished, or a callback someone else arranged. All three end
 * the same way, which is the point.
 */
export function takeBrowserToken(): string | null {
  let token: string | null = null;
  try {
    token = window.sessionStorage.getItem(BROWSER_TOKEN_KEY);
  } catch {
    return null;
  }
  forgetBrowserToken();
  return token;
}

/** Best effort: a browser that cannot store had nothing to clean up. */
export function forgetBrowserToken(): void {
  try {
    window.sessionStorage.removeItem(BROWSER_TOKEN_KEY);
  } catch {
    // Storage unavailable (a locked-down profile). Nothing was stored.
  }
}

/**
 * Hand the browser to the identity provider. The one place this application
 * leaves its own document, kept in a named function so the hop is obvious in
 * a stack trace and mockable in a test.
 */
export function sendToProvider(authorizationUrl: string): void {
  window.location.assign(authorizationUrl);
}
