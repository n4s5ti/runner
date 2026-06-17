#!/usr/bin/env python3
"""Vane Research Relay — 3-stage pipeline: classify → research → write → deliver.

Reads configuration from environment variables (GitHub Actions pattern) and
runs the full Vane search pipeline.  Handles missing provider keys, empty
search results, timeouts, and partial failures gracefully.

Environment variables:
    QUERY               — required; the user's research question
    MODE                — speed|balanced|quality (default: balanced)
    SEARXNG_URL         — SearXNG endpoint (default: http://127.0.0.1:8080)
    PROVIDER            — ollama|openai|anthropic|groq (default: ollama)
    PROVIDER_KEY        — API key when provider != ollama
    MODEL               — model name override (per-provider default used otherwise)
    CALLBACK_URL        — optional; POST result JSON here after completion
    SYSTEM_INSTRUCTIONS — optional system prompt additions for the writer
    TEMPERATURE         — LLM temperature 0.0-2.0 (default: 0.2)
    TOP_N               — search results per query 1-10 (default: 5)
    SOURCES             — web|academic|discussion (default: web)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any

from vane_prompts import CLASSIFIER_PROMPT, get_researcher_prompt, get_writer_prompt
from vane_llm import VaneLLM

# search_searxng lives in searxng_ollama_research.py.
# The contract specifies importing from research_common — re-export there
# when the module is updated.  Fallback handles both locations.
try:
    from research_common import search_searxng  # type: ignore[attr-defined]
except ImportError:
    from searxng_ollama_research import search_searxng  # type: ignore[import-not-found]

from research_common import (
    write_json,
    utc_now_iso,
    require_non_empty,
    parse_temperature,
    parse_top_n,
    query_sha256,
    ValidationError,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODE = "balanced"
DEFAULT_SEARXNG_URL = "http://127.0.0.1:8080"
DEFAULT_PROVIDER = "ollama"
DEFAULT_TOP_N = 5

MODE_ITERATIONS: dict[str, int] = {
    "speed": 1,
    "balanced": 3,
    "quality": 5,
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "ollama": DEFAULT_MODEL,            # llama3.2:3b
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-haiku-20240307",
    "groq": "llama3-8b-8192",
}

SEARXNG_TIMEOUT = 30     # seconds per search call
LLM_TIMEOUT = 300        # seconds per LLM call
RETRY_BACKOFF = 2        # seconds between LLM retries
MAX_LLM_RETRIES = 1      # number of retries on LLM failure

# JSON Schema for the classification step (passed to generate_object)
CLASSIFICATION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "object",
            "properties": {
                "skipSearch": {"type": "boolean"},
                "personalSearch": {"type": "boolean"},
                "academicSearch": {"type": "boolean"},
                "discussionSearch": {"type": "boolean"},
                "showWeatherWidget": {"type": "boolean"},
                "showStockWidget": {"type": "boolean"},
                "showCalculationWidget": {"type": "boolean"},
            },
            "required": ["skipSearch"],
        },
        "standaloneFollowUp": {"type": "string"},
    },
    "required": ["classification", "standaloneFollowUp"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_env_str(key: str, default: str = "") -> str:
    return (os.environ.get(key) or "").strip() or default


def _get_env_opt(key: str) -> str | None:
    val = (os.environ.get(key) or "").strip()
    return val if val else None


def _parse_search_queries(text: str, fallback: str) -> list[str]:
    """Extract web-search query strings from an LLM-generated response.

    Handles JSON arrays, markdown code blocks, numbered lists, and plain
    line-separated queries.  Falls back to *fallback* (the standalone query)
    when nothing parseable is found.
    """
    cleaned = text.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```").removeprefix("json").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned.removesuffix("```").strip()

    # Try JSON array of strings
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            queries = [str(q).strip() for q in parsed if q and str(q).strip()]
            if queries:
                return queries
    except (json.JSONDecodeError, ValueError):
        pass

    # Try parsing as numbered list or plain lines
    lines: list[str] = []
    for line in cleaned.split("\n"):
        line = line.strip().strip('"').strip("'")
        # Skip empty lines and markdown bullets
        if not line or line.startswith("-") or line.startswith("*"):
            continue
        # Strip leading numbering like "1. ", "12) ", "3. query"
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if line:
            lines.append(line)

    if lines:
        return lines

    return [fallback]


def _deduplicate_sources(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Merge incoming sources, skipping URLs already in existing."""
    seen = {s.get("url", "") for s in existing if s.get("url")}
    merged = list(existing)
    for src in incoming:
        url = src.get("url", "")
        if url and url in seen:
            continue
        merged.append(src)
        if url:
            seen.add(url)
    return merged


