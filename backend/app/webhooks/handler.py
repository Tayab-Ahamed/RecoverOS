"""Webhook ingestion.

Order matters and is enforced here: verify the signature over the raw body,
then deduplicate by provider event id, and only then let the verifier touch a
case. An unsigned or replayed event must never reach domain logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.integrations.idempotency import IdempotencyStore
from app.integrations.signature import verify_signature
from app.services.verifier import OutcomeVerifier


class WebhookRejected(Exception):
    pass


@dataclass
class WebhookResult:
    accepted: bool
    reason: str
    case_id: str | None = None
    event_type: str | None = None


class WebhookHandler:
    def __init__(
        self,
        secret: str,
        verifier: OutcomeVerifier,
        idempotency: IdempotencyStore,
        case_lookup,
    ) -> None:
        self.secret = secret
        self.verifier = verifier
        self.idempotency = idempotency
        # Callable mapping a provider reference id to a RecoveryCase, so the
        # handler does not depend on a concrete repository.
        self.case_lookup = case_lookup
        self.last_case = None

    def handle(
        self,
        raw_body: bytes,
        signature: str,
        event_id: str,
    ) -> WebhookResult:
        if not verify_signature(raw_body, signature, self.secret):
            # Returned rather than raised so the endpoint can answer 400 without
            # leaking whether the event id was recognised.
            return WebhookResult(False, "invalid signature")

        if not self.idempotency.claim(event_id):
            return WebhookResult(False, "duplicate event ignored")

        try:
            body = json.loads(raw_body.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return WebhookResult(False, f"unparseable body: {exc}")

        event_type = body.get("event")
        if not event_type:
            return WebhookResult(False, "missing event field")

        reference_id, payment_id, amount, captured = self._extract(body, event_type)
        if reference_id is None:
            return WebhookResult(False, "no resolvable case reference", event_type=event_type)

        case = self.case_lookup(reference_id)
        if case is None:
            return WebhookResult(False, "unknown case", event_type=event_type)

        self.last_case = case
        self.verifier.verify(
            case=case,
            event_type=event_type,
            external_event_id=event_id,
            payment_id=payment_id or "",
            amount_paise=amount or 0,
            captured=bool(captured),
        )
        return WebhookResult(True, "processed", case_id=case.id, event_type=event_type)

    @staticmethod
    def _extract(body: dict, event_type: str):
        payload = body.get("payload", {})
        link = payload.get("payment_link", {}).get("entity", {})
        payment = payload.get("payment", {}).get("entity", {})

        reference_id = link.get("reference_id")
        if not reference_id:
            # A failed attempt on a link arrives as a payment event, so the
            # association is carried in notes. This is exactly the linkage that
            # remains UNVERIFIED against a live account.
            reference_id = (payment.get("notes") or {}).get("reference_id")

        amount = payment.get("amount") or link.get("amount")
        captured = payment.get("status") == "captured" or (
            event_type == "payment_link.paid" and link.get("status") == "paid"
        )
        return reference_id, payment.get("id"), amount, captured
