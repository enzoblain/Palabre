"""accounts.team_token: the account of a call that belongs to no employee."""

import pytest

from app import accounts
from app.config import settings


@pytest.fixture
def tokens(monkeypatch):
    def configure(value: str, exhausted: list[int]) -> None:
        monkeypatch.setattr(settings, "claude_code_oauth_tokens", value)
        monkeypatch.setattr(accounts, "exhausted_accounts", lambda: exhausted)

    return configure


def test_the_first_account_that_is_not_exhausted(tokens):
    tokens("a|b|c", exhausted=[1])
    assert accounts.team_token() == "b"


def test_all_accounts_exhausted_falls_back_to_the_first(tokens):
    tokens("a|b", exhausted=[1, 2])
    assert accounts.team_token() == "a"


def test_no_token_configured_gives_none(tokens):
    tokens("", exhausted=[])
    assert accounts.team_token() is None
