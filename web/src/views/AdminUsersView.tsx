/**
 * /admin/users — user management v0 (handoff 0025, design point 1): list,
 * create, reset password, change role, deactivate/reactivate. Every write
 * is certifying_official-only and audited SERVER-SIDE; role checks here
 * are UX only.
 *
 * THE LOCKOUT FAIL-SAFE lives in the API: deactivating or demoting the
 * last active certifying official is refused (409, plain language). This
 * page states the same rule at the control (aria-disabled + visible
 * reason — the house pattern: never a native disabled that swallows the
 * click), and a click still asks the server, whose refusal renders
 * VERBATIM at that control. The server is the rule; the UI is the
 * explanation.
 */

import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  createUser,
  deactivateUser,
  listUsers,
  reactivateUser,
  resetUserPassword,
  setUserRole,
} from "../api/client";
import type { UserRecord } from "../api/types";
import { canCertify, useSession } from "../auth/session";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { Skeleton } from "../components/Skeleton";
import { copy } from "../copy";

const t = copy.admin.users;

const ROLES = [
  "viewer",
  "data_steward",
  "report_preparer",
  "certifying_official",
] as const;

function roleLabel(role: string): string {
  return copy.roleLabels[role] ?? role;
}

/** Workflow timestamp label (never a figure). */
function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  });
}

interface RowProps {
  user: UserRecord;
  /** True when this row is the LAST active certifying official — the
   *  server would refuse deactivation/demotion; the UI says so up front. */
  isLastActiveAdmin: boolean;
  currentUsername: string | null;
  onChanged: () => Promise<void>;
}

