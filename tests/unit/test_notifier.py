import httpx
import pytest

from caudal.scheduler.notifier import LogNotifier, WebhookNotifier, build_notifier


def test_build_notifier_returns_log_notifier_without_a_url() -> None:
    assert isinstance(build_notifier(None), LogNotifier)


def test_build_notifier_returns_webhook_notifier_with_a_url() -> None:
    assert isinstance(build_notifier("https://hooks.example.com/x"), WebhookNotifier)


def test_log_notifier_never_raises() -> None:
    LogNotifier().send("title", "body")  # just must not raise


def test_webhook_notifier_posts_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        calls.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    WebhookNotifier("https://hooks.example.com/x").send("Alert", "something happened")

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://hooks.example.com/x"
    assert "Alert" in payload["text"]
    assert "something happened" in payload["text"]


def test_webhook_notifier_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, json: dict, timeout: float) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(500, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(httpx.HTTPStatusError):
        WebhookNotifier("https://hooks.example.com/x").send("Alert", "body")
