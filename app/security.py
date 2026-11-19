"""Signed session cookies, constant-time credential checks and a login rate limiter."""
import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str, secret: str) -> str:
    return _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def sign(payload: dict, secret: str, ttl_seconds: int) -> str:
    body = _b64e(json.dumps({**payload, "exp": int(time.time()) + ttl_seconds}, separators=(",", ":")).encode())
    return f"{body}.{_mac(body, secret)}"


def verify(token: str, secret: str):
    """Return the payload dict, or None if the token is malformed, forged or expired."""
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _mac(body, secret)):
            return None
        payload = json.loads(_b64d(body))
        if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class LoginLimiter:
    """Blocks a key after `max_fails` failures within `window` seconds (in-memory, per process)."""

    def __init__(self, max_fails: int = 8, window: int = 600):
        self.max_fails, self.window = max_fails, window
        self._fails = defaultdict(deque)

    def _prune(self, key):
        q, cutoff = self._fails[key], time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, *keys) -> bool:
        return any(len(self._prune(k)) >= self.max_fails for k in keys)

    def fail(self, *keys) -> None:
        for k in keys:
            self._prune(k).append(time.monotonic())

    def reset(self, *keys) -> None:
        for k in keys:
            self._fails.pop(k, None)


limiter = LoginLimiter()