function UserRow({
  user,
  isLastActiveAdmin,
  currentUsername,
  onChanged,
}: RowProps) {
  const [pendingRole, setPendingRole] = useState(user.role);
  const [resetOpen, setResetOpen] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const roleSelectId = useId();
  const resetInputId = useId();
  const reasonId = useId();
  const messageId = useId();

  const run = async (action: () => Promise<string | null>) => {
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    try {
      const confirmation = await action();
      await onChanged();
      setMessage(confirmation);
    } catch (err) {
      // Server refusals — the lockout fail-safe's 409 included — verbatim.
      setErrorMessage(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const submitRoleChange = () => {
    if (pendingRole === user.role || busy) return;
    void run(async () => {
      const result = await setUserRole(user.username, pendingRole);
      const confirmation = t.role.changed(
        user.username,
        roleLabel(result.role),
      );
      return result.note ? `${confirmation} ${result.note}` : confirmation;
    });
  };

  const submitReset = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    void run(async () => {
      await resetUserPassword(user.username, newPassword);
      setResetOpen(false);
      setNewPassword("");
      return t.resetPassword.done(user.username);
    });
  };

  const submitActiveChange = () => {
    if (busy) return;
    // aria-disabled: the click is NOT swallowed — the server answers, and
    // its refusal (the fail-safe 409) renders verbatim right here.
    void run(async () => {
      if (user.is_active) {
        const result = await deactivateUser(user.username);
        const confirmation = t.deactivate.done(user.username);
        return result.note ? `${confirmation} ${result.note}` : confirmation;
      }
      await reactivateUser(user.username);
      return t.reactivate.done(user.username);
    });
  };

  const deactivateDisabled = isLastActiveAdmin && user.is_active;
  const isYou = user.username === currentUsername;

  return (
    <tr>
      <th scope="row">
        {isYou ? t.youMarker(user.username) : user.username}
      </th>
      <td>
        <label className="visually-hidden" htmlFor={roleSelectId}>
          {t.role.label(user.username)}
        </label>
        <span className="admin-role-cell">
          <select
            id={roleSelectId}
            value={pendingRole}
            onChange={(e) => setPendingRole(e.target.value)}
          >
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {roleLabel(role)}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-disabled={pendingRole === user.role || busy || undefined}
            aria-describedby={
              isLastActiveAdmin && pendingRole !== "certifying_official"
                ? reasonId
                : undefined
            }
            onClick={submitRoleChange}
          >
            {t.role.submit}
          </button>
        </span>
      </td>
      <td>{user.is_active ? t.statusActive : t.statusDeactivated}</td>
      <td>{formatWhen(user.created_at)}</td>
      <td>
        <div className="admin-user-actions">
          <button
            type="button"
            aria-expanded={resetOpen}
            onClick={() => {
              setResetOpen((open) => !open);
              setMessage(null);
              setErrorMessage(null);
            }}
          >
            {t.resetPassword.button(user.username)}
          </button>
          <button
            type="button"
            aria-disabled={deactivateDisabled || busy || undefined}
            aria-describedby={deactivateDisabled ? reasonId : messageId}
            onClick={submitActiveChange}
          >
            {user.is_active
              ? t.deactivate.button(user.username)
              : t.reactivate.button(user.username)}
          </button>
        </div>
        {/* The fail-safe, stated at the disabled control — and the server
            repeats it verbatim if the click goes through anyway. */}
        {deactivateDisabled && (
          <p id={reasonId} className="field-hint">
            {t.deactivate.lastAdminReason}
          </p>
        )}
        {resetOpen && (
          <form className="admin-reset-form" onSubmit={submitReset}>
            <label htmlFor={resetInputId}>
              {t.resetPassword.passwordLabel(user.username)}
            </label>
            <input
              id={resetInputId}
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
            <button type="submit" aria-disabled={busy || undefined}>
              {t.resetPassword.submit}
            </button>
            <button
              type="button"
              onClick={() => {
                setResetOpen(false);
                setNewPassword("");
              }}
            >
              {t.resetPassword.cancel}
            </button>
          </form>
        )}
        <div id={messageId}>
          {errorMessage && (
            <p role="alert" className="alert">
              {errorMessage}
            </p>
          )}
          {message && (
            <p role="status" className="status">
              {message}
            </p>
          )}
        </div>
      </td>
    </tr>
  );
}

function CreateUserForm({ onCreated }: { onCreated: () => Promise<void> }) {
  const [username, setUsername] = useState("");
  const [role, setRole] = useState<string>("viewer");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const usernameId = useId();
  const usernameHintId = useId();
  const roleId = useId();
  const passwordId = useId();
  const passwordHintId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setMessage(null);
    setErrorMessage(null);
    void (async () => {
      try {
        const created = await createUser({ username, role, password });
        await onCreated();
        setMessage(t.create.created(created.username, roleLabel(created.role)));
        setUsername("");
        setRole("viewer");
        setPassword("");
      } catch (err) {
        // Installer-rule refusals (username charset, password length) and
        // duplicate-username 409s, verbatim from the server.
        setErrorMessage(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <section className="card admin-section">
      <h2>{t.create.heading}</h2>
      {errorMessage && (
        <div role="alert" className="alert">
          {errorMessage}
        </div>
      )}
      {message && (
        <div role="status" className="status">
          {message}
        </div>
      )}
      <form className="admin-create-form" onSubmit={submit}>
        <div>
          <label htmlFor={usernameId}>{t.create.usernameLabel}</label>
          <p className="field-hint" id={usernameHintId}>
            {t.create.usernameHint}
          </p>
          <input
            id={usernameId}
            type="text"
            autoComplete="off"
            aria-describedby={usernameHintId}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor={roleId}>{t.create.roleLabel}</label>
          <select
            id={roleId}
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={passwordId}>{t.create.passwordLabel}</label>
          <p className="field-hint" id={passwordHintId}>
            {t.create.passwordHint}
          </p>
          <input
            id={passwordId}
            type="password"
            autoComplete="new-password"
            aria-describedby={passwordHintId}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" aria-disabled={busy || undefined}>
          {t.create.submit}
        </button>
      </form>
    </section>
  );
}

export function AdminUsersView() {
  const session = useSession();
  const [users, setUsers] = useState<UserRecord[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = async () => {
    // Always re-read from the server after a change — never client-adjust.
    try {
      setUsers(await listUsers());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err));
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!canCertify(session)) {
    return (
      <>
        <h1>{t.heading}</h1>
        <p>{copy.admin.notAllowed}</p>
      </>
    );
  }

  const activeAdminCount = (users ?? []).filter(
    (u) => u.role === "certifying_official" && u.is_active,
  ).length;

  return (
    <>
      <Breadcrumbs
        trail={[
          { label: copy.admin.heading, to: "/admin" },
          { label: t.heading },
        ]}
      />
      <h1>{t.heading}</h1>
      <p>{t.intro}</p>

      {loadError && (
        <div role="alert" className="alert">
          {loadError}
        </div>
      )}
      {!users && !loadError && (
        <Skeleton variant="table" count={4} label={copy.loading} />
      )}

      {users && (
        <div className="table-wrap">
          <table className="admin-users-table">
            <caption className="visually-hidden">{t.table.caption}</caption>
            <thead>
              <tr>
                <th scope="col">{t.table.username}</th>
                <th scope="col">{t.table.role}</th>
                <th scope="col">{t.table.status}</th>
                <th scope="col">{t.table.created}</th>
                <th scope="col">{t.table.actions}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <UserRow
                  key={user.username}
                  user={user}
                  isLastActiveAdmin={
                    user.role === "certifying_official" &&
                    user.is_active &&
                    activeAdminCount === 1
                  }
                  currentUsername={session?.username ?? null}
                  onChanged={refresh}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CreateUserForm onCreated={refresh} />
    </>
  );
}
