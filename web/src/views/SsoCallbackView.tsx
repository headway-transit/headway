import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, finishSsoLogin } from "../api/client";
import { isKnownRole, setSession } from "../auth/session";
import { takeBrowserToken } from "../auth/sso";
import { copy } from "../copy";

/**
 * /auth/callback — where the identity provider sends the browser back
 * (handoff 0046). This is the address an administrator registers at the
 * provider, character for character (docs/single-sign-on.md).
 *
 * Everything happens once, on arrival, in this order:
 *
 * 1. read `code` and `state` out of the query string, then SCRUB them from
 *    the visible URL by REPLACING the history entry. A one-time
 *    authorization code and a single-use state have no business in the
 *    address bar, in the back-button history, or in the screenshot someone
 *    pastes into a support ticket;
 * 2. take the browser binding back out of sessionStorage and delete it in
 *    the same breath — single use on this side too, whether this attempt is
 *    about to succeed or fail (migration 0043);
 * 3. finish the sign-in and establish the session through exactly the code
 *    path a local sign-in uses (`setSession`), including the same refusal of
 *    a role this build cannot map;
 * 4. on ANY refusal, put the reader back on the working local sign-in form
 *    with the message. A failed federated attempt must never strand someone
 *    on a dead screen, and the local form is the way back in.
 *
 * The API answers every federated failure with ONE generic message on
 * purpose — the specific reason goes to Headway's audit trail — so this
 * screen shows what it is told and never tries to work out which check
 * failed. Neither the code, the state nor the binding is ever logged or
 * rendered.
 */
export function SsoCallbackView() {
  const navigate = useNavigate();
  const location = useLocation();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const started = useRef(false);
  /**
   * The URL as the provider left it, captured at mount. Step 1 below scrubs
   * the query string within milliseconds, and this work must read what
   * arrived, not what the address bar says afterwards.
   */
  const [arrival] = useState(() => ({
    pathname: location.pathname,
    search: location.search,
  }));

  // Focus lands here after the full-page hop back from the provider, so a
  // screen reader says where the reader now is rather than nothing at all.
  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    // Exactly once. StrictMode double-invokes effects in development, and
    // the server's `state` is single-use: a second exchange would be refused
    // and the reader would be shown a failure that did not happen.
    if (started.current) return;
    started.current = true;

    const params = new URLSearchParams(arrival.search);
    const code = params.get("code");
    const state = params.get("state");
    // Out of the address bar before anything else is attempted, and by
    // REPLACE so the entry that carried them is not left in history either.
    navigate(arrival.pathname, { replace: true });

    // Read and delete together: nothing is left behind for a later visit to
    // this address to pick up, on any outcome below.
    const browserToken = takeBrowserToken();

    const refuse = (message: string) =>
      navigate("/login", { replace: true, state: { ssoError: message } });

    // A provider that refuses (`error=access_denied`, a consent screen the
    // person closed, an expired request) sends no code. Its
    // `error_description` is text this screen did not author and cannot
    // vouch for, so it is never displayed — this is the same generic refusal
    // as every other failure, which is also what the API does.
    if (!code || !state || !browserToken) {
      refuse(copy.login.sso.failed);
      return;
    }

    void (async () => {
      try {
        const response = await finishSsoLogin({
          code,
          state,
          browser_token: browserToken,
        });
        if (!isKnownRole(response.role)) {
          // Exactly the local path's refusal: never sign in with permissions
          // this build cannot map.
          refuse(copy.login.unknownRole(response.role));
          return;
        }
        setSession({
          token: response.access_token,
          username: response.username,
          role: response.role,
        });
        // /today is the post-login landing (handoff 0021, design point 1).
        // The `from` a local sign-in honors cannot survive a full-page hop
        // out to the provider and back, so a federated sign-in always lands
        // on the briefing.
        navigate("/today", { replace: true });
      } catch (err) {
        // API messages are plain-language by design and are shown verbatim.
        // For a federated failure that message is the same sentence every
        // time, deliberately, and this screen does not second-guess it.
        refuse(err instanceof ApiError ? err.message : String(err));
      }
    })();
    // Both are stable — `arrival` is set once, `navigate` is stable across
    // renders — so this runs exactly once, and the ref above holds that line
    // under StrictMode's deliberate double-invoke in development.
  }, [arrival, navigate]);

  return (
    <main className="login-page">
      <h1 ref={headingRef} tabIndex={-1}>
        {copy.login.sso.finishingHeading}
      </h1>
      <p role="status">{copy.login.sso.finishing}</p>
    </main>
  );
}
