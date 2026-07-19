"""Pluggable delivery for the proactive scheduler's findings.

Default is a generic webhook POST (works with Slack/Discord incoming
webhooks or any endpoint expecting a JSON body); a log-only notifier is
available for local dev / when no webhook is configured.
"""

from typing import Protocol

import httpx

from caudal.core.logging import get_logger

logger = get_logger(__name__)


class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class LogNotifier:
    """No-op delivery — logs the message instead of sending it anywhere.
    Used when no webhook URL is configured, so the scheduler still runs
    and its findings are visible in logs/observability rather than
    silently dropped.
    """

    def send(self, title: str, body: str) -> None:
        logger.info("notifier.log_only", title=title, body=body)


class WebhookNotifier:
    def __init__(self, url: str, timeout_seconds: float = 10.0) -> None:
        self._url = url
        self._timeout = timeout_seconds

    def send(self, title: str, body: str) -> None:
        response = httpx.post(self._url, json={"text": f"*{title}*\n{body}"}, timeout=self._timeout)
        response.raise_for_status()
        logger.info("notifier.webhook_sent", title=title, status_code=response.status_code)


def build_notifier(webhook_url: str | None) -> Notifier:
    if webhook_url:
        return WebhookNotifier(webhook_url)
    return LogNotifier()
