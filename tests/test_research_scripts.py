from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_common
import research_runner
import searxng_ollama_research


class ValidationTests(unittest.TestCase):
    def test_rejects_empty_query(self) -> None:
        with self.assertRaises(research_common.ValidationError):
            research_common.require_non_empty("  ", "query")

    def test_rejects_non_https_destination(self) -> None:
        with self.assertRaises(research_common.ValidationError):
            research_common.validate_destination_url("http://example.test/hook")

    def test_rejects_embedded_destination_credentials(self) -> None:
        with self.assertRaises(research_common.ValidationError):
            research_common.validate_destination_url("https://user:pass@example.test/hook")

    def test_parses_bounded_temperature(self) -> None:
        self.assertEqual(research_common.parse_temperature("0"), 0.0)
        self.assertEqual(research_common.parse_temperature("2"), 2.0)
        with self.assertRaises(research_common.ValidationError):
            research_common.parse_temperature("2.1")

    def test_parses_bounded_top_n(self) -> None:
        self.assertEqual(research_common.parse_top_n("1"), 1)
        self.assertEqual(research_common.parse_top_n("10"), 10)
        with self.assertRaises(research_common.ValidationError):
            research_common.parse_top_n("11")


class OllamaInvocationTests(unittest.TestCase):
    def test_ollama_invoked_without_shell_and_query_on_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "fake_ollama.py"
            capture = tmp_path / "capture.json"
            fake.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "payload = {'argv': sys.argv[1:], 'stdin': sys.stdin.read()}\n"
                "open(os.environ['CAPTURE_PATH'], 'w', encoding='utf-8').write(json.dumps(payload))\n"
                "print('synthetic answer')\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            old_capture = os.environ.get("CAPTURE_PATH")
            os.environ["CAPTURE_PATH"] = str(capture)
            try:
                output = research_common.run_ollama(
                    prompt="private query text",
                    model="llama3.2:3b",
                    temperature=0.7,
                    executable=str(fake),
                )
            finally:
                if old_capture is None:
                    os.environ.pop("CAPTURE_PATH", None)
                else:
                    os.environ["CAPTURE_PATH"] = old_capture

            self.assertEqual(output, "synthetic answer")
            payload = json.loads(capture.read_text(encoding="utf-8"))
            self.assertEqual(payload["argv"], ["run", "llama3.2:3b"])
            self.assertIn("/set parameter temperature 0.7", payload["stdin"])
            self.assertIn("private query text", payload["stdin"])
            self.assertNotIn("private query text", payload["argv"])


class ResultShapeTests(unittest.TestCase):
    def test_research_runner_result_shape(self) -> None:
        result = research_runner.build_result(
            query="hello",
            model="llama3.2:3b",
            temperature=0.2,
            answer="answer",
        )
        self.assertEqual(result["flow"], "research-ollama")
        self.assertEqual(result["sources"], [])
        self.assertEqual(len(result["query_sha256"]), 64)
        self.assertEqual(result["answer"], "answer")

    def test_searxng_result_shape(self) -> None:
        sources = [{"title": "T", "url": "https://example.test", "snippet": "S", "engine": "E"}]
        result = searxng_ollama_research.build_result(
            query="hello",
            model="llama3.2:3b",
            temperature=0.2,
            answer="answer",
            sources=sources,
        )
        self.assertEqual(result["flow"], "research-searxng-ollama")
        self.assertEqual(result["sources"], sources)
        self.assertEqual(len(result["query_sha256"]), 64)


class SearxngParsingTests(unittest.TestCase):
    def test_search_parses_and_bounds_results(self) -> None:
        seen_paths: list[str] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                seen_paths.append(self.path)
                body = json.dumps(
                    {
                        "results": [
                            {"title": "One", "url": "https://one.test", "content": " first  result ", "engine": "alpha"},
                            {"title": "Two", "url": "https://two.test", "content": "second", "engine": "beta"},
                            {"title": "Three", "url": "https://three.test", "content": "third", "engine": "gamma"},
                        ]
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            results = searxng_ollama_research.search_searxng(base_url=url, query="space query", top_n=2)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["snippet"], "first result")
        self.assertIn("q=space+query", seen_paths[0])
        self.assertIn("format=json", seen_paths[0])


if __name__ == "__main__":
    unittest.main()
