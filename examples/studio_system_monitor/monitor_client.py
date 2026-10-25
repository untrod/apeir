"""Standalone standard-library example of the public declarative Studio host API.

Copy this directory outside the APEIR checkout. It imports no Runtime internals.
A tool declaration is not a permission grant; mutations may wait for approval.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirected Runtime endpoints are not admitted")


class StudioHost:
    def __init__(self, endpoint, token):
        parts = urlsplit(endpoint)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or parts.scheme == "http"
            and parts.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError(
                "Use a local HTTP or an authenticated HTTPS Runtime origin"
            )
        if not token:
            raise ValueError("Provide the existing API token through NOUS_API_TOKEN")
        self.endpoint, self.token = endpoint.rstrip("/"), token
        self.opener = build_opener(NoRedirect())

    def request(self, path="", body=None, params=None):
        suffix = "?" + urlencode(params) if params else ""
        request = Request(
            self.endpoint + "/api/v1/studio/extensions" + path + suffix,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            payload = response.read(1048577)
        if len(payload) > 1048576:
            raise ValueError("Runtime response exceeds the example client bound")
        value = json.loads(payload)
        if not value.get("ok"):
            # No automatic retry: inspect the original approval, package or Run.
            raise RuntimeError(json.dumps(value.get("error"), ensure_ascii=False))
        return value["data"]

    def review(self, path):
        raw = Path(path).read_bytes()
        if len(raw) > 128 * 1024:
            raise ValueError("Manifest exceeds 128 KiB")
        source = raw.decode("utf-8")
        return source, self.request("/review", {"source_manifest": source})

    def install(self, path):
        source, review = self.review(path)
        return self.request(
            "/install",
            {
                "source_manifest": source,
                "expected_digest": review["digest"],
                "expected_previous_digest": review["previous_digest"],
            },
        )

    def configure(self, record, enabled):
        return self.request(
            "/configure",
            {
                "extension_id": record["extension_id"],
                "enabled": enabled,
                "expected_digest": record["digest"],
                "expected_version": record["version"],
            },
        )

    def remove(self, record):
        return self.request(
            "/remove",
            {
                "extension_id": record["extension_id"],
                "expected_digest": record["digest"],
                "expected_version": record["version"],
            },
        )

    def read_allowed_data(self, component_type, expected_digest):
        return self.request(
            "/data",
            params={
                "component_type": component_type,
                "expected_digest": expected_digest,
                "source": "runtime.status",
            },
        )

    def subscribe_allowed_events(self, component_type, expected_digest):
        # Bounded metadata snapshot from the existing EventBus; not a second stream.
        return self.request(
            "/events",
            params={
                "component_type": component_type,
                "expected_digest": expected_digest,
            },
        )

    def request_governed_action(self, component_type, expected_digest, original_key):
        return self.request(
            "/action",
            {
                "component_type": component_type,
                "expected_digest": expected_digest,
                "action": "workflow.run",
                "idempotency_key": original_key,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "list",
            "review",
            "install",
            "enable",
            "disable",
            "remove",
            "read",
            "events",
        ],
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8770")
    parser.add_argument(
        "--manifest", default=str(Path(__file__).with_name("nous.extension.json"))
    )
    parser.add_argument("--extension-id", default="examples/studio-system-monitor")
    args = parser.parse_args()
    host = StudioHost(args.endpoint, os.environ.get("NOUS_API_TOKEN", ""))
    if args.command == "list":
        result = host.request()
    elif args.command == "review":
        _, result = host.review(args.manifest)
    elif args.command == "install":
        result = host.install(args.manifest)
    else:
        record = next(
            (
                item
                for item in host.request()["extensions"]
                if item["extension_id"] == args.extension_id
            ),
            None,
        )
        if record is None:
            raise ValueError("Extension is not installed")
        if args.command in {"enable", "disable"}:
            result = host.configure(record, args.command == "enable")
        elif args.command == "remove":
            result = host.remove(record)
        else:
            item = next(
                item for item in record["contributions"] if item["kind"] == "panel"
            )
            reader = (
                host.read_allowed_data
                if args.command == "read"
                else host.subscribe_allowed_events
            )
            result = reader(item["type"], record["digest"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
