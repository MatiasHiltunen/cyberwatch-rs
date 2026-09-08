#!/usr/bin/env python3
"""Verify the authorized Azure live endpoint without exposing its credentials."""
import argparse
import base64
import datetime
import http.client
import json
from pathlib import Path
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--access-file", required=True, type=Path)
parser.add_argument("--output", type=Path)
parser.add_argument("--wait-seconds", type=int, default=600)
parser.add_argument("--enqueue-refresh", action="store_true", help="Also verify the real admin token by requesting one live refresh")
opts = parser.parse_args()
access = json.loads(opts.access_file.read_text(encoding="utf-8"))
base = access["url"].rstrip("/")
origin = urllib.parse.urlsplit(base)
if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
    raise SystemExit("The access file must name an HTTPS origin")
basic = "Basic " + base64.b64encode((access["readerUsername"] + ":" + access["readerPassword"]).encode()).decode()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Verification will not forward credentials through redirects")

opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
checks = []
class UnexpectedStatus(RuntimeError):
    def __init__(self, status, description):
        super().__init__(description)
        self.status = status

def get(path, expected=200, auth=True, method="GET", bearer=None, record=True, auth_header=None):
    headers = {"Accept-Encoding": "identity"}
    if auth:
        headers["Authorization"] = basic
    if bearer is not None:
        headers["Authorization"] = "Bearer " + bearer
    if auth_header is not None:
        headers["Authorization"] = auth_header
    request = urllib.request.Request(base + path, headers=headers, method=method)
    try:
        response = opener.open(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            raise RuntimeError("Verification response exceeds the size limit")
        if response.status != expected:
            raise UnexpectedStatus(response.status, f"{method} {path}: HTTP{response.status}, expected{expected}, response suppressed")
        if record:
            checks.append(f"{method} {path}: {expected}")
        return body, response.headers

deadline = time.monotonic() + opts.wait_seconds
while True:
    try:
        health = json.loads(get("/health", record=False)[0])
        if health.get("demo_mode") is not False or health.get("refresh_enabled") is not True:
            raise RuntimeError("Endpoint is not the requested live-feed mode")
        items = json.loads(get("/api/v1/items?limit=5", record=False)[0])
        if items.get("items"):
            break
    except (urllib.error.URLError, TimeoutError):
        pass
    except UnexpectedStatus as error:
        if error.status not in {502, 503, 504}:
            raise
    if time.monotonic() >= deadline:
        raise RuntimeError("Live endpoint did not become reachable and ingest records within the wait period")
    time.sleep(10)

get("/", expected=401, auth=False)
get("/", expected=401, auth_header="Basic " + base64.b64encode(b"cyberwatch:invalid-test-password").decode())
get("/api/v1/items", expected=401, auth=False)
get("/api/v1/refresh", expected=401, auth=False, method="POST")
get("/api/v1/refresh", expected=401, auth=False, method="POST", bearer="invalid-test-token")
if opts.enqueue_refresh:
    get("/api/v1/refresh", expected=202, auth=False, method="POST", bearer=access["adminToken"])
connection = http.client.HTTPConnection(origin.hostname, 80, timeout=5)
try:
    connection.request("GET", "/")
    response = connection.getresponse()
    if response.status != 301 or response.getheader("Location") != base + "/":
        raise RuntimeError("HTTP did not redirect to the exact HTTPS origin")
    checks.append("HTTP redirects to exact HTTPS origin: passed")
finally:
    connection.close()
for port in (22, 8080):
    try:
        with socket.create_connection((origin.hostname, port), timeout=2):
            raise RuntimeError(f"Unexpected publicly reachable TCP port {port}")
    except (TimeoutError, ConnectionRefusedError):
        checks.append(f"Public TCP {port} unreachable from verifier: passed")
page, headers = get("/")
if b"Cyberwatch" not in page or "default-src 'self'" not in headers.get("Content-Security-Policy", ""):
    raise RuntimeError("Dashboard content/security headers missing")
get("/ready")
get("/health")
get("/metrics")
stats = json.loads(get("/api/v1/stats")[0])
sources = json.loads(get("/api/v1/sources")[0])
refresh = json.loads(get("/api/v1/refresh/status")[0])
get("/api/v1/items?kind=invalid", expected=400)
get("/api/v1/does-not-exist", expected=404)
if any(str(item.get("id", "")).startswith("demo:") for item in items["items"]):
    raise RuntimeError("Demo records found in the live deployment")
report = {"recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "url": base, "status": "passed", "tls_certificate_validation": "passed", "checks": checks,
          "health": health, "stats": stats, "configured_sources": len(sources),
          "sources_with_errors": sum(bool(source.get("last_error")) for source in sources),
          "live_records_observed": len(items["items"]), "refresh_status": refresh}
if opts.output:
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    opts.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
