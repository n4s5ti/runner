#!/usr/bin/env python3
"""Simple HTTP relay server for Vane callback mode.

Stores results from POST requests in memory and serves them via GET.
Designed to receive workflow callbacks and let the browser poll for results.
"""

import argparse
import json
import signal
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional


results: Dict[str, dict] = {}


class RelayHandler(BaseHTTPRequestHandler):
    """HTTP handler that stores and retrieves results by run_id."""

    def _respond(self, status: int, body: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        if body is not None:
            self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_OPTIONS(self) -> None:
        self._respond(204)

    def do_GET(self) -> None:
        run_id = self.path.strip("/")
        if not run_id:
            self._respond(400, {"error": "Missing run_id"})
            return
        data = results.get(run_id)
        if data is None:
            self._respond(404, {"error": f"Result for '{run_id}' not found"})
            return
        self._respond(200, data)

    def do_POST(self) -> None:
        run_id = self.path.strip("/")
        if not run_id:
            self._respond(400, {"error": "Missing run_id in path"})
            return
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "Invalid JSON body"})
            return
        results[run_id] = payload
        self._respond(200, {"status": "stored", "run_id": run_id})

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("[local_relay] %s - %s\n" % (self.client_address[0], format % args))


def create_server(port: int) -> HTTPServer:
    server = HTTPServer(("0.0.0.0", port), RelayHandler)
    server.timeout = 0.5  # allow signal handling to work
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Vane callback relay server")
    parser.add_argument(
        "--port",
        type=int,
        default=9876,
        help="Port to listen on (default: 9876)",
    )
    args = parser.parse_args()

    server = create_server(args.port)

    def shutdown(signum, frame) -> None:
        print(f"\nShutting down relay server...", file=sys.stderr)
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    url = f"http://localhost:{args.port}"
    print(f"Vane Relay listening on {url}", file=sys.stderr)
    print(f"  POST   {url}/<run_id>  - Store a result", file=sys.stderr)
    print(f"  GET    {url}/<run_id>  - Retrieve a result", file=sys.stderr)
    print(f"  Press Ctrl+C to stop.", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
