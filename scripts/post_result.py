#!/usr/bin/env python3
"""Post result JSON to the request destination without logging the URL."""

from __future__ import annotations

import argparse
import subprocess

from research_common import validate_common_args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-event-path", required=True)
    parser.add_argument("--event-name", default="")
    parser.add_argument("--result", default="result.json")
    parser.add_argument("--curl-executable", default="curl")
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
    _query, destination_url, _model, _temperature = validate_common_args(namespace)
    completed = subprocess.run(
        [
            args.curl_executable,
            "-fsS",
            "-o",
            "/dev/null",
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            f"@{args.result}",
            destination_url,
        ],
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"curl failed with exit code {completed.returncode}")
    print("result posted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
