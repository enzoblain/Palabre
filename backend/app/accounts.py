"""Which Claude account (CLAUDE_CODE_OAUTH_TOKENS) each employee runs on."""

from app.config import settings
from app.credits import exhausted_accounts
from app.models import Employee


def account_count() -> int:
    return len(settings.claude_tokens)


def token_for(account: int) -> str | None:
    tokens = settings.claude_tokens
    return tokens[account - 1] if 1 <= account <= len(tokens) else None


def assign_accounts(employees: list[Employee]) -> dict[int, int]:
    """Employee id → account number (from 1), for the employees of one project.

    An employee's custom account is kept if it exists; the others are spread so that
    every account ends up with as many employees as possible. Exhausted accounts get no
    automatic employee as long as another account is left."""
    n = max(account_count(), 1)
    usable = [i for i in range(n) if i + 1 not in exhausted_accounts()] or list(range(n))
    load = [0] * n
    accounts: dict[int, int] = {}
    automatic = []
    for e in sorted(employees, key=lambda e: e.id):
        if e.account is not None and 1 <= e.account <= n:
            accounts[e.id] = e.account
            load[e.account - 1] += 1
        else:
            automatic.append(e)
    for e in automatic:
        least = min(usable, key=lambda i: load[i])
        load[least] += 1
        accounts[e.id] = least + 1
    return accounts
