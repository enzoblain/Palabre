"""Channels of a custom team: one claude call without tools proposes them, the catalog's rules are the fallback."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, StrictStr, TypeAdapter, ValidationError

from app.runner import ClaudeRunError, RunResult, RunSpec, run_claude

log = logging.getLogger(__name__)

MAX_CHANNELS = 6
MODEL = "haiku"  # A light model is enough to group a dozen names
TIMEOUT_S = 120
NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
RESERVED = {"direction"}  # Created by the backend, never by a plan
FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

SYSTEM_PROMPT = (
    "You organize the chat channels of a software team. You have no tool and no access to anything: "
    "answer with the JSON only, no comment, no code fence."
)


class Member(TypedDict):
    name: str
    roles: list[str]


class PlannedChannel(BaseModel):
    """A channel as the model proposes it. Strict: no coercion, no extra field."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: StrictStr
    members: list[StrictStr]


class InvalidPlan(ValueError):
    pass


_PLAN = TypeAdapter(list[PlannedChannel])


def build_prompt(members: list[Member]) -> str:
    roster = "\n".join(f"- {m['name']}: {', '.join(m['roles'])}" for m in members)
    return (
        "Here are the members of the team (name: roles):\n"
        f"{roster}\n\n"
        f"Propose at most {MAX_CHANNELS} topic channels that suit this team (for example by discipline: "
        "development, quality, product). Do not propose a catch-all channel with everyone.\n"
        "Rules: a channel name is lowercase (letters, digits, - or _); each channel has at least 2 members, "
        "taken from the list above with their exact name; channel names are unique.\n"
        'Answer with a JSON array only: [{"name": "dev", "members": ["Alice", "Bob"]}]'
    )


def parse_plan(text: str, members: list[Member]) -> list[PlannedChannel]:
    """The channels of a model answer, or InvalidPlan: one wrong channel rejects the whole plan."""
    text = text.strip()
    if fenced := FENCE_RE.match(text):
        text = fenced.group(1)
    try:
        channels = _PLAN.validate_python(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidPlan(f"not the expected JSON ({type(exc).__name__})") from None
    if not channels:
        raise InvalidPlan("no channel")
    if len(channels) > MAX_CHANNELS:
        raise InvalidPlan(f"{len(channels)} channels, at most {MAX_CHANNELS}")
    known = {m["name"] for m in members}
    seen: set[str] = set()
    for channel in channels:
        if not NAME_RE.fullmatch(channel.name) or channel.name in RESERVED:
            raise InvalidPlan(f"invalid channel name {channel.name!r}")
        if channel.name in seen:
            raise InvalidPlan(f"duplicate channel name {channel.name!r}")
        seen.add(channel.name)
        if unknown := sorted(set(channel.members) - known):
            raise InvalidPlan(f"{channel.name}: unknown members {', '.join(unknown)}")
        if len(set(channel.members)) < 2 or len(set(channel.members)) != len(channel.members):
            raise InvalidPlan(f"{channel.name}: needs at least 2 distinct members")
    return channels


async def plan_channels(
    members: list[Member], *, lead_id: int, lead_name: str, token: str | None, cwd: Path
) -> list[PlannedChannel] | None:
    """The channels proposed for these members, run on the lead's account. None (logged) when the
    call fails, times out or answers something invalid: the caller falls back on the catalog."""
    spec = RunSpec(
        author_name=lead_name, system_prompt=SYSTEM_PROMPT, prompt=build_prompt(members), cwd=cwd,
        employee_id=lead_id, mcp_headers={}, mcp_tools=[], claude_tools=[], model=MODEL,
        oauth_token=token, max_turns=1,
    )  # fmt: skip
    try:
        result: RunResult = await asyncio.wait_for(run_claude(spec), TIMEOUT_S)
        if result.is_error:
            raise InvalidPlan(f"the run ended with an error: {result.text[:200]}")
        return parse_plan(result.text, members)
    except TimeoutError:
        log.warning("Channel planner timed out after %ss, using the catalog's channels", TIMEOUT_S)
    except (ClaudeRunError, InvalidPlan) as exc:
        log.warning("Channel planner failed (%s), using the catalog's channels", exc)
    except Exception:
        log.exception("Channel planner crashed, using the catalog's channels")
    return None
