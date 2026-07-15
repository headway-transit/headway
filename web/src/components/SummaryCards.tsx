/**
 * Severity/status summary cards (handoff 0017, design point 2): count cards
 * with a colored top border + label, each card an ACCESSIBLE FILTER TOGGLE
 * over the list below it. Used above /dq (severity), the /safety events list
 * (classification), and the deadlines panel (urgency).
 *
 * Accessibility (binding): each card is a real <button> with aria-pressed;
 * the pressed state is conveyed by aria-pressed + a check mark + the fill —
 * never color alone. Counts are WORKFLOW TALLIES (issues, events, deadlines
 * in a queue), never regulatory figures; the caller formats them.
 */

import type { ReactNode } from "react";
import { copy } from "../copy";

export type SummaryTone = "danger" | "warning" | "info" | "success" | "neutral";

export interface SummaryCard {
  /** The filter value this card toggles. */
  key: string;
  /** Plain-language label ("Blocking open", "Major events", "Overdue"). */
  label: string;
  /** Formatted workflow count, displayed as the card's big figure. */
  count: string;
  tone: SummaryTone;
  /** Whether this card's filter is currently on. */
  pressed: boolean;
  /** Optional icon (decorative; the label carries the meaning). */
  icon?: ReactNode;
}

export interface SummaryCardsProps {
  /** Accessible name for the toggle group. */
  label: string;
  cards: SummaryCard[];
  /**
   * Called with the pressed card's key and its NEXT state. The parent owns
   * the filter semantics (a row may mix filter dimensions).
   */
  onToggle: (key: string, pressed: boolean) => void;
}

export function SummaryCards({ label, cards, onToggle }: SummaryCardsProps) {
  return (
    // A labeled list (the implicit list role supports aria-label); NOT
    // role="group" — that would strip the ul's list semantics and orphan
    // the list items (an axe violation caught in development).
    <ul className="summary-cards" aria-label={label}>
      {cards.map((card) => (
        <li key={card.key}>
          <button
            type="button"
            className={`summary-card tone-${card.tone}`}
            aria-pressed={card.pressed}
            onClick={() => onToggle(card.key, !card.pressed)}
          >
            <span className="summary-count">
              {card.pressed && (
                <span className="pressed-mark" aria-hidden="true">
                  ✓{" "}
                </span>
              )}
              {card.count}
            </span>
            <span className="summary-label">
              {card.icon}
              {card.label}
            </span>
            <span className="visually-hidden">
              {card.pressed
                ? ` — ${copy.summaryCards.pressedHint}`
                : ` — ${copy.summaryCards.unpressedHint}`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
