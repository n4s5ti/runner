#!/usr/bin/env python3
"""Flow B: search with ephemeral SearXNG, then synthesize with Ollama."""

from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from research_common import (
    add_common_arguments,
    parse_top_n,
    query_sha256,
    require_non_empty,
    run_ollama,
    utc_now_iso,
    validate_common_args,
    write_json,
)

DEFAULT_SEARXNG_URL = "http://127.0.0.1:8080"
MAX_FIELD_CHARS = 500


def compact_text(value: object, max_chars: int = MAX_FIELD_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def search_searxng(*, base_url: str, query: str, top_n: int, timeout_seconds: int = 30) -> list[dict[str, str]]:
    base_url = require_non_empty(base_url, "searxng_url").rstrip("/") + "/"
    endpoint = urljoin(base_url, "search") + "?" + urlencode({"q": query, "format": "json"})
    request = Request(endpoint, headers={"Accept": "application/json", "User-Agent": "n4s5ti-runner/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except URLError as exc:
        raise RuntimeError("searxng request failed") from exc

    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("searxng returned invalid JSON") from exc

    results = payload.get("results")
    if not isinstance(results, list):
        return []

    sources: list[dict[str, str]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = compact_text(item.get("url"), 1000)
        title = compact_text(item.get("title"))
        snippet = compact_text(item.get("content"))
        if not url and not title and not snippet:
            continue
        sources.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": compact_text(item.get("engine"), 100),
            }
        )
        if len(sources) >= top_n:
            break
    return sources


def build_prompt(query: str, sources: list[dict[str, str]]) -> str:
    if sources:
        source_lines = []
        for index, source in enumerate(sources, start=1):
            source_lines.append(
                f"[{index}] {source['title']}\nURL: {source['url']}\nSnippet: {source['snippet']}"
            )
        source_block = "\n\n".join(source_lines)
    else:
        source_block = "No SearXNG results were returned. Answer from general model knowledge and state this limitation."

    return (
        "You are a careful research assistant running inside a stateless "
        "GitHub Actions job. Use the SearXNG search context when relevant, "
        "cite source numbers for factual claims, and state uncertainty when "
        "evidence is incomplete.\n\n"
        f"Research request:\n{query}\n\n"
        f"Search context:\n{source_block}\n"
    )


def build_result(
    *,
    query: str,
    model: str,
    temperature: float,
    answer: str,
    sources: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "flow": "research-searxng-ollama",
        "query_sha256": query_sha256(query),
        "model": model,
        "temperature": temperature,
        "generated_at": utc_now_iso(),
        "answer": answer,
        "sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--searxng-url", default=DEFAULT_SEARXNG_URL)
    parser.add_argument("--top-n", default="5")
    args = parser.parse_args()

    query, _destination_url, model, temperature = validate_common_args(args)
    top_n = parse_top_n(args.top_n)
    qhash = query_sha256(query)
    print(f"research-searxng-ollama starting query_sha256={qhash}")
    sources = search_searxng(base_url=args.searxng_url, query=query, top_n=top_n)
    print(f"research-searxng-ollama collected_sources={len(sources)} query_sha256={qhash}")
    answer = run_ollama(
        prompt=build_prompt(query, sources),
        model=model,
        temperature=temperature,
        executable=args.ollama_executable,
    )
    write_json(
        args.output,
        build_result(query=query, model=model, temperature=temperature, answer=answer, sources=sources),
    )
    print(f"research-searxng-ollama wrote result query_sha256={qhash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
