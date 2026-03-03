from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json


@dataclass(frozen=True)
class TokenPayload:
    user_id: str
    role: str
    issued_at: datetime
    expires_at: datetime


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(text: str) -> bytes:
    padding = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _sign(data: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).digest()
    return _b64_encode(digest)


def issue_token(
    user_id: str,
    role: str,
    issued_at: datetime,
    secret: str,
    ttl_seconds: int = 3600,
) -> str:
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)

    payload = {
        "user_id": user_id,
        "role": role,
        "issued_at": issued_at.isoformat(),
        "expires_at": (issued_at + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    payload_text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_token = _b64_encode(payload_text.encode("utf-8"))
    signature = _sign(payload_token, secret)
    return f"{payload_token}.{signature}"


def verify_token(token: str, at: datetime, secret: str) -> tuple[bool, TokenPayload | None]:
    parts = token.split(".")
    if len(parts) != 2:
        return False, None

    payload_token, signature = parts
    expected = _sign(payload_token, secret)
    if not hmac.compare_digest(signature, expected):
        return False, None

    try:
        payload_raw = json.loads(_b64_decode(payload_token).decode("utf-8"))
        issued_at = datetime.fromisoformat(payload_raw["issued_at"])
        expires_at = datetime.fromisoformat(payload_raw["expires_at"])
    except Exception:
        return False, None

    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)

    if at >= expires_at:
        return False, None

    payload = TokenPayload(
        user_id=str(payload_raw["user_id"]),
        role=str(payload_raw["role"]),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    return True, payload
