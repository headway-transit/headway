"""Pluggable text-generation provider abstraction.

Design constraints (AI_SYSTEMS_ENGINEER role, ADR-0001):

- The critical path is open and self-hostable. This increment ships a
  deterministic ``StubProvider`` (used by all tests; no network, no model)
  and an ``OllamaProvider`` adapter for an OpenAI-compatible *local* HTTP
  endpoint. NO hosted/proprietary provider exists here; per the role file
  one may only ever be an optional off-critical-path adapter.
- Every provider output is a :class:`LabeledOutput` whose ``ai_generated``
  field is ``init=False`` with default ``True`` on a frozen dataclass —
  callers cannot construct or mutate an unlabeled output, so presenting
  provider text without the AI-generated label is structurally impossible.
- Providers generate *prose only*. They never see a code path that writes
  to the database, and nothing downstream may treat their text as a source
  of numbers: every draft built from provider output must pass the
  grounding harness (``headway_ai.grounding``) before it is surfaced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

__all__ = ["LabeledOutput", "Provider", "StubProvider", "OllamaProvider"]


@dataclass(frozen=True)
class LabeledOutput:
    """A single piece of AI-generated text, permanently labeled as such.

    ``ai_generated`` is not a constructor argument and the dataclass is
    frozen: there is no way to obtain a ``LabeledOutput`` with
    ``ai_generated`` anything but ``True``.
    """

    text: str
    provider_name: str
    provider_version: str
    ai_generated: bool = field(init=False, default=True)

    def __post_init__(self) -> None:
        if not self.provider_name or not self.provider_version:
            raise ValueError("LabeledOutput requires provider_name and provider_version")


@runtime_checkable
class Provider(Protocol):
    """Minimal pluggable text-generation interface.

    ``generate(prompt, context)`` is the raw text-generation seam; its
    return type is deliberately :class:`LabeledOutput`, not ``str``, so no
    implementation can hand back unlabeled prose.
    """

    name: str
    version: str

    def generate(self, prompt: str, context: Mapping[str, str]) -> LabeledOutput:
        """Produce labeled text for ``prompt`` given key/value ``context``."""
        ...


class StubProvider:
    """Deterministic, template-based provider. No network, no model.

    Used by every test in this repository: identical ``(prompt, context)``
    always yields byte-identical output (context keys are sorted; there is
    no randomness, time, or environment dependence).
    """

    name = "stub"
    version = "0.1.0"

    def generate(self, prompt: str, context: Mapping[str, str]) -> LabeledOutput:
        rendered_context = "; ".join(f"{key}={context[key]}" for key in sorted(context))
        text = f"[AI-generated draft | provider=stub] prompt: {prompt} | context: {{{rendered_context}}}"
        return LabeledOutput(text=text, provider_name=self.name, provider_version=self.version)


class OllamaProvider:
    """Adapter for a *local* OpenAI-compatible chat endpoint (e.g. Ollama).

    Status: NOT yet exercised against a live server (no model runtime in
    the authoring environment); the request shape follows the
    OpenAI-compatible ``/v1/chat/completions`` contract Ollama exposes.
    Live verification is an explicit pending item in services/ai/README.md.

    ``httpx`` is imported lazily inside :meth:`generate` and installed via
    the ``ollama`` optional extra, so the core package stays stdlib-only
    and no test path touches the network.
    """

    name = "ollama"

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model:
            raise ValueError("OllamaProvider requires a model name")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.version = f"ollama:{model}"

    def generate(self, prompt: str, context: Mapping[str, str]) -> LabeledOutput:
        try:
            import httpx  # lazy: only the optional 'ollama' extra needs it
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "OllamaProvider requires httpx; install with: pip install 'headway-ai[ollama]'"
            ) from exc

        context_block = "\n".join(f"{key}: {context[key]}" for key in sorted(context))
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an assistive drafting model for transit analysts. "
                    "Use ONLY the provided context. Never invent numbers or records."
                ),
            },
            {"role": "user", "content": f"{prompt}\n\nContext:\n{context_block}"},
        ]
        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": self.model, "messages": messages, "stream": False},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return LabeledOutput(text=text, provider_name=self.name, provider_version=self.version)
