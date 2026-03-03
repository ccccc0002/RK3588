from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def send_webhook(task: object, timeout_seconds: float = 2.0) -> bool:
    payload = json.dumps(task.payload).encode("utf-8")
    req = Request(
        url=str(task.target_url),
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {task.bearer_token}",
            "Idempotency-Key": str(task.idempotency_key),
        },
    )

    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            return 200 <= int(resp.status) < 300
    except URLError:
        return False
