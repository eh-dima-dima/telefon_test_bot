from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx


@dataclass(frozen=True, slots=True)
class CallRequest:
    name: str
    email: str
    phone: str
    source: str = "app"

    def as_payload(self) -> dict[str, str]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class CallTriggerResult:
    accepted: bool
    http_status: int
    session_id: str | None
    vapi_call_id: str | None
    error: str | None


class CallTrigger(Protocol):
    async def trigger(self, request: CallRequest) -> CallTriggerResult: ...


class N8nCallTrigger:
    def __init__(
        self,
        *,
        webhook_url: str,
        timeout_seconds: float = 12.0,
        bearer_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = urlparse(webhook_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("webhook_url must use HTTPS")
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds
        self.bearer_token = bearer_token
        self.transport = transport

    async def trigger(self, request: CallRequest) -> CallTriggerResult:
        headers = {"Accept": "application/json"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.webhook_url,
                    json=request.as_payload(),
                    headers=headers,
                )
        except httpx.HTTPError:
            return CallTriggerResult(False, 503, None, None, "n8n nicht erreichbar")

        if len(response.content) > 32_768:
            return CallTriggerResult(False, 502, None, None, "Ungültige n8n-Antwort")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        accepted = response.status_code == 202 and body.get("accepted") is True
        return CallTriggerResult(
            accepted=accepted,
            http_status=response.status_code,
            session_id=body.get("session_id") if isinstance(body.get("session_id"), str) else None,
            vapi_call_id=body.get("vapi_call_id") if isinstance(body.get("vapi_call_id"), str) else None,
            error=body.get("error") if isinstance(body.get("error"), str) else None,
        )
