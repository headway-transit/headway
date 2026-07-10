"""LabeledOutput invariants, StubProvider determinism, OllamaProvider laziness."""

from __future__ import annotations

import dataclasses
import sys

import pytest

from headway_ai.provider import LabeledOutput, OllamaProvider, Provider, StubProvider


class TestLabeledOutputInvariants:
    def test_ai_generated_is_always_true(self):
        output = LabeledOutput(text="hi", provider_name="stub", provider_version="0.1.0")
        assert output.ai_generated is True

    def test_ai_generated_cannot_be_passed_to_constructor(self):
        with pytest.raises(TypeError):
            LabeledOutput(
                text="hi",
                provider_name="stub",
                provider_version="0.1.0",
                ai_generated=False,
            )

    def test_ai_generated_cannot_be_mutated(self):
        output = LabeledOutput(text="hi", provider_name="stub", provider_version="0.1.0")
        with pytest.raises(dataclasses.FrozenInstanceError):
            output.ai_generated = False

    def test_provider_metadata_required(self):
        with pytest.raises(ValueError):
            LabeledOutput(text="hi", provider_name="", provider_version="0.1.0")
        with pytest.raises(ValueError):
            LabeledOutput(text="hi", provider_name="stub", provider_version="")


class TestStubProvider:
    def test_satisfies_provider_protocol(self):
        assert isinstance(StubProvider(), Provider)

    def test_deterministic_across_calls_and_instances(self):
        prompt = "explain the VRM anomaly"
        context = {"metric": "vrm", "period": "2026-05"}
        first = StubProvider().generate(prompt, context)
        second = StubProvider().generate(prompt, dict(reversed(list(context.items()))))
        assert first == second
        assert first.text == second.text

    def test_output_is_labeled(self):
        output = StubProvider().generate("p", {})
        assert output.ai_generated is True
        assert output.provider_name == "stub"
        assert output.provider_version == "0.1.0"

    def test_context_key_order_does_not_matter(self):
        a = StubProvider().generate("p", {"b": "2", "a": "1"})
        b = StubProvider().generate("p", {"a": "1", "b": "2"})
        assert a.text == b.text


class TestOllamaProvider:
    def test_construction_does_not_import_httpx(self):
        before = "httpx" in sys.modules
        provider = OllamaProvider(model="test-model")
        assert provider.version == "ollama:test-model"
        # Constructing the adapter must not pull in the optional dependency.
        assert ("httpx" in sys.modules) == before

    def test_requires_model_name(self):
        with pytest.raises(ValueError):
            OllamaProvider(model="")

    def test_base_url_normalized(self):
        provider = OllamaProvider(model="m", base_url="http://localhost:11434/")
        assert provider.base_url == "http://localhost:11434"
