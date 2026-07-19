"""Smoke tests for Stage 1 (project scaffolding).

Real coverage of core/, mcp_server/, web/, and scheduler/ behavior lands
alongside their own stages (see test_repository.py, test_mcp_tools.py,
test_scheduler.py, etc.); this file just asserts the package is
importable and correctly wired.
"""

from fastapi import FastAPI

from caudal.web.app import app


def test_package_imports() -> None:
    import caudal  # noqa: F401


def test_web_app_is_a_fastapi_app() -> None:
    assert isinstance(app, FastAPI)
