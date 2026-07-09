/**
 * Hand-rolled modal dialog per the ARIA Authoring Practices Guide dialog
 * pattern: role="dialog", aria-modal="true", labelled by its heading, focus
 * moved in on open, Tab/Shift+Tab trapped inside, Escape closes, and focus
 * returns to the opener on close.
 *
 * (React Aria / Radix adoption is the design-system increment per the
 * Frontend Engineer role file; this walking skeleton hand-rolls one pattern.)
 */

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface ModalProps {
  /** id of the element (inside the modal) that names the dialog. */
  titleId: string;
  onClose: () => void;
  children: ReactNode;
}

export function Modal({ titleId, onClose, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const focusables = () =>
      Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));

    // Move focus into the dialog on open.
    (focusables()[0] ?? dialog).focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === dialog)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    dialog.addEventListener("keydown", onKeyDown);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      // Return focus to the control that opened the dialog.
      opener?.focus();
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="modal"
        tabIndex={-1}
      >
        {children}
      </div>
    </div>
  );
}
