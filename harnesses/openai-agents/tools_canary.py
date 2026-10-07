"""Canary tools, identical across harnesses (see compat/CONTRACT.md)."""
import json
import os

with open(os.environ.get("CANARY_FIXTURE", "/app/canary.json")) as _f:
    _TABLE = {k.lower(): v for k, v in json.load(_f)["lookup_table"].items()}


def lookup(key: str) -> int | str:
    return _TABLE.get(key.strip().lower(), f"error: unknown key '{key}'")


def add(a: int, b: int) -> int:
    return a + b


SYSTEM_PROMPT = (
    "You are a precise assistant. Always use the provided tools for lookups and arithmetic; never guess numbers."
)
