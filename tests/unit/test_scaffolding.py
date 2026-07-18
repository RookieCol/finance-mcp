"""Smoke tests for Stage 1 (project scaffolding).

Real coverage of core/, mcp_server/, web/, and scheduler/ behavior lands
alongside those stages; this file just asserts the package is importable
and correctly wired so CI has something meaningful to run from Stage 1
onward instead of "no tests collected".
"""

from fastapi import FastAPI

from finance_mcp.web.app import app


def test_package_imports() -> None:
    import finance_mcp  # noqa: F401


def test_web_app_is_a_fastapi_app() -> None:
    assert isinstance(app, FastAPI)


def test_mcp_server_main_is_not_yet_implemented() -> None:
    from finance_mcp.mcp_server.server import main

    try:
        main()
    except NotImplementedError:
        pass
    else:
        raise AssertionError("Expected NotImplementedError until Stage 4 lands")


def test_scheduler_main_is_not_yet_implemented() -> None:
    from finance_mcp.scheduler.runner import main

    try:
        main()
    except NotImplementedError:
        pass
    else:
        raise AssertionError("Expected NotImplementedError until Stage 7 lands")
