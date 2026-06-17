#!/usr/bin/env python3
"""Unified LLM client supporting ollama, openai, anthropic, and groq providers.

Matches the 4-method contract from the Vane TypeScript ``BaseLLM``:
``generate_text``, ``stream_text``, ``generate_object``, ``stream_object``.

Usage:
    llm = VaneLLM(provider="openai", model="gpt-4o", provider_key="sk-...")
    answer = llm.generate_text("You are a helpful assistant.", "What is Rust?")
    for chunk in llm.stream_text("You are a helper.", "Tell me a story."):
        print(chunk, end="")
    obj = llm.generate_object("Classify.", "hello world", {"type": "object"})
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Generator, Iterable

from openai import OpenAI
from openai.types.chat import ChatCompletionChunk

from research_common import DEFAULT_TEMPERATURE, run_ollama

_VALID_PROVIDERS = frozenset({"ollama", "openai", "anthropic", "groq"})

# Maximum seconds to wait between retries.
_BACKOFF = 2.0


# ---------------------------------------------------------------------------
# Output types matching Vane TS BaseLLM output shapes.
# ---------------------------------------------------------------------------

@dataclass
class GenerateTextOutput:
    """Output from a non-streaming text generation call."""
    text: str
    model: str = ""
    provider: str = ""
    finish_reason: str = ""


@dataclass
class StreamTextOutput:
    """A single chunk yielded by ``stream_text`` / ``stream_object``."""
    delta: str = ""
    finish_reason: str = ""


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict[str, Any]:
    """Parse *text* as JSON with multi-level fallback:

    1. Direct ``json.loads``
    2. Extract from ```json ... ``` fences
    3. Extract from bare ``` ... ``` fences

    Raises ``ValueError`` with the raw text when all attempts fail.
    """
    raw = text.strip()

    # 1 -- direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2 -- ```json ... ``` fence
    m = re.search(
        r"```(?:json)\s*\n(.+?)\n```", raw, re.DOTALL | re.IGNORECASE
    )
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3 -- bare ``` ... ``` fence (no language tag)
    m = re.search(r"```\s*\n(.+?)\n```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Failed to parse JSON from response:\n{raw}")


def _json_schema_instruction(schema: dict[str, Any]) -> str:
    """Build a system-prompt snippet asking for valid JSON matching *schema*."""
    return (
        "You must respond with valid JSON only -- no explanations, no markdown "
        "fences. The response MUST match this schema:\n"
        f"{json.dumps(schema, indent=2)}"
    )


def _build_messages(
    system: str | None,
    user: str | None,
    messages: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    """Normalise the flexible message-passing API into a single messages list."""
    if messages is not None:
        return messages
    msgs: list[dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    if user:
        msgs.append({"role": "user", "content": user})
    return msgs


# ---------------------------------------------------------------------------
# VaneLLM
# ---------------------------------------------------------------------------

class VaneLLM:
    """Unified LLM client for classifier / researcher / writer agents.

    Parameters
    ----------
    provider :
        One of ``"ollama"``, ``"openai"``, ``"anthropic"``, ``"groq"``.
    model :
        Model name (e.g. ``"gpt-4o"``, ``"claude-sonnet-4-20250514"``,
        ``"llama3.2:3b"``).
    provider_key :
        API key for non-ollama providers.  **Required** when *provider* is
        not ``"ollama"``.
    ollama_url :
        Base URL of the Ollama server (default ``http://localhost:11434``).
    temperature :
        Sampling temperature (default 0.2).  Passed to every generation call
        unless overridden per-call.
    ollama_timeout :
        Timeout in seconds for the Ollama CLI ``subprocess.run`` call.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        provider_key: str | None = None,
        ollama_url: str = "http://localhost:11434",
        temperature: float = DEFAULT_TEMPERATURE,
        ollama_timeout: int = 900,
    ) -> None:
        if provider not in _VALID_PROVIDERS:
            raise ValueError(
                f"Unsupported provider {provider!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}"
            )
        if provider != "ollama" and not provider_key:
            raise ValueError(f"provider_key is required when provider={provider!r}")

        self.provider = provider
        self.model = model
        self.provider_key = provider_key
        self.ollama_url = ollama_url.rstrip("/")
        self.temperature = temperature
        self.ollama_timeout = ollama_timeout

        # Build the appropriate OpenAI-compatible client.
        if provider == "openai":
            self._client = OpenAI(api_key=provider_key)
        elif provider == "groq":
            self._client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=provider_key,
            )
        elif provider == "anthropic":
            self._client = OpenAI(
                base_url="https://api.anthropic.com/v1",
                api_key=provider_key,
            )
        else:  # ollama
            self._client = OpenAI(
                base_url=f"{self.ollama_url}/v1",
                api_key="ollama",
            )

    # ------------------------------------------------------------------
    # Public API — 4 methods matching Vane TS BaseLLM contract
    # ------------------------------------------------------------------

    def generate_text(
        self,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> GenerateTextOutput:
        """Non-streaming text generation.

        Accepts the classic ``(system_prompt, user_prompt)`` pair *or* an
        explicit ``messages`` list.  If both are provided ``messages`` wins.
        """
        msgs = _build_messages(system_prompt, user_prompt, messages)

        if self.provider == "ollama":
            return self._generate_text_ollama(msgs, temperature, max_tokens)

        return self._generate_text_api(
            msgs, temperature, max_tokens, retries
        )

    def stream_text(
        self,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> Generator[StreamTextOutput, None, None]:
        """Streaming text generation.

        Yields ``StreamTextOutput`` deltas.  Only available for cloud
        backends (the Ollama CLI mode does not support streaming).
        """
        msgs = _build_messages(system_prompt, user_prompt, messages)

        if self.provider == "ollama":
            # Fall back to /v1 endpoint for streaming (CLI can't stream).
            yield from self._stream_text_api(
                msgs, temperature, max_tokens, retries
            )
            return

        yield from self._stream_text_api(
            msgs, temperature, max_tokens, retries
        )

    def generate_object(
        self,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> dict[str, Any]:
        """Return a parsed JSON object.

        For **openai** the native ``response_format`` parameter is used.
        All other providers inject a schema instruction into the system prompt
        and parse the text reply.  *schema* is optional — when omitted the
        prompt must self-describe the expected JSON shape.
        """
        msgs = _build_messages(system_prompt, user_prompt, messages)

        if self.provider == "ollama":
            return self._generate_object_ollama(
                msgs, schema, temperature, max_tokens
            )

        if self.provider == "openai":
            return self._generate_object_openai(
                msgs, temperature, max_tokens, retries
            )

        # groq / anthropic -- inject schema into system prompt
        return self._generate_object_via_prompt(
            msgs, schema, temperature, max_tokens, retries
        )

    def stream_object(
        self,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        schema: dict[str, Any] | None = None,
        *,
        messages: list[dict[str, str]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        retries: int = 1,
    ) -> Generator[dict[str, Any] | StreamTextOutput, None, None]:
        """Stream a JSON object.

        Yields intermediate ``StreamTextOutput`` chunks and yields the final
        parsed ``dict`` as the last item.  Only available for cloud backends.
        """
        msgs = _build_messages(system_prompt, user_prompt, messages)

        if self.provider == "ollama":
            # Non-streaming fallback -- yield the final object directly.
            yield self.generate_object(
                messages=msgs,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                retries=retries,
            )
            return

        yield from self._stream_object_api(
            msgs, schema, temperature, max_tokens, retries
        )

    # ------------------------------------------------------------------
    # Text generation internals
    # ------------------------------------------------------------------

    def _generate_text_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
    ) -> GenerateTextOutput:
        """Call the local Ollama CLI via ``run_ollama``."""
        # Flatten messages into a conversation string.
        parts: list[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"{role.capitalize()}: {content}")
        combined = "\n\n".join(parts)

        text = run_ollama(
            prompt=combined,
            model=self.model,
            temperature=temperature if temperature is not None else self.temperature,
            timeout_seconds=self.ollama_timeout,
        )
        return GenerateTextOutput(text=text)

    def _generate_text_api(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        retries: int,
    ) -> GenerateTextOutput:
        """Call the OpenAI SDK (works for openai, groq, anthropic)."""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            stream=False,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(_BACKOFF)
                    continue
                raise

            choice = response.choices[0]
            return GenerateTextOutput(
                text=choice.message.content or "",
                finish_reason=choice.finish_reason or "",
            )

        # Should not be reached, but keep the type-checker happy.
        raise RuntimeError("Unreachable") from last_error

    # ------------------------------------------------------------------
    # Streaming internals
    # ------------------------------------------------------------------

    def _stream_text_api(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        retries: int,
    ) -> Generator[StreamTextOutput, None, None]:
        """Stream text from the OpenAI SDK."""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            stream=True,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                stream: Iterable[ChatCompletionChunk] = (
                    self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
                )
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(_BACKOFF)
                    continue
                raise

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                yield StreamTextOutput(
                    delta=delta.content or "",
                    finish_reason=(
                        chunk.choices[0].finish_reason or ""
                        if chunk.choices else ""
                    ),
                )
            return  # successful stream completed

        raise RuntimeError("Unreachable") from last_error

    def _stream_object_api(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
        retries: int,
    ) -> Generator[dict[str, Any] | StreamTextOutput, None, None]:
        """Stream JSON from the OpenAI SDK.

        Yields intermediate ``StreamTextOutput`` deltas and the final parsed
        ``dict`` as the last item.
        """
        # For openai: try response_format; for groq/anthropic: inject schema.
        if self.provider == "openai":
            kwargs: dict[str, Any] = dict(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                stream=True,
            )
        else:
            # Inject schema into system prompt if provided.
            msgs = list(messages)
            if schema:
                instr = _json_schema_instruction(schema)
                if msgs and msgs[0].get("role") == "system":
                    msgs[0] = {"role": "system", "content": msgs[0]["content"] + "\n\n" + instr}
                else:
                    msgs.insert(0, {"role": "system", "content": instr})
            kwargs = dict(
                model=self.model,
                messages=msgs,
                stream=True,
            )

        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                stream: Iterable[ChatCompletionChunk] = (
                    self._client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
                )
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(_BACKOFF)
                    continue
                raise

            buffer_parts: list[str] = []
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                content = delta.content or ""
                buffer_parts.append(content)
                yield StreamTextOutput(delta=content)

            # Stream finished -- parse the buffer.
            full_text = "".join(buffer_parts)
            yield _extract_json(full_text)
            return

        raise RuntimeError("Unreachable") from last_error

    # ------------------------------------------------------------------
    # Structured-object generation internals
    # ------------------------------------------------------------------

    def _generate_object_ollama(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Ollama JSON path: inject schema into system prompt, call
        the OpenAI-compatible /v1 endpoint, then parse the text reply."""
        msgs = list(messages)
        if schema:
            instr = _json_schema_instruction(schema)
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {
                    "role": "system",
                    "content": msgs[0]["content"] + "\n\n" + instr,
                }
            else:
                msgs.insert(0, {"role": "system", "content": instr})

        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=msgs,
            stream=False,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = self._client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        return _extract_json(text)

    def _generate_object_openai(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        retries: int,
    ) -> dict[str, Any]:
        """OpenAI native JSON mode via ``response_format``."""
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            stream=False,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(_BACKOFF)
                    continue
                raise

            text = response.choices[0].message.content or ""
            return _extract_json(text)

        raise RuntimeError("Unreachable") from last_error

    def _generate_object_via_prompt(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any] | None,
        temperature: float | None,
        max_tokens: int | None,
        retries: int,
    ) -> dict[str, Any]:
        """Fallback JSON path (groq, anthropic): embed schema in the system
        prompt and parse the text reply."""
        msgs = list(messages)
        if schema:
            instr = _json_schema_instruction(schema)
            if msgs and msgs[0].get("role") == "system":
                msgs[0] = {
                    "role": "system",
                    "content": msgs[0]["content"] + "\n\n" + instr,
                }
            else:
                msgs.insert(0, {"role": "system", "content": instr})

        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=msgs,
            stream=False,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        last_error: Exception | None = None
        for attempt in range(max(1, retries)):
            try:
                response = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    time.sleep(_BACKOFF)
                    continue
                raise

            text = response.choices[0].message.content or ""
            return _extract_json(text)

        raise RuntimeError("Unreachable") from last_error
