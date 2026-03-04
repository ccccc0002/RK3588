from __future__ import annotations


def ok_payload(data: dict, meta: dict | None = None) -> dict:
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def error_payload(code: str, message: str, details: dict | None = None, meta: dict | None = None) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": meta or {},
    }
