from __future__ import annotations

import argparse
import json
import subprocess
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RefreshState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.status = "idle"
        self.message = ""

    def snapshot(self) -> dict[str, str]:
        with self.lock:
            return {"status": self.status, "message": self.message}

    def start(self, command: list[str], cwd: Path) -> bool:
        with self.lock:
            if self.status == "running":
                return False
            self.status = "running"
            self.message = "refresh started"
        thread = threading.Thread(
            target=self._run,
            args=(command, cwd),
            name="stock-investor-refresh",
            daemon=True,
        )
        thread.start()
        return True

    def _run(self, command: list[str], cwd: Path) -> None:
        try:
            subprocess.run(command, cwd=cwd, check=True)
        except Exception as error:  # pragma: no cover - defensive server guard
            with self.lock:
                self.status = "failed"
                self.message = str(error)
            return
        with self.lock:
            self.status = "succeeded"
            self.message = "refresh complete"


def make_handler(root: Path, refresh_script: Path, state: RefreshState):
    class StockInvestorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if self.path != "/api/refresh":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            started = state.start([str(refresh_script), "--synced"], root)
            payload = {
                "status": "started" if started else "running",
                "message": "refresh started" if started else "refresh already running",
            }
            self._send_json(payload)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path.startswith("/api/refresh-status"):
                self._send_json(state.snapshot())
                return
            super().do_GET()

        def _send_json(self, payload: dict[str, str]) -> None:
            body = (json.dumps(payload, separators=(",", ":")) + "\n").encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return StockInvestorHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local stock investor dashboard.")
    parser.add_argument("--directory", default=".", help="Runtime directory to serve.")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind address.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port.")
    args = parser.parse_args(argv)

    root = Path(args.directory).resolve()
    refresh_script = root / "scripts" / "run_market_refresh.sh"
    state = RefreshState()
    server = ThreadingHTTPServer(
        (args.bind, args.port),
        make_handler(root, refresh_script, state),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
