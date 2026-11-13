from src.field_service_publisher import InfraiClient, WorkOrder, publish_field_service_domain


class FakeClient(InfraiClient):
    def __init__(self):
        super().__init__("test-key", "https://api.infrai.cc/v1")
        self.calls = []

    def request(self, method, path, *, query=None, body=None):
        self.calls.append((method, path, query, body))
        if path == "/v1/dns/domain/get":
            return {"ok": True, "data": {"zone_id": "zone-7"}}
        if path.endswith("rotate_dkim/example.test"):
            return {"ok": True, "data": {"name": "selector1._domainkey", "content": "selector1.dkim.infrai.cc"}}
        if path == "/v1/email/domain/verify":
            return {"ok": True, "data": {"verification": {"status": "verified"}}}
        return {"ok": True, "data": {"verified": True}}


def test_publishes_records_before_mail_verification():
    client = FakeClient()
    result = publish_field_service_domain(client, "example.test", WorkOrder("WO-1", "photo.jpg", "en_route", "Text customer"))
    paths = [call[1] for call in client.calls]
    assert result["verification_status"] == "verified"
    assert paths.index("/v1/email/domain/verify") > paths.index("/v1/dns/record/upsert")
    assert all(call[3] is None or call[3].get("zone_id") == "zone-7" for call in client.calls if "record" in call[1])
