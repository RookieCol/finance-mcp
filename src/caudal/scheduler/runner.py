"""Proactive scheduler process — the internal fallback delivery path for
when Hermes cron isn't available/configured (README documents the
primary path: Hermes cron calling `get_digest`/`check_alerts` via MCP).

Runs the alert check daily and the digest weekly, delivering via the
configured notifier (webhook, or logs if none configured).
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from caudal.config import get_settings
from caudal.core import db
from caudal.core.logging import configure_logging, get_logger
from caudal.core.tracing import configure_tracing
from caudal.scheduler.jobs import run_alert_check, run_weekly_digest
from caudal.scheduler.notifier import Notifier, build_notifier

logger = get_logger(__name__)


def _alert_check_job(notifier: Notifier, cash_balance_minor: int) -> None:
    with db.session_scope() as session:
        run_alert_check(session, notifier, cash_balance_minor=cash_balance_minor)


def _digest_job(notifier: Notifier, cash_balance_minor: int) -> None:
    with db.session_scope() as session:
        run_weekly_digest(session, notifier, cash_balance_minor=cash_balance_minor)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otel_exporter_otlp_endpoint, settings.otel_exporter_otlp_headers)
    db.init_engine(settings.database_url)

    notifier = build_notifier(settings.notifier_webhook_url)
    cash_balance_minor = int(round(float(settings.scheduler_cash_balance) * 100))

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _alert_check_job,
        CronTrigger(hour=settings.scheduler_alert_check_hour_utc),
        args=[notifier, cash_balance_minor],
        id="alert_check",
    )
    scheduler.add_job(
        _digest_job,
        CronTrigger(
            day_of_week=settings.scheduler_digest_day_of_week,
            hour=settings.scheduler_digest_hour_utc,
        ),
        args=[notifier, cash_balance_minor],
        id="weekly_digest",
    )
    logger.info(
        "scheduler.starting",
        alert_check_hour_utc=settings.scheduler_alert_check_hour_utc,
        digest_day=settings.scheduler_digest_day_of_week,
        digest_hour_utc=settings.scheduler_digest_hour_utc,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
