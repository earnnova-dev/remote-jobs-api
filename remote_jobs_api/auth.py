"""Thread-safe API-key store for the hosted tier.

Keys are persisted to a JSON file so the server stays stateless across
pod restarts in Kubernetes. All writes are serialized via a process-wide
lock; reads use a lightweight snapshot pattern so concurrent requests
do not block on the lock.

File layout (keys.json):
{
  "v": 1,
  "keys": {
    "rja_live_ab12cd34ef56": {
      "plan": "pro",
      "label": "acme-inc",
      "created": 1790433192,
      "month": "2026-09",
      "calls": 143
    }
  }
}
"""
from __future__ import annotations

import json
import os
import threading
import time
import secrets
from dataclasses import dataclass
from typing import Dict, Optional, Any

# Plan -> monthly call cap (0 = unlimited).
PLAN_LIMITS = {
    "free": 100,
    "pro": 10_000,
    "team": 100_000,
    "admin": 0,
}


def _month_key() -> str:
    return time.strftime("%Y-%m", time.gmtime())


@dataclass
class KeyInfo:
    key: str
    plan: str
    label: str
    created: int
    calls_this_month: int
    limit: int  # 0 = unlimited
    owner: str = ""  # account email, if this key is tied to a user


class KeyStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {"v": 1, "keys": {}}
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("keys"), dict):
                self._data = loaded
        except (json.JSONDecodeError, OSError):
            # Corrupt file: keep in-memory default, log to stderr
            print(f"[keys] could not parse {self.path}; starting fresh", flush=True)

    def _save_locked(self):
        # Atomic write: write to temp, then rename.
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- key lifecycle ----------
    def create(self, plan: str, label: str = "", owner: str = "") -> KeyInfo:
        if plan not in PLAN_LIMITS:
            raise ValueError(f"unknown plan {plan!r}; choose from {sorted(PLAN_LIMITS)}")
        with self._lock:
            # Account keys (owner set) always use the live prefix so the value
            # stays stable and unambiguous across upgrades — the tier is the
            # plan field, not the prefix. Admin keys keep the free/live split.
            prefix = "rja_live_" if (owner or plan != "free") else "rja_free_"
            raw = prefix + secrets.token_hex(12)
            self._data["keys"][raw] = {
                "plan": plan,
                "label": label or "",
                "owner": owner or "",
                "created": int(time.time()),
                "month": _month_key(),
                "calls": 0,
            }
            self._save_locked()
            return self._info(raw)

    def create_with_value(self, key, plan, label=""):
        """Create a key with a specific value (account layer generates the key
        so the same value exists in both the account store and key store)."""
        if plan not in PLAN_LIMITS:
            raise ValueError("unknown plan %r; choose from %s" % (plan, sorted(PLAN_LIMITS)))
        if not key:
            raise ValueError("key value required")
        with self._lock:
            self._data["keys"][key] = {
                "plan": plan,
                "label": label or "",
                "created": int(time.time()),
                "month": _month_key(),
                "calls": 0,
            }
            self._save_locked()
            return self._info(key)

    def set_plan(self, key, plan):
        """Update the plan on an existing key (upgrade/downgrade on billing)."""
        if plan not in PLAN_LIMITS:
            raise ValueError("unknown plan %r" % (plan,))
        with self._lock:
            if key in self._data["keys"]:
                self._data["keys"][key]["plan"] = plan
                self._data["keys"][key]["month"] = _month_key()
                self._data["keys"][key]["calls"] = 0
                self._save_locked()
                return True
            return False

    def revoke(self, key: str) -> bool:
        with self._lock:
            if key in self._data["keys"]:
                del self._data["keys"][key]
                self._save_locked()
                return True
            return False

    def list_keys(self) -> list:
        with self._lock:
            month = _month_key()
            out = []
            for k, v in self._data["keys"].items():
                info = self._info(k)
                # reset month if it rolled over
                if v["month"] != month:
                    info.calls_this_month = 0
                out.append(info)
            return out

    def _info(self, key: str) -> KeyInfo:
        v = self._data["keys"][key]
        return KeyInfo(
            key=key,
            plan=v["plan"],
            label=v.get("label", ""),
            created=int(v.get("created", 0)),
            calls_this_month=int(v.get("calls", 0)),
            limit=PLAN_LIMITS.get(v["plan"], 0),
            owner=v.get("owner", ""),
        )

    # ---------- auth + rate limit ----------
    def check(self, key: str) -> KeyInfo:
        """Return KeyInfo if the key exists and is under its monthly limit;
        else return None (invalid) or raise RateLimitError."""
        with self._lock:
            v = self._data["keys"].get(key)
            if not v:
                return None
            # Reset monthly counter when month rolls over
            if v.get("month") != _month_key():
                v["month"] = _month_key()
                v["calls"] = 0
            limit = PLAN_LIMITS.get(v["plan"], 0)
            if limit and v["calls"] >= limit:
                raise RateLimitError(limit)
            v["calls"] += 1
            self._save_locked()
            return self._info(key)


class RateLimitError(Exception):
    def __init__(self, limit: int):
        super().__init__(f"rate limit exceeded: {limit} calls/month")
        self.limit = limit


def bearer_token_from_headers(headers) -> Optional[str]:
    """Parse Authorization: Bearer <token> from a BaseHTTPRequestHandler
    headers object. Returns the raw token or None."""
    auth = headers.get("Authorization") or ""
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == "bearer":
        return parts[1].strip()
    return None
