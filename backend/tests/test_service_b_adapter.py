import pytest

from app.service_b import ServiceBAdapter, ServiceBError


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeHttpxClient:
    def __init__(self, response):
        self.response = response
        self.last_call = None

    def post(self, url, json, headers, timeout):
        self.last_call = {"url": url, "json": json, "headers": headers, "timeout": timeout}
        return self.response


def make_adapter(response):
    fake_client = FakeHttpxClient(response)
    adapter = ServiceBAdapter(
        "https://api.onfonmedia.co.ke/v1/sms/SendBulkSMS",
        api_key="api-key-123",
        client_id="client-id-456",
        access_key="access-key-789",
        client=fake_client,
    )
    return adapter, fake_client


def test_send_builds_onfon_request_shape_and_parses_success():
    response = FakeResponse(200, {
        "ErrorCode": 0,
        "ErrorDescription": "Success",
        "Data": [{"MobileNumber": "254712345678", "MessageId": "fc103131-5931-4530-ba8e-aa223c769536"}],
    })
    adapter, fake_client = make_adapter(response)

    provider_id = adapter.send("UPENFLOW", "254712345678", "Your order is on its way.", "msg-1", is_unicode=False)

    assert provider_id == "fc103131-5931-4530-ba8e-aa223c769536"
    assert fake_client.last_call["url"] == "https://api.onfonmedia.co.ke/v1/sms/SendBulkSMS"
    assert fake_client.last_call["headers"]["AccessKey"] == "access-key-789"
    assert fake_client.last_call["headers"]["Content-Type"] == "application/json"
    body = fake_client.last_call["json"]
    assert body["ApiKey"] == "api-key-123"
    assert body["ClientId"] == "client-id-456"
    assert body["SenderId"] == "UPENFLOW"
    assert body["IsUnicode"] is False
    assert body["MessageParameters"] == [{"Number": "254712345678", "Text": "Your order is on its way."}]
    assert "ScheduleDateTime" not in body


def test_send_sets_is_unicode_flag():
    response = FakeResponse(200, {"ErrorCode": 0, "Data": [{"MessageId": "id-1"}]})
    adapter, fake_client = make_adapter(response)

    adapter.send("UPENFLOW", "254712345678", "Hujambo, agizo lako liko njiani — asante.", "msg-2", is_unicode=True)

    assert fake_client.last_call["json"]["IsUnicode"] is True


def test_send_raises_non_retryable_on_nonzero_error_code():
    response = FakeResponse(200, {"ErrorCode": 1001, "ErrorDescription": "Insufficient balance"})
    adapter, _ = make_adapter(response)

    with pytest.raises(ServiceBError) as excinfo:
        adapter.send("UPENFLOW", "254712345678", "text", "msg-3")

    assert excinfo.value.retryable is False
    assert "Insufficient balance" in str(excinfo.value)


def test_send_raises_retryable_on_server_error():
    response = FakeResponse(503, {})
    adapter, _ = make_adapter(response)

    with pytest.raises(ServiceBError) as excinfo:
        adapter.send("UPENFLOW", "254712345678", "text", "msg-4")

    assert excinfo.value.retryable is True


def test_send_raises_non_retryable_on_client_error():
    response = FakeResponse(401, {})
    adapter, _ = make_adapter(response)

    with pytest.raises(ServiceBError) as excinfo:
        adapter.send("UPENFLOW", "254712345678", "text", "msg-5")

    assert excinfo.value.retryable is False


def test_send_returns_none_when_data_missing():
    response = FakeResponse(200, {"ErrorCode": 0, "Data": []})
    adapter, _ = make_adapter(response)

    assert adapter.send("UPENFLOW", "254712345678", "text", "msg-6") is None
