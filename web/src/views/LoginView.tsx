import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ApiError,
  getSsoStatus,
  login,
  startSsoLogin,
  type SsoStatus,
} from "../api/client";
import { isKnownRole, landingPathFor, setSession } from "../auth/session";
import {
  forgetBrowserToken,
  rememberBrowserToken,
  sendToProvider,
} from "../auth/sso";
import { copy } from "../copy";

/**
 * Sign-in (ADR-0011): local accounts always, single sign-on beside them when
 * the agency has configured it and switched it on (handoff 0046). The token
 * is kept in memory only — see src/auth/session.ts for the httpOnly-cookie
 * hardening note.
 *
 * THE LOCAL FORM IS THE BREAK-GLASS PATH, and it is never made to wait for
 * the single-sign-on status call. An installation whose identity provider is
 * misconfigured, slow or unreachable is precisely the one whose administrator
 * needs to sign in with a Headway password — so the status call cannot delay
 * this screen, cannot degrade it, and cannot put an error on it. If it never
 * answers, this is the sign-in screen it has always been.
 */
export function LoginView() {
  const navigate = useNavigate();
  const location = useLocation();
  /**
   * A federated sign-in that failed sends the reader back here with its
   * message in history STATE — never in the URL, which is also where the
   * callback screen has just scrubbed the provider's answer from.
   */
  const returnedSsoError =
    (location.state as { ssoError?: string } | null)?.ssoError ?? null;

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(returnedSsoError);
  const [submitting, setSubmitting] = useState(false);
  const [sso, setSso] = useState<SsoStatus | null>(null);
  const [startingSso, setStartingSso] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  // Focus follows the reader across the whole redirect: the button on this
  // screen, then the callback screen's heading, then back here onto the
  // message that says what happened. After a full-page navigation focus is
  // otherwise on <body> and a screen-reader user is told nothing at all.
  // Mount only, and an alert only exists at mount on the way back from a
  // failed federated attempt: a later local-login failure must not snatch
  // focus out of the form someone is still typing in.
  useEffect(() => {
    alertRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!returnedSsoError) return;
    // The message has been read into this screen's own error slot; take it
    // out of history so Back or a refresh does not replay a failure as
    // though it had just happened.
    navigate(location.pathname, { replace: true, state: null });
  }, [returnedSsoError, navigate, location.pathname]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const status = await getSsoStatus();
        if (!cancelled) setSso(status);
      } catch {
        // DELIBERATELY SILENT. Single sign-on is an ADDITION to this screen.
        // If the status call is refused, slow or unreachable, the reader
        // gets the sign-in screen they have always had — no error about a
        // feature they may not even use, and nothing between them and the
        // password field.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await login({ username, password });
      if (!isKnownRole(response.role)) {
        // Fail loudly rather than signing in with permissions we cannot map.
        setError(copy.login.unknownRole(response.role));
        return;
      }
      const session = {
        token: response.access_token,
        username: response.username,
        role: response.role,
      };
      setSession(session);
      const from = (location.state as { from?: string } | null)?.from;
      // /today is the post-login landing (handoff 0021, design point 1) for
      // every role that acts; a read-only role lands on /review instead
      // (handoff 0047). The page someone was sent here from still wins.
      navigate(from ?? landingPathFor(session), { replace: true });
    } catch (err) {
      // API messages are plain-language by design: show them verbatim.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSsoClick = () => {
    if (startingSso) return;
    setError(null);
    setStartingSso(true);
    void (async () => {
      try {
        const started = await startSsoLogin();
        // The browser binding (migration 0043): held for the length of the
        // redirect, sent back exactly once at the callback, never logged,
        // rendered, or put in a URL.
        rememberBrowserToken(started.browser_token);
        sendToProvider(started.authorization_url);
        // `startingSso` stays true on purpose — this document is leaving.
        // Re-enabling the button would invite a second attempt that
        // overwrites the binding the first one just stored.
      } catch (err) {
        // Either nothing was stored or storing it failed; leave no stale
        // binding behind for the next attempt to trip over.
        forgetBrowserToken();
        setError(err instanceof ApiError ? err.message : String(err));
        setStartingSso(false);
      }
    })();
  };

  return (
    <main className="login-page">
      <h1>{copy.login.heading}</h1>
      {/* role="alert" announces the failure to screen readers immediately;
          tabIndex -1 lets focus land on it when a federated sign-in sent the
          reader back here with a message. */}
      {error && (
        <div role="alert" className="alert" ref={alertRef} tabIndex={-1}>
          {error}
        </div>
      )}
      <form onSubmit={handleSubmit}>
        <label htmlFor="login-username">{copy.login.username}</label>
        <input
          id="login-username"
          type="text"
          autoComplete="username"
          required
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <label htmlFor="login-password">{copy.login.password}</label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="primary" disabled={submitting}>
          {copy.login.submit}
        </button>
      </form>
      {/* Single sign-on, only once the server has said it is configured AND
          on. BELOW the local form on purpose: the status call answers after
          first paint, and a control appearing above the username field would
          shove the form out from under someone already typing in it. The
          words are the administrator's own (`button_label`).

          aria-disabled, not disabled: `disabled` would drop focus to <body>
          at the exact moment the browser is navigating away, which is the
          moment a keyboard user most needs to keep it. */}
      {sso?.enabled && (
        <div className="login-sso">
          <button
            type="button"
            aria-disabled={startingSso || undefined}
            onClick={handleSsoClick}
          >
            {sso.button_label.trim() || copy.login.sso.button}
          </button>
          {/* Present from the moment the button is, and empty until there is
              something to say, so a screen reader announces the change
              instead of missing a live region that arrived already full. */}
          <p role="status" className="field-hint">
            {startingSso ? copy.login.sso.starting : ""}
          </p>
          <p className="field-hint">{copy.login.sso.hint}</p>
        </div>
      )}
      {/* The certified open-data page needs no account at all. */}
      <p>
        <Link to="/public">{copy.nav.publicData}</Link>
      </p>
    </main>
  );
}
