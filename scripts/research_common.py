#!/usr/bin/env python3
"""Shared helpers for stateless GitHub Actions research runners."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_MODEL = "llama3.2:3b"
DEFAULT_TEMPERATURE = 0.2
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0
MIN_TOP_N = 1
MAX_TOP_N = 10


class ValidationError(ValueError):
    """Raised when caller-supplied input is unsafe or invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def require_non_empty(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ValidationError(f"{name} must be non-empty")
    return value.strip()


def validate_destination_url(value: str | None) -> str:
    url = require_non_empty(value, "destination_url")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("destination_url must be an HTTPS URL")
    if parsed.username or parsed.password:
        raise ValidationError("destination_url must not include embedded credentials")
    return url


def parse_temperature(value: str | float | None) -> float:
    if value in (None, ""):
        return DEFAULT_TEMPERATURE
    try:
        temperature = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("temperature must be numeric") from exc
    if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
        raise ValidationError(
            f"temperature must be between {MIN_TEMPERATURE:g} and {MAX_TEMPERATURE:g}"
        )
    return temperature


def parse_top_n(value: str | int | None) -> int:
    if value in (None, ""):
        return 5
    try:
        top_n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("top_n must be an integer") from exc
    if not MIN_TOP_N <= top_n <= MAX_TOP_N:
        raise ValidationError(f"top_n must be between {MIN_TOP_N} and {MAX_TOP_N}")
    return top_n


def query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run_ollama(
    *,
    prompt: str,
    model: str,
    temperature: float,
    executable: str = "ollama",
    timeout_seconds: int = 900,
) -> str:
    """Run Ollama through its CLI without a shell and return stdout.

    Ollama's CLI is intentionally invoked with an argv list and stdin so query
    text never appears in the process title or shell history. The temperature is
    included as an Ollama interactive parameter command, which current Ollama
    accepts on stdin before the prompt body.
    """

    model = require_non_empty(model, "model")
    cli_input = f"/set parameter temperature {temperature:g}\n\n{prompt}"
    completed = subprocess.run(
        [executable, "run", model],
        input=cli_input,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(f"ollama failed with exit code {completed.returncode}{detail}")
    output = completed.stdout.strip()
    if not output:
        raise RuntimeError("ollama returned empty output")
    return output


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True)
    parser.add_argument("--destination-url", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", default=str(DEFAULT_TEMPERATURE))
    parser.add_argument("--output", default="result.json")
    parser.add_argument("--ollama-executable", default="ollama")


def validate_common_args(args: argparse.Namespace) -> tuple[str, str, str, float]:
    query = require_non_empty(args.query, "query")
    destination_url = validate_destination_url(args.destination_url)
    model = require_non_empty(args.model, "model")
    temperature = parse_temperature(args.temperature)
    return query, destination_url, model, temperature
