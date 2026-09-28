"""User accounts + sessions for the hosted SaaS tier.

Stdlib-only. Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user salt
(100k iterations). Sessions are server-side, revocable bearer tokens stored in
the same JSON file as the users, so everything survives pod restarts and no
cookie jar is required (works equally well for browsers and API clients).

File layout (accounts.json):
{
  "v": 1,
  "users": {
    "user@example.com": {
      "salt":      "hex",
      "pass_hash": "hex",
      "plan":      "free" | "pro" | "team",
      "api_key":   "rja_live_..." | "",
      "stripe_customer": "cus_..." | "",
      "stripe_sub":      "sub_..." | "",
      "sub_status":  "none" | "active" | "trialing" | "past_due" | "canceled",
      "created":   1790433192,
      "month":     "2026-09",
      "calls":     14
    }
  },
  "sessions": {
    "hex_token": {"email": "user@example.com", "created": 123, "expires": 123}
  },
  "resets": {
    "sha256(token)": {"email": "user@example.com", "expires": 123, "used": false, "attempts": 0}
  }
}
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from typing import Dict, Any, Optional

PBKDF2_ITERATIONS = 100_000
SESSION_TTL = 60 * 60 * 24 * 30  # 30 days
RESET_TTL = 60 * 30  # 30 minutes
RESET_MAX_ATTEMPTS = 5  # max password set attempts per token
RESET_MAX_REQUESTS_PER_HOUR = 3  # max reset requests per email per hour


def _now() -> int:
    return int(time.time())


def _month_key() -> str:
    return time.strftime("%Y-%m", time.gmtime())


def hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return dk.hex()


def verify_password(password: str, salt_hex: str, expected_hex: str) -> bool:
    # secrets.compare_digest on the hex string avoids timing side channels.
    return secrets.compare_digest(hash_password(password, salt_hex), expected_hex)


class UserStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {"v": 1, "users": {}, "sessions": {}, "resets": {}}
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("users"), dict):
                loaded.setdefault("sessions", {})
                loaded.setdefault("resets", {})
                self._data = loaded
        except (json.JSONDecodeError, OSError):
            print("[accounts] could not parse accounts file; starting fresh", flush=True)

    def _save_locked(self):
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- users ----------
    def exists(self, email: str) -> bool:
        with self._lock:
            return email.lower() in self._data["users"]

    def register(self, email: str, password: str, plan: str = "free", api_key: str = "") -> Dict[str, Any]:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("invalid email")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        with self._lock:
            if email in self._data["users"]:
                raise ValueError("user already exists")
            salt = secrets.token_hex(16)
            rec = {
                "salt": salt,
                "pass_hash": hash_password(password, salt),
                "plan": plan,
                "api_key": api_key or "",
                "stripe_customer": "",
                "stripe_sub": "",
                "sub_status": "none",
                "created": _now(),
                "month": _month_key(),
                "calls": 0,
            }
            self._data["users"][email] = rec
            self._save_locked()
            return self.public(email)

    def verify(self, email: str, password: str) -> Optional[str]:
        """Return api_key if the credentials are valid, else None."""
        email = email.strip().lower()
        with self._lock:
            rec = self._data["users"].get(email)
            if not rec:
                return None
            if verify_password(password, rec["salt"], rec["pass_hash"]):
                return rec.get("api_key", "")
            return None

    def get(self, email: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._data["users"].get(email.strip().lower())
            return dict(rec) if rec else None

    def set_plan(self, email: str, plan: str, sub_status: str = "none"):
        with self._lock:
            rec = self._data["users"].get(email.strip().lower())
            if rec:
                rec["plan"] = plan
                rec["sub_status"] = sub_status
                self._save_locked()

    def set_api_key(self, email: str, api_key: str):
        with self._lock:
            rec = self._data["users"].get(email.strip().lower())
            if rec:
                rec["api_key"] = api_key
                self._save_locked()

    def set_stripe(self, email: str, customer: str = "", sub: str = "", status: str = ""):
        with self._lock:
            rec = self._data["users"].get(email.strip().lower())
            if rec:
                if customer:
                    rec["stripe_customer"] = customer
                if sub:
                    rec["stripe_sub"] = sub
                if status:
                    rec["sub_status"] = status
                self._save_locked()

    def public(self, email: str) -> Dict[str, Any]:
        """User record without the password material."""
        rec = self.get(email)
        if not rec:
            return {}
        return {
            "email": email,
            "plan": rec.get("plan", "free"),
            "api_key": rec.get("api_key", ""),
            "sub_status": rec.get("sub_status", "none"),
            "calls_this_month": rec.get("calls", 0),
            "created": rec.get("created", 0),
        }

    def list_emails(self) -> list:
        with self._lock:
            return list(self._data["users"].keys())

    # ---------- password reset ----------
    def set_password(self, email: str, password: str) -> None:
        """Directly set a password (used by the reset flow and provisioning)."""
        email = email.strip().lower()
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        with self._lock:
            rec = self._data["users"].get(email)
            if not rec:
                raise ValueError("user not found")
            rec["salt"] = secrets.token_hex(16)
            rec["pass_hash"] = hash_password(password, rec["salt"])
            self._save_locked()

    def revoke_sessions_for(self, email: str) -> int:
        """Revoke all active sessions for a user (used after password change)."""
        email = email.strip().lower()
        now = _now()
        with self._lock:
            removed = 0
            for tok in list(self._data["sessions"].keys()):
                s = self._data["sessions"][tok]
                if s.get("email") == email and s.get("expires", 0) > now:
                    del self._data["sessions"][tok]
                    removed += 1
            self._save_locked()
            return removed

    def _reset_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _gc_resets_locked(self) -> None:
        now = _now()
        for h in list(self._data["resets"].keys()):
            r = self._data["resets"][h]
            if r.get("expires", 0) < now:
                del self._data["resets"][h]

    def create_reset_token(self, email: str) -> Optional[str]:
        """Return a one-time reset token, or None if the user doesn't exist / is rate-limited.

        The token is only stored as a SHA-256 hash. Returns the raw token so the
        caller can deliver it (via email, or locally in dev mode).
        """
        email = email.strip().lower()
        with self._lock:
            if email not in self._data["users"]:
                return None
            # Rate limit: max N fresh requests per email per hour.
            now = _now()
            fresh = 0
            for h, r in self._data["resets"].items():
                if r.get("email") == email and r.get("created", 0) > now - 3600:
                    fresh += 1
            if fresh >= RESET_MAX_REQUESTS_PER_HOUR:
                return None
            # Invalidate any prior (unexpired) tokens for this email.
            for h, r in list(self._data["resets"].items()):
                if r.get("email") == email and not r.get("used") and r.get("expires", 0) > now:
                    r["used"] = True
            token = secrets.token_urlsafe(32)
            self._data["resets"][self._reset_hash(token)] = {
                "email": email,
                "created": now,
                "expires": now + RESET_TTL,
                "used": False,
                "attempts": 0,
            }
            self._save_locked()
            return token

    def validate_reset_token(self, token: str) -> Optional[str]:
        """Return the email the token belongs to if valid, else None."""
        if not token:
            return None
        with self._lock:
            self._gc_resets_locked()
            r = self._data["resets"].get(self._reset_hash(token))
            if not r:
                return None
            if r.get("used") or r.get("expires", 0) < _now():
                return None
            return r.get("email")

    def consume_reset_token(self, token: str, new_password: str) -> Optional[str]:
        """Validate the token, set the password, mark used, revoke sessions.

        Returns the email on success, or None if the token is invalid/used/expired
        or attempts are exhausted. Raises ValueError on a bad password.
        """
        if not token:
            return None
        with self._lock:
            self._gc_resets_locked()
            key = self._reset_hash(token)
            r = self._data["resets"].get(key)
            if not r or r.get("used"):
                return None
            if r.get("expires", 0) < _now():
                return None
            if r.get("attempts", 0) >= RESET_MAX_ATTEMPTS:
                return None
            email = r["email"]
            # Set the password (reuses the lock, which is reentrant).
            rec = self._data["users"].get(email)
            if not rec:
                return None
            if len(new_password) < 8:
                raise ValueError("password must be at least 8 characters")
            rec["salt"] = secrets.token_hex(16)
            rec["pass_hash"] = hash_password(new_password, rec["salt"])
            # Mark token used + revoke all sessions for the user.
            r["used"] = True
            r["attempts"] += 1
            now = _now()
            for tok in list(self._data["sessions"].keys()):
                if self._data["sessions"][tok].get("email") == email and self._data["sessions"][tok].get("expires", 0) > now:
                    del self._data["sessions"][tok]
            self._save_locked()
            return email


    # ---------- sessions ----------
    def create_session(self, email: str) -> str:
        token = secrets.token_hex(32)
        with self._lock:
            self._gc_sessions()
            self._data["sessions"][token] = {
                "email": email.strip().lower(),
                "created": _now(),
                "expires": _now() + SESSION_TTL,
            }
            self._save_locked()
            return token

    def session_email(self, token: str) -> Optional[str]:
        if not token:
            return None
        with self._lock:
            s = self._data["sessions"].get(token)
            if not s:
                return None
            if s.get("expires", 0) < _now():
                del self._data["sessions"][token]
                self._save_locked()
                return None
            return s.get("email")

    def delete_session(self, token: str):
        if not token:
            return
        with self._lock:
            if token in self._data["sessions"]:
                del self._data["sessions"][token]
                self._save_locked()

    def _gc_sessions(self):
        now = _now()
        for t in list(self._data["sessions"].keys()):
            if self._data["sessions"][t].get("expires", 0) < now:
                del self._data["sessions"][t]


def session_token_from_headers(headers) -> Optional[str]:
    """Accept a session as `Authorization: Bearer <token>` or `?token=***"""
    auth = headers.get("Authorization") or ""
    parts = auth.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == "bearer":
        return parts[1].strip()
    return None
