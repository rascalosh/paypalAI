"""PayPal Invoicing v2 client.

APIMatic's paypal-server-sdk has no Invoicing controller, so invoice calls go
through httpx; the SDK is used only to fetch the OAuth client-credentials token
(with a plain httpx fallback). Every call logs (action, invoice_id, debug_id, status).
"""
import logging
import time
from decimal import ROUND_HALF_UP, Decimal

import httpx
from paypalserversdk.configuration import Environment
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app.config import settings

log = logging.getLogger("paycord.paypal")

CENT = Decimal("0.01")


class PayPalError(Exception):
    def __init__(self, status: int, debug_id: str | None, body: str):
        super().__init__(f"PayPal {status} debug_id={debug_id}: {body}")
        self.status = status
        self.debug_id = debug_id
        self.body = body


def money(value: Decimal) -> str:
    if not isinstance(value, Decimal):
        raise TypeError(f"money must be Decimal, got {type(value).__name__}")
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


class PayPalClient:
    def __init__(self):
        self._http = httpx.Client(base_url=settings.paypal_base_url, timeout=20)
        self._token: str | None = None
        self._expires_at = 0.0

    # --- auth -------------------------------------------------------------
    def _fetch_token_sdk(self) -> tuple[str, int]:
        sdk = PaypalServersdkClient(
            environment=Environment.SANDBOX if settings.paypal_env != "live" else Environment.PRODUCTION,
            client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                o_auth_client_id=settings.paypal_client_id,
                o_auth_client_secret=settings.paypal_client_secret,
            ),
        )
        tok = sdk.oauth_2.fetch_token()
        return tok.access_token, int(tok.expires_in or 300)

    def _fetch_token_httpx(self) -> tuple[str, int]:
        r = self._http.post(
            "/v1/oauth2/token",
            auth=(settings.paypal_client_id, settings.paypal_client_secret),
            data={"grant_type": "client_credentials"},
        )
        log.info("paypal action=oauth_token invoice_id=- status=%s debug_id=%s",
                 r.status_code, r.headers.get("PayPal-Debug-Id"))
        if r.status_code >= 400:
            raise PayPalError(r.status_code, r.headers.get("PayPal-Debug-Id"), r.text)
        j = r.json()
        return j["access_token"], int(j.get("expires_in", 300))

    def _get_token(self, force: bool = False) -> str:
        if not force and self._token and time.time() < self._expires_at - 60:
            return self._token
        try:
            token, ttl = self._fetch_token_sdk()
            log.info("paypal action=oauth_token via=apimatic_sdk")
        except Exception as e:  # SDK API drift or auth error: retry via raw httpx
            log.warning("paypal action=oauth_token sdk_failed=%r, falling back to httpx", e)
            token, ttl = self._fetch_token_httpx()
        self._token, self._expires_at = token, time.time() + ttl
        return token

    # --- transport --------------------------------------------------------
    def _request(self, action: str, method: str, path: str,
                 invoice_id: str | None = None, json: dict | None = None) -> httpx.Response:
        for attempt in (1, 2):
            r = self._http.request(
                method, path, json=json,
                headers={
                    "Authorization": f"Bearer {self._get_token(force=attempt == 2)}",
                    "Prefer": "return=representation",
                },
            )
            debug_id = r.headers.get("PayPal-Debug-Id")
            log.info("paypal action=%s invoice_id=%s status=%s debug_id=%s",
                     action, invoice_id or "-", r.status_code, debug_id)
            if r.status_code == 401 and attempt == 1:
                continue
            break
        if r.status_code >= 400:
            raise PayPalError(r.status_code, debug_id, r.text)
        return r

    # --- invoicing v2 -----------------------------------------------------
    def create_draft_invoice(self, recipient_email: str, items: list[dict],
                             currency: str = "USD", due_date: str | None = None,
                             note: str | None = None) -> dict:
        """items: [{name, quantity: Decimal, unit_price: Decimal}]. Returns the invoice dict with 'id'."""
        body: dict = {
            "detail": {"currency_code": currency},
            "primary_recipients": [{"billing_info": {"email_address": recipient_email}}],
            "items": [
                {
                    "name": i["name"],
                    "quantity": str(i["quantity"]),
                    "unit_amount": {"currency_code": currency, "value": money(i["unit_price"])},
                }
                for i in items
            ],
        }
        if due_date:
            body["detail"]["payment_term"] = {"term_type": "DUE_ON_DATE_SPECIFIED", "due_date": due_date}
        if note:
            body["detail"]["note"] = note
        r = self._request("create_draft", "POST", "/v2/invoicing/invoices", json=body)
        j = r.json()
        # Prefer=return=representation returns the invoice; otherwise only an href to it.
        if "id" not in j and "href" in j:
            j["id"] = j["href"].rstrip("/").rsplit("/", 1)[-1]
        return j

    def send_invoice(self, invoice_id: str) -> dict:
        r = self._request("send", "POST", f"/v2/invoicing/invoices/{invoice_id}/send",
                          invoice_id, json={"send_to_invoicer": True})
        return r.json() if r.content else {}

    def get_invoice(self, invoice_id: str) -> dict:
        return self._request("get", "GET", f"/v2/invoicing/invoices/{invoice_id}", invoice_id).json()

    def cancel_invoice(self, invoice_id: str, note: str | None = None) -> None:
        self._request("cancel", "POST", f"/v2/invoicing/invoices/{invoice_id}/cancel", invoice_id,
                      json={"send_to_recipient": True, "send_to_invoicer": True,
                            "note": note or "Cancelled by Paycord"})


paypal = PayPalClient()
