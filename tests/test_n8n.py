import asyncio
import json

import httpx

from caller_app.n8n import CallRequest, N8nCallTrigger


def test_n8n_client_sends_exact_contract_and_parses_accepted_response():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            202,
            json={
                "accepted": True,
                "session_id": "call-42",
                "vapi_call_id": "vapi-42",
            },
        )

    trigger = N8nCallTrigger(
        webhook_url="https://n8n.example.test/webhook/start-call",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        trigger.trigger(
            CallRequest(
                name="Max Mustermann",
                email="max@example.com",
                phone="+49" + "15112345678",
            )
        )
    )

    assert captured == {
        "method": "POST",
        "url": "https://n8n.example.test/webhook/start-call",
        "body": {
            "name": "Max Mustermann",
            "email": "max@example.com",
            "phone": "+49" + "15112345678",
            "source": "app",
        },
    }
    assert result.accepted is True
    assert result.http_status == 202
    assert result.session_id == "call-42"
    assert result.vapi_call_id == "vapi-42"


def test_n8n_client_does_not_follow_redirects():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://attacker.example/collect"})

    trigger = N8nCallTrigger(
        webhook_url="https://n8n.example.test/webhook/start-call",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        trigger.trigger(CallRequest(name="Max", email="max@example.com", phone="+49" + "15112345678"))
    )

    assert requests == ["https://n8n.example.test/webhook/start-call"]
    assert result.accepted is False
    assert result.http_status == 302


def test_n8n_transport_failure_returns_service_unavailable():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    trigger = N8nCallTrigger(
        webhook_url="https://n8n.example.test/webhook/start-call",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        trigger.trigger(CallRequest(name="Max", email="max@example.com", phone="+49" + "15112345678"))
    )

    assert result.accepted is False
    assert result.http_status == 503
    assert result.error == "n8n nicht erreichbar"
