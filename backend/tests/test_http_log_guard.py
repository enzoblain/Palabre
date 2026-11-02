"""The app forces httpx and httpcore to WARNING so credentials stay out of DEBUG traces."""

import logging

import pytest

from app import main  # noqa: F401 (the guard runs when the module is imported)


@pytest.mark.parametrize("logger_name", ["httpx", "httpcore"])
def test_http_loggers_are_forced_to_warning(logger_name: str) -> None:
    assert logging.getLogger(logger_name).level == logging.WARNING
