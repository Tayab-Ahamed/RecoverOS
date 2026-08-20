"""LLM port and adapters.

Agents depend on this narrow interface, so the deterministic adapter can be
substituted for benchmarks and offline demos. A parse failure is treated as a
failure, never as a silent default — risk R10.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    name: str

    def complete_json(self, system: str, prompt: str, schema_hint: str) -> dict: ...


def parse_strict_json(text: str) -> dict:
    """Extract a JSON object, raising rather than guessing on failure."""
    text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError(f"no JSON object found in model output: {text[:200]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"malformed JSON from model: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError("model returned a non-object JSON value")
    return parsed


class AnthropicClient:
    """Live adapter. Uses urllib to avoid a hard third-party dependency."""

    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise LLMError("ANTHROPIC_API_KEY is required for the live LLM adapter")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete_json(self, system: str, prompt: str, schema_hint: str) -> dict:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 1024,
                "system": f"{system}\n\nRespond with JSON only, matching: {schema_hint}",
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            method="POST",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = json.loads(resp.read().decode())
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        try:
            text = raw["content"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected Anthropic response shape: {exc}") from exc
        return parse_strict_json(text)


class DeterministicLLMClient:
    """Offline adapter producing reproducible, clearly-labelled reasoning.

    Output is a function of the prompt, so benchmark runs are repeatable. It is
    reported as SYNTHETIC reasoning and never presented as model output.
    """

    name = "deterministic"

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, system: str, prompt: str, schema_hint: str) -> dict:
        self.calls += 1
        return {"_deterministic": True, "prompt_chars": len(prompt)}
