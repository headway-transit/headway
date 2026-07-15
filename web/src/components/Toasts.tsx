/**
 * The shell's toast region (handoff 0017, design point 4): one persistent
 * aria-live="polite" region (role="status") that announces action
 * confirmations — create / supersede / certify — pushed via src/toasts.ts.
 *
 * The container is ALWAYS rendered (an aria-live region that pops into
 * existence with its first message is unreliably announced); toasts inside
 * it are plain text with an explicit dismiss button — no auto-hide (see the
 * store's lifetime note). Success tokens + border: the meaning is in the
 * words, never color alone.
 *
 * role="log" (implicit aria-live polite): the right semantics for a stream
 * of confirmations, and deliberately NOT role="status" — views keep their
 * own status/alert elements and the two must never collide in the
 * accessibility tree.
 */

import { copy } from "../copy";
import { dismissToast, useToasts } from "../toasts";

export function ToastRegion() {
  const toasts = useToasts();
  return (
    <div
      className="toast-region"
      role="log"
      aria-live="polite"
      aria-label={copy.toasts.regionLabel}
    >
      {toasts.map((toast) => (
        <div className="toast" key={toast.id}>
          <p>{toast.message}</p>
          <button
            type="button"
            className="link-like"
            onClick={() => dismissToast(toast.id)}
          >
            {copy.toasts.dismiss}
            <span className="visually-hidden">: {toast.message}</span>
          </button>
        </div>
      ))}
    </div>
  );
}
