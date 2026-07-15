"""The metric registry's DIRECTION metadata (handoff 0017, design point 1).

The comparison surface renders deltas SIGN-NEUTRALLY (direction glyph +
magnitude) unless the compared quantity DEFINES a better/worse direction.
That definition lives HERE — in the calc library's registry, next to the
calc-name→metric mapping (headway_calc.persist) — never per-view: a UI must
not decide that "more VRH is good" (it is neither; it is a measurement).

Deliberately minimal (handoff 0017, Open Questions): the ONLY quantity with
a registered direction today is ``coverage`` — the completeness ratio the
vrm/vrh coverage details carry — where higher genuinely is better (more of
the period's service is evidenced by telemetry). Every reported metric
(vrm, vrh, upt, pmt, voms, otp, headway_adherence) maps to None: no
better/worse claim is registered for it, so its deltas stay sign-neutral.
Expanding this map is a deliberate act with its own review — e.g. otp is
NOT registered even though "more on-time" sounds better, because otp_v0's
figure moves with the agency-configurable window and a green/red arrow
would imply a quality verdict the calc does not make.
"""

from __future__ import annotations

#: The one registered direction value. (A "lower_is_better" vocabulary slot
#: exists by symmetry but nothing registers it yet.)
HIGHER_IS_BETTER = "higher_is_better"
LOWER_IS_BETTER = "lower_is_better"

#: Quantity name → direction, or None (sign-neutral — the default for every
#: reported metric). Keys are the vocabulary the comparison surface compares:
#: the computed.metric_values.metric names plus the detail-level ``coverage``
#: ratio. Start with coverage only; expand deliberately (handoff 0017).
QUANTITY_DIRECTIONS: dict[str, str | None] = {
    "coverage": HIGHER_IS_BETTER,
    "vrm": None,
    "vrh": None,
    "upt": None,
    "pmt": None,
    "voms": None,
    "otp": None,
    "headway_adherence": None,
}

DIRECTION_NOTE = (
    "Deltas are sign-neutral (direction glyph + magnitude) unless the "
    "quantity registers a direction here in the calc library's metric "
    "registry. Only 'coverage' (higher_is_better) is registered today; no "
    "reported metric claims a better/worse direction (handoff 0017)."
)


def direction_for(quantity: str) -> str | None:
    """The registered direction for a quantity, or None (sign-neutral).

    An unknown quantity is honestly sign-neutral: absence of a registry row
    is absence of a better/worse claim, never a guess.
    """
    return QUANTITY_DIRECTIONS.get(quantity)
