import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, login } from "../api/client";
import { isKnownRole, setSession } from "../auth/session";
import { copy } from "../copy";

/**
 * Sign-in with local accounts (ADR-0011). The token is kept in memory only —
 * see src/auth/session.ts for the httpOnly-cookie hardening note.
 */
export function LoginView() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

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
      setSession({
        token: response.access_token,
        username: response.username,
        role: response.role,
      });
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from ?? "/metrics", { replace: true });
    } catch (err) {
      // API messages are plain-language by design: show them verbatim.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <h1>{copy.login.heading}</h1>
      {/* role="alert" announces the failure to screen readers immediately */}
      {error && (
        <div role="alert" className="alert">
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
    </main>
  );
}