def _format_source_context(sources: list[dict[str, str]]) -> str:
    """Format sources into the <result index=N title="...">content</result> block."""
    if not sources:
        return "No relevant search results were found. Answer from general model knowledge and state this limitation."
    parts: list[str] = []
    for idx, src in enumerate(sources, start=1):
        title = src.get("title", "").replace('"', "&quot;")
        snippet = src.get("snippet", "")
        parts.append(f'<result index={idx} title="{title}">\n{snippet}\n</result>')
    return "\n\n".join(parts)


def _post_callback(url: str, payload: dict[str, object]) -> None:
    """POST result JSON to callback_url.  Errors are logged, not fatal."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                print(f"vane-relay WARNING callback returned HTTP {resp.status}")
            else:
                print("vane-relay: callback delivered successfully")
    except Exception as exc:
        print(f"vane-relay WARNING callback failed: {exc}")


def _llm_generate_text(
    llm: VaneLLM,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Call llm.generate_text with one retry on failure."""
    last_exc: Exception | None = None
    for attempt in range(1 + MAX_LLM_RETRIES):
        try:
            return llm.generate_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_LLM_RETRIES:
                print(f"vane-relay WARNING LLM call failed (attempt {attempt + 1}): {exc} — retrying")
                time.sleep(RETRY_BACKOFF)
            else:
                print(f"vane-relay ERROR LLM call failed after {attempt + 1} attempts: {exc}")
                raise
    raise RuntimeError("unreachable") from last_exc


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    *,
    query: str,
    mode: str = DEFAULT_MODE,
    searxng_url: str = DEFAULT_SEARXNG_URL,
    provider: str = DEFAULT_PROVIDER,
    provider_key: str | None = None,
    model: str | None = None,
    callback_url: str | None = None,
    system_instructions: str = "",
    temperature: float = DEFAULT_TEMPERATURE,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Execute the full Vane relay: classify → research → write → deliver.

    Returns the result dictionary.  Caller is responsible for persisting it.
    """

    # --- Validate inputs ---
    query = require_non_empty(query, "QUERY")

    mode = mode.strip().lower()
    if mode not in MODE_ITERATIONS:
        print(f"vane-relay WARNING unknown mode '{mode}', defaulting to '{DEFAULT_MODE}'")
        mode = DEFAULT_MODE

    iterations = MODE_ITERATIONS[mode]

    provider = (provider or DEFAULT_PROVIDER).strip().lower()
    if provider not in PROVIDER_DEFAULT_MODELS:
        raise ValidationError(
            f"Unsupported PROVIDER '{provider}'. "
            f"Supported: {', '.join(sorted(PROVIDER_DEFAULT_MODELS))}"
        )

    if provider != "ollama" and not provider_key:
        raise ValidationError(
            f"PROVIDER_KEY is required when PROVIDER='{provider}'. "
            "Either set the PROVIDER_KEY environment variable or use PROVIDER=ollama."
        )

    resolved_model = model or PROVIDER_DEFAULT_MODELS[provider]

    # --- Initialize LLM client ---
    llm = VaneLLM(
        provider=provider,
        model=resolved_model,
        temperature=temperature,
        provider_key=provider_key,
    )

    qhash = query_sha256(query)
    print(f"vane-relay starting mode={mode} provider={provider} model={resolved_model} query_sha256={qhash}")

    # ======================================================================
    # STEP 1: CLASSIFY
    # ======================================================================
    print("vane-relay: classify step")
    user_prompt = f"Query: {query}"
    classification_result: dict[str, Any] = {}
    try:
        classification_result = llm.generate_object(
            system_prompt=CLASSIFIER_PROMPT,
            user_prompt=user_prompt,
            schema=CLASSIFICATION_SCHEMA,
        )
    except Exception as exc:
        print(f"vane-relay WARNING classification failed: {exc} — proceeding with defaults")

    classification: dict[str, Any] = classification_result.get("classification", {})
    standalone_followup: str = classification_result.get("standaloneFollowUp", query)
    skip_search: bool = classification.get("skipSearch", False)

    print(f"vane-relay: classification skip_search={skip_search} has_followup={bool(standalone_followup)}")

    # ======================================================================
    # STEP 2: RESEARCH (iterative)
    # ======================================================================
    all_sources: list[dict[str, str]] = []
    research_rounds = 0

    if not skip_search:
        for i in range(iterations):
            print(f"vane-relay: research round {i + 1}/{iterations}")

            # --- 2a. Generate search queries via LLM ---
            researcher_prompt = get_researcher_prompt(
                action_desc="",
                mode=mode,
                i=i,
                max_iteration=iterations,
            )

            search_response: str = ""
            try:
                search_response = _llm_generate_text(
                    llm=llm,
                    system_prompt=researcher_prompt,
                    user_prompt=standalone_followup,
                )
            except Exception as exc:
                print(f"vane-relay WARNING researcher LLM call failed round {i + 1}: {exc}")
                continue

            search_queries = _parse_search_queries(search_response, standalone_followup)
            # Limit to 3 queries per round to stay within time budget
            search_queries = search_queries[:3]

            print(f"vane-relay: round {i + 1} generated {len(search_queries)} search queries")

            # --- 2b. Execute searches ---
            round_sources: list[dict[str, str]] = []
            for sq in search_queries:
                try:
                    results = search_searxng(
                        base_url=searxng_url,
                        query=sq,
                        top_n=top_n,
                        timeout_seconds=SEARXNG_TIMEOUT,
                    )
                    round_sources.extend(results)
                except Exception as exc:
                    print(f"vane-relay WARNING SearXNG search failed for query '{sq[:80]}': {exc}")
                    continue

            # Deduplicate and accumulate
            all_sources = _deduplicate_sources(all_sources, round_sources)
            print(f"vane-relay: round {i + 1} got {len(round_sources)} new sources, total={len(all_sources)}")
            research_rounds = i + 1

            # Brief pause between rounds
            if i < iterations - 1:
                time.sleep(1)
    else:
        print("vane-relay: skip_search=True — skipping research phase")

    # ======================================================================
    # STEP 3: WRITE
    # ======================================================================
    print("vane-relay: write step")

    # Format source context using the <result> tag format
    source_context = _format_source_context(all_sources)

    writer_prompt = get_writer_prompt(
        context=source_context,
        system_instructions=system_instructions,
        mode=mode,
    )

    answer = ""
    try:
        answer = _llm_generate_text(
            llm=llm,
            system_prompt=writer_prompt,
            user_prompt=standalone_followup,
        )
    except Exception as exc:
        print(f"vane-relay ERROR writer LLM call failed: {exc}")
        answer = (
            f"[Synthesis unavailable due to LLM error]\n\n"
            f"Query: {query}\n"
            f"Sources found: {len(all_sources)}\n"
        )

    print(f"vane-relay: answer generated ({len(answer)} chars)")

    # ======================================================================
    # STEP 4: DELIVER
    # ======================================================================
    result: dict[str, Any] = {
        "query": query,
        "answer": answer,
        "sources": [
            {"title": s.get("title", ""), "url": s.get("url", ""), "snippet": s.get("snippet", "")}
            for s in all_sources
        ],
        "mode": mode,
        "provider": provider,
        "model": resolved_model,
        "generated_at": utc_now_iso(),
        "classification": classification,
        "research_rounds": research_rounds,
    }

    # Always write local result.json
    write_json("result.json", result)
    print(f"vane-relay wrote result.json query_sha256={qhash}")

    # Optionally POST to callback URL
    if callback_url:
        print("vane-relay: delivering via callback")
        _post_callback(callback_url, result)

    print(f"vane-relay completed query_sha256={qhash}")
    return result


# ---------------------------------------------------------------------------
# Main entry point (env-var driven for GitHub Actions)
# ---------------------------------------------------------------------------

def main() -> int:
    """Read environment variables and run the pipeline.

    Returns 0 on success, 1 on validation failure, 2 on runtime failure.
    """

    query = _get_env_str("QUERY")
    if not query:
        print("FATAL: QUERY environment variable is required", flush=True)
        return 1

    mode = _get_env_str("MODE", DEFAULT_MODE)
    searxng_url = _get_env_str("SEARXNG_URL", DEFAULT_SEARXNG_URL)
    provider = _get_env_str("PROVIDER", DEFAULT_PROVIDER)
    provider_key = _get_env_opt("PROVIDER_KEY")
    model = _get_env_opt("MODEL")
    callback_url = _get_env_opt("CALLBACK_URL")
    system_instructions = _get_env_str("SYSTEM_INSTRUCTIONS")
    sources_filter = _get_env_str("SOURCES", "web")  # reserved for future use
    _ = sources_filter  # mark as intentionally unused in current implementation

    try:
        temperature = parse_temperature(_get_env_str("TEMPERATURE"))
    except ValidationError as exc:
        print(f"FATAL: Invalid TEMPERATURE: {exc}", flush=True)
        return 1

    try:
        top_n = parse_top_n(_get_env_str("TOP_N"))
    except ValidationError as exc:
        print(f"FATAL: Invalid TOP_N: {exc}", flush=True)
        return 1

    print(f"vane-relay main entry mode={mode} provider={provider}", flush=True)

    try:
        run_pipeline(
            query=query,
            mode=mode,
            searxng_url=searxng_url,
            provider=provider,
            provider_key=provider_key,
            model=model,
            callback_url=callback_url,
            system_instructions=system_instructions,
            temperature=temperature,
            top_n=top_n,
        )
        return 0
    except ValidationError as exc:
        print(f"FATAL: {exc}", flush=True)
        return 1
    except Exception as exc:
        print(f"FATAL: unhandled exception: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
