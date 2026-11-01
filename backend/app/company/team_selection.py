"""Roles of an automatic team: one claude call without tools picks them from the project description, the catalog's seat order is the fallback."""

import itertools
import json
import logging
import re

from pydantic import StrictStr, TypeAdapter, ValidationError

from app.company.catalog import CODE, MANDATORY_ROLE, load_catalog, team_permission_error
from app.config import settings
from app.runner import ClaudeRunError, run_oneshot

log = logging.getLogger(__name__)

MODEL = "haiku"  # Choosing among a few dozen job names is a light task
# Placed without asking the model: the lead organizes, the reviewer and QA gate the merges (enterprise process)
SKELETON_ROLES = (MANDATORY_ROLE, "reviewer", "qa")
FALLBACK_MODE = "multinational"  # The mode whose seats give the fallback order
FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

SYSTEM_PROMPT = (
    "You staff a software team. You have no tool and no access to anything: "
    "answer with the JSON only, no comment, no code fence."
)

_KEYS = TypeAdapter(list[StrictStr])


class InvalidSelection(ValueError):
    pass


def selectable_roles() -> dict[str, tuple[str, str]]:
    """Key → (title, category) of the company roles the model may pick: every one but the lead."""
    return {
        key: (role.title, role.category)
        for key, role in load_catalog()["roles"].items()
        if role.kind == "company" and key != MANDATORY_ROLE
    }


def build_prompt(description: str, seats: int) -> str:
    catalog = "\n".join(f"- {key}: {title} ({category})" for key, (title, category) in selectable_roles().items())
    return (
        f"Project description:\n{description.strip()}\n\n"
        f"Choose the {seats} roles that suit this project best, to join a lead, a reviewer and a QA who are already hired. "
        f"Available roles (key: title (category)):\n{catalog}\n\n"
        f"Rules: use the keys above exactly; exactly {seats} keys; a key may repeat when the project needs several "
        "people in the same role; at least one role must write code.\n"
        'Answer with a JSON array of keys only: ["dev_backend", "dev_frontend"]'
    )


def parse_selection(text: str, seats: int) -> list[str]:
    """The role keys of a model answer, or InvalidSelection: one wrong key rejects the whole answer."""
    text = text.strip()
    if fenced := FENCE_RE.match(text):
        text = fenced.group(1)
    try:
        keys = _KEYS.validate_python(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidSelection(f"not the expected JSON ({type(exc).__name__})") from None
    if len(keys) != seats:
        raise InvalidSelection(f"{len(keys)} roles, exactly {seats} wanted")
    if unknown := sorted(set(keys) - selectable_roles().keys()):
        raise InvalidSelection(f"unknown roles {', '.join(unknown)}")
    if problem := team_permission_error([[key] for key in (*SKELETON_ROLES, *keys)], "company"):
        raise InvalidSelection(problem)
    roles = load_catalog()["roles"]
    if not any(CODE in roles[key].permissions for key in keys):
        raise InvalidSelection("nobody writes code")
    return keys


def fallback_selection(seats: int) -> list[str]:
    """The roles after the skeleton, in the seat order of the multinational mode with the roles that
    write code first, cut to `seats` (the order repeats when the team is bigger than the mode)."""
    roles = load_catalog()["roles"]
    seats_of_mode = load_catalog()["modes"][FALLBACK_MODE]["seats"]
    order = [key for seat in seats_of_mode for _ in range(seat.get("count", 1)) for key in seat["roles"]]
    for key in SKELETON_ROLES:
        order.remove(key)  # One seat each: the skeleton's
    order.sort(key=lambda key: CODE not in roles[key].permissions)  # Stable: code first, the rest as the mode lists it
    return list(itertools.islice(itertools.cycle(order), seats))


async def select_roles(description: str, employee_count: int, token: str | None) -> list[str]:
    """The roles of an automatic team, skeleton first then `employee_count` minus the skeleton chosen
    for the description. Any failure of the call or of its answer (logged) gives the fallback."""
    seats = employee_count - len(SKELETON_ROLES)
    try:
        answer = await run_oneshot(
            build_prompt(description, seats), system_prompt=SYSTEM_PROMPT, model=MODEL, oauth_token=token,
            timeout_s=settings.team_selection_timeout_s,
        )  # fmt: skip
        chosen = parse_selection(answer, seats)
    except (ClaudeRunError, InvalidSelection) as exc:
        log.warning("Role selection failed (%s), using the catalog order", exc)
        chosen = fallback_selection(seats)
    except Exception:
        log.exception("Role selection crashed, using the catalog order")
        chosen = fallback_selection(seats)
    return [*SKELETON_ROLES, *chosen]
