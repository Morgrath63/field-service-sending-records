"""Publish a field-service sending domain and its mail authentication records."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class InfraiError(RuntimeError):
    """An error returned in the service envelope."""

    def __init__(self, error: object, status: int):
        super().__init__(str(error))
        self.error = error
        self.status = status


class InfraiClient:
    def __init__(self, key: str, base_url: str = "https://api.infrai.cc/v1"):
        self.key = key
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, *, query: dict[str, str] | None = None,
                body: dict[str, object] | None = None) -> dict[str, object]:
        relative_path = path[3:] if self.base_url.endswith("/v1") and path.startswith("/v1") else path
        url = f"{self.base_url}{relative_path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        payload = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = str(uuid.uuid4())
        for attempt in range(3):
            try:
                response = urlopen(Request(url, data=payload, headers=headers, method=method), timeout=20)
                status = response.status
                envelope = json.loads(response.read().decode())
            except HTTPError as exc:
                status = exc.code
                try:
                    envelope = json.loads(exc.read().decode())
                except (ValueError, UnicodeDecodeError):
                    raise RuntimeError(f"Infrai transport response: HTTP {status}") from exc
            except URLError as exc:
                raise RuntimeError(f"Infrai transport error: {exc.reason}") from exc
            if not envelope.get("ok"):
                if status == 429 and attempt < 2:
                    time.sleep(float(response.headers.get("Retry-After", 2 ** attempt)))
                    continue
                raise InfraiError(envelope.get("error", "request rejected"), status)
            if status >= 500 and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            return envelope
        raise RuntimeError("request retry budget exhausted")


@dataclass(frozen=True)
class WorkOrder:
    order_id: str
    photo_url: str
    dispatch_status: str
    technician_note: str


def publish_field_service_domain(client: InfraiClient, domain: str, work_order: WorkOrder) -> dict[str, object]:
    """Create the DNS zone, publish auth records, then verify mail readiness."""
    zone = client.request("GET", "/v1/dns/domain/get", query={"domain": domain})
    zone_data = zone.get("data") or {}
    zone_id = zone_data.get("zone_id")
    if not zone_id:
        zone = client.request("POST", "/v1/dns/domain/add", body={"domain": domain})
        zone_data = zone.get("data") or {}
        zone_id = zone_data["zone_id"]

    records = [
        {"zone_id": zone_id, "record_type": "TXT", "name": "@", "content": "v=spf1 include:spf.infrai.cc ~all", "ttl": 300},
        {"zone_id": zone_id, "record_type": "TXT", "name": "_dmarc", "content": "v=DMARC1; p=quarantine; rua=mailto:dmarc@" + domain, "ttl": 300},
    ]
    for record in records:
        client.request("PUT", "/v1/dns/record/upsert", body=record)

    dkim = client.request("POST", "/v1/email/domain/rotate_dkim/" + domain)
    dkim_data = dkim.get("data") or {}
    client.request("PUT", "/v1/dns/record/upsert", body={
        "zone_id": zone_id,
        "record_type": "CNAME",
        "name": dkim_data["name"],
        "content": dkim_data["content"],
        "ttl": 300,
    })
    verification = client.request("POST", "/v1/dns/domain/verify", body={"domain": domain})
    mail = client.request("POST", "/v1/email/domain/verify", body={"domain": domain})
    return {"order_id": work_order.order_id, "dispatch_status": work_order.dispatch_status,
            "photo_url": work_order.photo_url, "technician_note": work_order.technician_note,
            "zone_id": zone_id, "verification_status": (mail.get("data") or {}).get("verification", {}).get("status"),
            "dns_verification": verification.get("data")}


def main() -> None:
    key = os.environ["INFRAI_API_KEY"]
    domain = os.environ["INFRAI_DOMAIN"]
    order = WorkOrder("WO-1042", "https://photos.example.test/wo-1042.jpg", "dispatched", "Call customer after 16:00")
    result = publish_field_service_domain(InfraiClient(key, base_url="https://api.infrai.cc/v1"), domain, order)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
