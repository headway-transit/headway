"""Claim / GroundedDraft contract: no free prose, no unlabeled drafts."""

from __future__ import annotations

import dataclasses

import pytest

from headway_ai.claims import Claim, GroundedDraft


def make_claim(**overrides):
    base = dict(
        text="VRM for May 2026 was 12,794.92 miles.",
        cited_record_kind="computed.metric_values",
        cited_record_id="5f3c2a9e-1d4b-4c8e-9f0a-7b6d5e4c3b2a",
        numeric_values=("12794.92",),
    )
    base.update(overrides)
    return Claim(**base)


class TestClaim:
    def test_requires_text(self):
        with pytest.raises(ValueError):
            make_claim(text="   ")

    def test_requires_citation(self):
        with pytest.raises(ValueError):
            make_claim(cited_record_kind="")
        with pytest.raises(ValueError):
            make_claim(cited_record_id="")

    def test_numeric_values_must_be_strings_never_floats(self):
        with pytest.raises(TypeError):
            make_claim(numeric_values=(12794.92,))

    def test_numeric_values_list_coerced_to_tuple(self):
        claim = make_claim(numeric_values=["12794.92"])
        assert claim.numeric_values == ("12794.92",)

    def test_frozen(self):
        claim = make_claim()
        with pytest.raises(dataclasses.FrozenInstanceError):
            claim.text = "changed"


class TestGroundedDraft:
    def test_free_prose_without_claims_is_not_representable(self):
        with pytest.raises(ValueError):
            GroundedDraft(claims=(), provider_name="stub", provider_version="0.1.0")

    def test_claims_must_be_claim_objects(self):
        with pytest.raises(TypeError):
            GroundedDraft(
                claims=("just some prose",),
                provider_name="stub",
                provider_version="0.1.0",
            )

    def test_requires_provider_metadata(self):
        with pytest.raises(ValueError):
            GroundedDraft(claims=(make_claim(),), provider_name="", provider_version="0.1.0")
        with pytest.raises(ValueError):
            GroundedDraft(claims=(make_claim(),), provider_name="stub", provider_version="")

    def test_ai_generated_is_always_true_and_not_settable(self):
        draft = GroundedDraft(
            claims=(make_claim(),), provider_name="stub", provider_version="0.1.0"
        )
        assert draft.ai_generated is True
        with pytest.raises(TypeError):
            GroundedDraft(
                claims=(make_claim(),),
                provider_name="stub",
                provider_version="0.1.0",
                ai_generated=False,
            )
        with pytest.raises(dataclasses.FrozenInstanceError):
            draft.ai_generated = False

    def test_claims_list_coerced_to_tuple(self):
        draft = GroundedDraft(
            claims=[make_claim()], provider_name="stub", provider_version="0.1.0"
        )
        assert isinstance(draft.claims, tuple)
