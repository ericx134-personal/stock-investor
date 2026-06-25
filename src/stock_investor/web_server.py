from __future__ import annotations

import argparse
import json
import os
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
        self.progress = 0
        self.progress_file: Path | None = None

    def snapshot(self) -> dict[str, str | int]:
        with self.lock:
            status = self.status
            message = self.message
            progress = self.progress
            progress_file = self.progress_file
        if status == "running" and progress_file and progress_file.exists():
            try:
                payload = json.loads(progress_file.read_text())
                progress = int(payload.get("progress", progress))
                message = str(payload.get("message", message))
            except (OSError, ValueError, TypeError):
                pass
        return {"status": status, "message": message, "progress": progress}

    def start(self, command: list[str], cwd: Path) -> bool:
        with self.lock:
            if self.status == "running":
                return False
            self.status = "running"
            self.message = "refresh started"
            self.progress = 1
            self.progress_file = cwd / "data" / "private" / ".refresh-progress.json"
            try:
                self.progress_file.unlink()
            except OSError:
                pass
        thread = threading.Thread(
            target=self._run,
            args=(command, cwd),
            name="stock-investor-refresh",
            daemon=True,
        )
        thread.start()
        return True

    def _run(self, command: list[str], cwd: Path) -> None:
        with self.lock:
            progress_file = self.progress_file
        env = os.environ.copy()
        if progress_file:
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            env["STOCK_INVESTOR_REFRESH_PROGRESS"] = str(progress_file)
        try:
            subprocess.run(command, cwd=cwd, check=True, env=env)
        except Exception as error:  # pragma: no cover - defensive server guard
            with self.lock:
                self.status = "failed"
                self.message = str(error)
                self.progress = 100
            return
        with self.lock:
            self.status = "succeeded"
            self.message = "refresh complete"
            self.progress = 100


def make_handler(root: Path, refresh_script: Path, state: RefreshState):
    class StockInvestorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            if self.path != "/api/refresh":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            started = state.start([str(refresh_script)], root)
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

        def _send_json(self, payload: dict[str, str | int]) -> None:
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
