#!/usr/bin/env python3
"""Submit decode_demo result artifacts to the Python runtime inference-results endpoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple
from urllib import error, request


RESULT_SCHEMA = "rk_decode_demo_result/v1"
BATCH_SCHEMA = "rk_decode_demo_batch_result/v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-url", required=True, help="Runtime base URL, for example http://127.0.0.1:18080")
    parser.add_argument("--input", required=True, help="Single result JSON or batch result summary JSON")
    parser.add_argument("--token", default="", help="Bearer token used to call the runtime")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_output_path(input_path: Path, raw_output_path: str) -> Path:
    candidate = Path(raw_output_path.strip())
    if candidate.is_absolute():
        return candidate

    search_roots = [
        Path.cwd(),
        input_path.parent,
        input_path.parent.parent,
    ]
    if len(input_path.parents) >= 3:
        search_roots.append(input_path.parents[2])
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return (input_path.parent / candidate).resolve()


def collect_payloads(input_path: Path) -> List[Tuple[Path, dict]]:
    document = load_json(input_path)
    schema_version = str(document.get("schema_version", "")).strip()
    if schema_version == RESULT_SCHEMA:
        return [(input_path, document)]
    if schema_version != BATCH_SCHEMA:
        raise ValueError(f"unsupported schema_version: {schema_version or '<missing>'}")

    payloads: List[Tuple[Path, dict]] = []
    for item in list(document.get("items", [])):
        if not isinstance(item, dict):
            continue
        output_path = resolve_output_path(input_path, str(item.get("output_path", "")))
        if not output_path.exists():
            raise FileNotFoundError(f"referenced result file not found: {output_path}")
        payload = load_json(output_path)
        payloads.append((output_path, payload))
    return payloads


def submit_payload(runtime_url: str, token: str, payload: dict, timeout: float) -> Tuple[int, dict]:
    endpoint = runtime_url.rstrip("/") + "/api/v1/inference/results"
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url=endpoint, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> int:
    args = parse_args()
    payloads = collect_payloads(Path(args.input).resolve())
    if not payloads:
        print("submitted_count=0")
        print("failed_count=0")
        return 0

    submitted = 0
    failed = 0
    for index, (path, payload) in enumerate(payloads):
        status_code, response = submit_payload(args.runtime_url, args.token, payload, args.timeout)
        device_id = str(payload.get("workload", {}).get("device_id", ""))
        success = 200 <= status_code < 300 and bool(response.get("success", False))
        if success:
            submitted += 1
        else:
            failed += 1
        response_data = response.get("data", {}) if isinstance(response, dict) else {}
        print(f"submit_index={index}")
        print(f"submit_path={path}")
        print(f"submit_device_id={device_id}")
        print(f"submit_http_status={status_code}")
        print(f"submit_success={'true' if success else 'false'}")
        if isinstance(response_data, dict) and "id" in response_data:
            print(f"submit_result_id={response_data['id']}")
        if not success:
            print(f"submit_response={json.dumps(response, ensure_ascii=True, sort_keys=True)}")

    print(f"submitted_count={submitted}")
    print(f"failed_count={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
