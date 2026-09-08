#!/usr/bin/env python3
"""Exercise a disposable demo process, or an explicitly local demo container."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message):
    if not condition:
        raise RuntimeError(str(message))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("smoke tests never follow redirects")


def check(base: str) -> dict:
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("smoke target must be an HTTP loopback origin")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    checks = []

    def request(path, expected=200, method="GET"):
        req = urllib.request.Request(base.rstrip("/") + path, method=method)
        try:
            response = opener.open(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(1024 * 1024)
            require(response.status == expected, (path, response.status, body[:200]))
            require(response.headers.get("X-Content-Type-Options") == "nosniff", path)
            require("default-src 'self'" in response.headers.get("Content-Security-Policy", ""), path)
            checks.append(f"{method} {path}: {expected}")
            return body

    health = json.loads(request("/health"))
    require(health.get("demo_mode") is True, "use a disposable DEMO_MODE=true instance")
    require(health.get("refresh_enabled") is False, "source refresh must be disabled")
    request("/ready")
    require(b"Cyberwatch" in request("/"), "dashboard missing")
    page = json.loads(request("/api/v1/items?limit=1"))
    require(len(page["items"]) == 1, "demo seed missing")
    first = page["items"][0]
    require(page["next_cursor"], "demo should exercise pagination")
    next_page = json.loads(request("/api/v1/items?limit=1&cursor=" + urllib.parse.quote(page["next_cursor"])))
    require(first["id"] != next_page["items"][0]["id"], "cursor repeated an item")
    request("/api/v1/items/" + urllib.parse.quote(first["id"], safe=""))
    filtered = json.loads(request("/api/v1/items?kind=cve"))
    require(filtered["items"] and all(item["kind"] == "cve" for item in filtered["items"]), "kind filter failed")
    request("/api/v1/stats")
    request("/api/v1/sources")
    request("/api/v1/items?kind=invalid", 400)
    request("/api/v1/items?cursor=invalid", 400)
    request("/api/v1/does-not-exist", 404)
    request("/api/v1/refresh", 503, "POST")
    metrics = request("/metrics").decode()
    require("cyberwatch_http_requests_total" in metrics, "HTTP counter missing")
    return {"status": "passed", "checks": checks, "health": health}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--binary", type=Path)
    target.add_argument("--url")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.url:
        result = check(args.url)
    else:
        binary = args.binary.resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="cyberwatch-smoke-") as temp:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            # Do not inherit ingestion credentials/configuration or load a user's .env.
            env = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "LD_LIBRARY_PATH"}}
            env.update(BIND_ADDRESS=f"127.0.0.1:{port}", DATABASE_PATH=str(Path(temp) / "demo.db"),
                       WEB_DIR=str(ROOT / "web"), DEMO_MODE="true", REFRESH_ENABLED="false",
                       ADMIN_TOKEN=secrets.token_urlsafe(32), RUST_LOG="warn")
            with (Path(temp) / "server.log").open("w+") as log:
                process = subprocess.Popen([str(binary)], cwd=temp, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 30
                    while True:
                        if process.poll() is not None:
                            log.seek(0)
                            raise RuntimeError("server exited: " + log.read())
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                                break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise RuntimeError("server did not start within 30 seconds")
                            time.sleep(0.1)
                    result = check(f"http://127.0.0.1:{port}")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    report = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
