#!/usr/bin/env python3
"""Flow A: answer a research query with in-runner Ollama."""

from __future__ import annotations

import argparse

from research_common import (
    add_common_arguments,
    query_sha256,
    run_ollama,
    utc_now_iso,
    validate_common_args,
    write_json,
)


def build_prompt(query: str) -> str:
    return (
        "You are a careful research assistant running inside a stateless "
        "GitHub Actions job. Answer the user's research request directly. "
        "State uncertainty when evidence is incomplete.\n\n"
        f"Research request:\n{query}\n"
    )


def build_result(*, query: str, model: str, temperature: float, answer: str) -> dict[str, object]:
    return {
        "flow": "research-ollama",
        "query_sha256": query_sha256(query),
        "model": model,
        "temperature": temperature,
        "generated_at": utc_now_iso(),
        "answer": answer,
        "sources": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    args = parser.parse_args()

    query, _destination_url, model, temperature = validate_common_args(args)
    qhash = query_sha256(query)
    print(f"research-ollama starting query_sha256={qhash}")
    answer = run_ollama(
        prompt=build_prompt(query),
        model=model,
        temperature=temperature,
        executable=args.ollama_executable,
    )
    write_json(args.output, build_result(query=query, model=model, temperature=temperature, answer=answer))
    print(f"research-ollama wrote result query_sha256={qhash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
