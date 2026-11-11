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
            payload = response.read(5 * 1024 * 1024 + 1)
        if len(payload) > 5 * 1024 * 1024:
            raise ValueError("Runtime response exceeds the example client bound")
        value = json.loads(payload)
        if not value.get("ok"):
            # No automatic retry: inspect the original approval, package or Run.
            raise RuntimeError(json.dumps(value.get("error"), ensure_ascii=False))
        return value["data"]

    def require_features(self, required):
        """Check advertised wire support; this grants no data or execution access."""
        if not isinstance(required, list) or any(
            not isinstance(item, str) for item in required
        ):
            raise ValueError("Host requirements must be a list of feature names")
        contract = self.request().get("contract")
        if (
            not isinstance(contract, dict)
            or contract.get("schema") != "apeir.studio-ui/v1"
        ):
            raise ValueError("Host does not advertise this Studio UI contract")
        supported = contract.get("features")
        if not isinstance(supported, list) or any(
            not isinstance(item, str) for item in supported
        ):
            raise ValueError("Host feature list is invalid")
        if set(required) - set(supported):
            raise ValueError("Host lacks required Studio features")
        return contract

    def review(self, path):
        raw = Path(path).read_bytes()
        if len(raw) > 128 * 1024:
            raise ValueError("Manifest exceeds 128 KiB")
        source = raw.decode("utf-8")
        manifest = json.loads(source)
        required = (
            manifest.get("metadata", {}).get("apeir_studio", {}).get("requires", [])
        )
        if required:
            self.require_features(required)
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

    def read_allowed_data(
        self, component_type, expected_digest, source="runtime.status"
    ):
        return self.request(
            "/data",
            params={
                "component_type": component_type,
                "expected_digest": expected_digest,
                "source": source,
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
            "contract",
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
    parser.add_argument("--extension-id")
    parser.add_argument(
        "--source",
        choices=["runtime.status", "workflow.summary"],
        default=None,
    )
    args = parser.parse_args()
    host = StudioHost(args.endpoint, os.environ.get("NOUS_API_TOKEN", ""))
    if args.command == "contract":
        result = host.require_features([])
    elif args.command == "list":
        result = host.request()
    elif args.command == "review":
        _, result = host.review(args.manifest)
    elif args.command == "install":
        result = host.install(args.manifest)
    else:
        extension_id = (
            args.extension_id
            or json.loads(Path(args.manifest).read_text(encoding="utf-8"))[
                "extension_id"
            ]
        )
        record = next(
            (
                item
                for item in host.request()["extensions"]
                if item["extension_id"] == extension_id
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
            result = (
                reader(
                    item["type"],
                    record["digest"],
                    args.source
                    or next(
                        source
                        for source in item.get("subscriptions", [])
                        if source in {"runtime.status", "workflow.summary"}
                    ),
                )
                if args.command == "read"
                else reader(item["type"], record["digest"])
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None
