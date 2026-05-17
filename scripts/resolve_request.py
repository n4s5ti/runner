#!/usr/bin/env python3
"""Validate a GitHub event request and expose non-sensitive workflow outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_common import DEFAULT_MODEL, parse_top_n, validate_common_args


def append_output(path: str, name: str, value: str) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-event-path", required=True)
    parser.add_argument("--event-name", default="")
    parser.add_argument("--github-output", required=True)
    parser.add_argument("--include-top-n", action="store_true")
    args = parser.parse_args()

    namespace = argparse.Namespace(
        github_event_path=args.github_event_path,
        event_name=args.event_name,
        query=None,
        destination_url=None,
        model=None,
        temperature=None,
        top_n=None,
    )
    _query, _destination_url, model, _temperature = validate_common_args(namespace)
    append_output(args.github_output, "model", model or DEFAULT_MODEL)
    if args.include_top_n:
        from research_common import resolve_request_values

        top_n = parse_top_n(resolve_request_values(namespace).get("top_n"))
        append_output(args.github_output, "top_n", str(top_n))
    print("request validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
