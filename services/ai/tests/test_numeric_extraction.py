"""Numeric-token extraction and Decimal normalization edge cases."""

from __future__ import annotations

from headway_ai.grounding import extract_numeric_tokens, normalize_number


class TestExtraction:
    def test_plain_and_thousands_separated(self):
        assert extract_numeric_tokens("VRM was 12,794.92 miles") == ("12,794.92",)
        assert extract_numeric_tokens("VRM was 12794.92 miles") == ("12794.92",)

    def test_sentence_final_punctuation_stripped(self):
        assert extract_numeric_tokens("The total was 42.") == ("42",)
        assert extract_numeric_tokens("In 2026, ridership rose.") == ("2026",)

    def test_dotted_triples_are_version_tokens_not_numbers(self):
        # Documented policy: calc/transform versions like 0.4.0 appear
        # legitimately in grounded prose and are NOT numeric claims.
        assert extract_numeric_tokens("computed by vrm_v0 version 0.4.0") == ()
        assert extract_numeric_tokens("connector 1.2.3.4 emitted the frame") == ()

    def test_identifier_fragments_are_not_numbers(self):
        assert extract_numeric_tokens("record abc123 and route-66") == ()
        assert extract_numeric_tokens("sha f9c40aa1c9f0b") == ()

    def test_hex_id_starting_with_digit_is_flagged_conservatively(self):
        # A digit-leading hex id yields its leading digit run as a token —
        # conservative by design: an unexplained digit run fails, it never
        # silently passes. Drafts cite ids structurally, not in prose.
        assert extract_numeric_tokens("record 9c40aa") == ("9",)

    def test_multiple_tokens(self):
        assert extract_numeric_tokens("VRM 12,794.92 and VRH 1,043.5 in 2026.") == (
            "12,794.92",
            "1,043.5",
            "2026",
        )

    def test_no_numbers(self):
        assert extract_numeric_tokens("no digits here") == ()


class TestNormalization:
    def test_thousands_separator_normalizes_equal(self):
        assert normalize_number("12,794.92") == normalize_number("12794.92")

    def test_trailing_zeros_normalize_equal(self):
        assert normalize_number("13000.00") == normalize_number("13,000")
        assert normalize_number("13000.00") == "13000"

    def test_integral_form_has_no_exponent(self):
        # Decimal.normalize() alone would give 1.3E+4; the harness's
        # canonical form must stay comparable and human-readable.
        assert normalize_number("13000") == "13000"

    def test_fractional_trailing_zeros(self):
        assert normalize_number("0.500") == "0.5"

    def test_leading_zeros(self):
        assert normalize_number("007") == "7"

    def test_unparseable_returns_none(self):
        assert normalize_number("1.2.3") is None
        assert normalize_number("not-a-number") is None

    def test_never_floats(self):
        # 0.1 + 0.2 style artifacts must not appear: exact Decimal semantics.
        assert normalize_number("0.30000000000000004") == "0.30000000000000004"
        assert normalize_number("0.3") == "0.3"
        assert normalize_number("0.30000000000000004") != normalize_number("0.3")
