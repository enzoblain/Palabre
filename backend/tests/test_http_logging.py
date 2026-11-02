"""The HTTP client loggers stay at WARNING so tokens never leak into DEBUG traces."""

import logging

import pytest

from app.main import QUIET_HTTP_LOGGERS, silence_http_loggers


@pytest.mark.parametrize("name", QUIET_HTTP_LOGGERS)
def test_http_loggers_are_forced_to_warning(name: str) -> None:
    logging.getLogger(name).setLevel(logging.DEBUG)
    silence_http_loggers()
    assert logging.getLogger(name).level == logging.WARNING


def test_http_loggers_cover_httpx_and_httpcore() -> None:
    assert set(QUIET_HTTP_LOGGERS) == {"httpx", "httpcore"}
