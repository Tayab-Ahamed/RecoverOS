"""Live Razorpay adapter (Phase 3b).

Uses urllib from the standard library rather than a third-party HTTP client so
that the package has no hard runtime dependency for this path. Only the two
capabilities defined by the provider port are implemented; the API surface is
kept deliberately small.

VERIFIED against Razorpay documentation: Payment Links accept amount in paise,
currency, reference_id, description, customer{}, notify{}, reminder_enable and
notes, and return id, short_url and status.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request

from app.domain.money import Money
from app.integrations.provider import (
    PaymentLinkRequest,
    PaymentLinkResponse,
    ProviderError,
)

API_BASE = "https://api.razorpay.com/v1"


class RazorpayProvider:
    name = "razorpay"

    def __init__(self, key_id: str, key_secret: str, timeout: float = 15.0) -> None:
        if not key_id or not key_secret:
            raise ProviderError("Razorpay credentials are required")
        self._auth = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
        self.timeout = timeout


    def _request(self, method: str, path: str, body: dict | None = None, _retries: int = 2) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{API_BASE}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Basic {self._auth}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            # Authoritative error — never retry.
            detail = exc.read().decode(errors="replace")[:500]
            raise ProviderError(f"Razorpay {method} {path} -> {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            # Network-level error (timeout, DNS failure). Retry up to _retries times.
            if _retries > 0:
                time.sleep(1)
                return self._request(method, path, body, _retries - 1)
            raise ProviderError(f"Razorpay unreachable after retries: {exc.reason}") from exc

    def create_payment_link(self, req: PaymentLinkRequest) -> PaymentLinkResponse:
        payload = {
            "amount": req.amount.paise,
            "currency": req.amount.currency,
            "accept_partial": False,
            "reference_id": req.reference_id,
            "description": req.description,
            "customer": {
                "name": req.customer_name,
                "email": req.customer_email,
                "contact": req.customer_contact,
            },
            "notify": {"email": req.notify_email, "sms": req.notify_sms},
            "reminder_enable": req.reminder_enable,
            "notes": req.notes or {},
        }
        if req.expire_by:
            payload["expire_by"] = req.expire_by
        raw = self._request("POST", "/payment_links", payload)
        return PaymentLinkResponse(
            id=raw["id"],
            short_url=raw["short_url"],
            status=raw["status"],
            amount=Money(int(raw["amount"])),
            reference_id=raw.get("reference_id", req.reference_id),
        )

    def fetch_payment_link(self, link_id: str) -> PaymentLinkResponse:
        raw = self._request("GET", f"/payment_links/{link_id}")
        return PaymentLinkResponse(
            id=raw["id"],
            short_url=raw["short_url"],
            status=raw["status"],
            amount=Money(int(raw["amount"])),
            reference_id=raw.get("reference_id", ""),
        )
