"""Random generation of a project's team from catalog.toml.

When a project is created: `team = generate_team("startup")`, store `team.to_dict()`,
then `render_system_prompt(team, employee, boss_name)` gives each employee's prompt.
"""

import random
import tomllib
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("catalog.toml")
MODEL_RANK = {"haiku": 0, "sonnet": 1, "opus": 2}
DIVERSITY_ATTEMPTS = 1000


@cache
def load_catalog() -> dict:
    with CATALOG_PATH.open("rb") as f:
        return tomllib.load(f)


@dataclass
class Employee:
    name: str
    roles: list[str]
    title: str
    model: str
    permissions: list[str]
    traits: dict[str, int]
    quirks: list[str]
    style: dict[str, str]


@dataclass
class Team:
    mode: str
    seed: int
    process: dict
    employees: list[Employee]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Team":
        return cls(**{**data, "employees": [Employee(**e) for e in data["employees"]]})


def generate_team(mode: str, seed: int | None = None) -> Team:
    """Randomly draw a team. Same mode + same seed = same team."""
    catalog = load_catalog()
    if mode not in catalog["modes"]:
        raise ValueError(f"Unknown mode: {mode} (choices: {', '.join(catalog['modes'])})")
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    rng = random.Random(seed)

    mode_cfg = catalog["modes"][mode]
    seats = [seat["roles"] for seat in mode_cfg["seats"] for _ in range(seat.get("count", 1))]
    names = rng.sample(catalog["people"]["names"], len(seats))
    traits = _draw_traits(rng, catalog["personality"], len(seats))
    employees = [
        _make_employee(rng, catalog, roles, name, t) for roles, name, t in zip(seats, names, traits)
    ]
    return Team(mode=mode, seed=seed, process=dict(mode_cfg["process"]), employees=employees)


def custom_employee(
    roles: list[str],
    name: str,
    *,
    traits: dict[str, int] | None = None,
    quirks: list[str] | None = None,
    style: dict[str, str] | None = None,
    model: str | None = None,
    seed: int | None = None,
) -> Employee:
    """An employee chosen by the boss. The roles set the title, permissions and default
    model; whatever part of the personality is left out is drawn at random."""
    catalog = load_catalog()
    roles = list(dict.fromkeys(roles))
    unknown = [r for r in roles if r not in catalog["roles"]]
    if not roles or unknown:
        raise ValueError(f"Unknown roles: {', '.join(unknown)}" if unknown else "An employee needs a role")
    rng = random.Random(seed)
    personality = catalog["personality"]
    drawn = {a["key"]: rng.choice(personality["levels"]) for a in personality["axes"]}
    member = _make_employee(rng, catalog, roles, name, {**drawn, **(traits or {})})
    if quirks is not None:
        member.quirks = list(quirks)
    if style is not None:
        member.style = {**member.style, **style}
    if model is not None:
        member.model = model
    return member


def reroll_employee(team: Team, index: int, seed: int | None = None) -> Employee:
    """Redraw one employee's personality (roles and name are kept)."""
    catalog = load_catalog()
    rng = random.Random(seed)
    old = team.employees[index]
    axes = catalog["personality"]["axes"]
    traits = {a["key"]: rng.choice(catalog["personality"]["levels"]) for a in axes}
    team.employees[index] = _make_employee(rng, catalog, old.roles, old.name, traits)
    return team.employees[index]


def _draw_traits(rng: random.Random, personality: dict, n: int) -> list[dict[str, int]]:
    axes = personality["axes"]
    levels = personality["levels"]
    diverse = [a["key"] for a in axes if a.get("diverse")]

    def draw() -> list[dict[str, int]]:
        return [{a["key"]: rng.choice(levels) for a in axes} for _ in range(n)]

    def is_diverse(team: list[dict[str, int]]) -> bool:
        return all(
            any(t[k] < 0 for t in team) and any(t[k] > 0 for t in team) for k in diverse
        )

    team = draw()
    if n < 2:
        return team
    for _ in range(DIVERSITY_ATTEMPTS):
        if is_diverse(team):
            break
        team = draw()
    return team


def _make_employee(
    rng: random.Random, catalog: dict, role_keys: list[str], name: str, traits: dict[str, int]
) -> Employee:
    roles = [catalog["roles"][k] for k in role_keys]
    personality = catalog["personality"]
    return Employee(
        name=name,
        roles=list(role_keys),
        title=" + ".join(r["title"] for r in roles),
        model=max((r["model"] for r in roles), key=MODEL_RANK.__getitem__),
        permissions=sorted({p for r in roles for p in r["permissions"]}),
        traits=traits,
        quirks=rng.sample(personality["quirks"], rng.randint(1, 2)),
        style={k: rng.choice(v) for k, v in personality["style"].items()},
    )


# --- System prompt -----------------------------------------------------------------


def render_system_prompt(team: Team, employee: Employee, boss_name: str) -> str:
    """`boss_name` is the name of the person using Palabre (the CEO)."""
    catalog = load_catalog()
    boss = {**catalog["boss"], "name": boss_name}
    mode = catalog["modes"][team.mode]
    sections = [
        f"You are {employee.name}, {employee.title}, in a software development company "
        f"organized as a {mode['label']}.",
        "## Your boss\n" + boss["prompt"].strip().format(**boss),
        "## The team\n" + _render_roster(team, employee, boss),
        *(_render_role(catalog["roles"][k]) for k in employee.roles),
        "## Your personality\n" + _render_personality(employee, catalog["personality"]),
        "## Company process\n" + "\n".join(f"- {r}" for r in mode["rules"]),
    ]
    return "\n\n".join(sections)


def _render_roster(team: Team, me: Employee, boss: dict) -> str:
    lines = [f"- {boss['name']} — {boss['title']} (the boss)"]
    for e in team.employees:
        lines.append(f"- {e.name} — {e.title}" + (" (you)" if e is me else ""))
    return "\n".join(lines)


def _render_role(role: dict) -> str:
    bullets = lambda items: "\n".join(f"- {i}" for i in items)  # noqa: E731
    return (
        f"## Position: {role['title']}\n"
        f"Mission: {role['mission']}\n\n"
        f"Responsibilities:\n{bullets(role['responsibilities'])}\n\n"
        f"You do NOT:\n{bullets(role['forbidden'])}\n\n"
        f"Deliverables: {', '.join(role['deliverables'])}\n"
        f"Escalation: {role['escalation']}\n"
        f"Success criterion: {role['success']}"
    )


def _render_personality(employee: Employee, personality: dict) -> str:
    lines = ["In discussions and choices, your opinions lean as follows:"]
    for axis in personality["axes"]:
        level = employee.traits[axis["key"]]
        if level == 0:
            continue
        intensity = "strong" if abs(level) == 2 else "moderate"
        pole = axis["low"] if level < 0 else axis["high"]
        lines.append(f"- {axis['label']} ({intensity}): {pole}.")
    lines += [f"- {q}" for q in employee.quirks]
    lines.append(
        f"Communication style: {employee.style['verbosity']}, tone {employee.style['tone']}."
    )
    lines.append("Your personality shapes your opinions, never your mission: you always do your job.")
    return "\n".join(lines)
