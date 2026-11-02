"""Random generation of a project's team from the catalog (company/catalog.py).

When a project is created: `team = generate_team("startup")`, store `team.to_dict()`,
then `render_system_prompt(team, employee, boss_name)` gives each employee's prompt.
"""

import random
from dataclasses import asdict, dataclass

from app.company.catalog import Role, load_catalog

MODEL_RANK = {"haiku": 0, "sonnet": 1, "opus": 2}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DIVERSITY_ATTEMPTS = 1000


def effort_for(role_keys: list[str]) -> str | None:
    """The claude --effort level of an employee: the highest of their roles, None (claude's
    default) as soon as one role sets none."""
    roles = load_catalog()["roles"]
    levels = [roles[k].effort for k in role_keys]
    if not levels or None in levels:
        return None
    return max(levels, key=EFFORT_LEVELS.index)


def personality_preset(key: str) -> dict:
    """A personality preset; ValueError when it does not exist."""
    presets = load_catalog()["personalities"]
    if key not in presets:
        raise ValueError(f"Unknown personality: {key} (choices: {', '.join(presets)})")
    return presets[key]


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

    seats = [seat["roles"] for seat in catalog["modes"][mode]["seats"] for _ in range(seat.get("count", 1))]
    return _draw_team(rng, catalog, mode, seed, seats)


def generate_team_from_roles(mode: str, role_keys: list[str], seed: int | None = None) -> Team:
    """A team with one employee per role chosen beforehand (the process is the mode's); the names
    and personalities are drawn at random, as for generate_team."""
    catalog = load_catalog()
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    return _draw_team(random.Random(seed), catalog, mode, seed, [[key] for key in role_keys])


def _draw_team(rng: random.Random, catalog: dict, mode: str, seed: int, seats: list[list[str]]) -> Team:
    mode_cfg = catalog["modes"][mode]
    personality = load_catalog()["personality"]
    names = rng.sample(catalog["people"]["names"], len(seats))
    traits = _draw_traits(rng, personality, len(seats))
    employees = [
        _make_employee(rng, catalog, personality, roles, name, t) for roles, name, t in zip(seats, names, traits)
    ]
    return Team(mode=mode, seed=seed, process=dict(mode_cfg["process"]), employees=employees)


def custom_employee(
    roles: list[str],
    name: str,
    *,
    traits: dict[str, int] | None = None,
    quirks: list[str] | None = None,
    style: dict[str, str] | None = None,
    preset: str | None = None,
    model: str | None = None,
    seed: int | None = None,
) -> Employee:
    """An employee chosen by the boss. The roles set the title,
    permissions and default model. The personality preset applies first, then the explicit
    traits, quirks and style override it; whatever is still left out is drawn at random."""
    catalog = load_catalog()
    roles = list(dict.fromkeys(roles))
    unknown = [r for r in roles if r not in catalog["roles"]]
    if not roles or unknown:
        raise ValueError(f"Unknown roles: {', '.join(unknown)}" if unknown else "An employee needs a role")
    preset_data = personality_preset(preset) if preset is not None else None
    rng = random.Random(seed)
    personality = catalog["personality"]
    drawn = {a["key"]: rng.choice(personality["levels"]) for a in personality["axes"]}
    preset_traits = {a["key"]: preset_data["traits"].get(a["key"], 0) for a in personality["axes"]} if preset_data else {}
    member = _make_employee(rng, catalog, personality, roles, name, {**drawn, **preset_traits, **(traits or {})})
    if preset_data:
        member.quirks = list(preset_data["quirks"])
        member.style = dict(preset_data["style"])
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
    personality = catalog["personality"]
    traits = {a["key"]: rng.choice(personality["levels"]) for a in personality["axes"]}
    team.employees[index] = _make_employee(rng, catalog, personality, old.roles, old.name, traits)
    return team.employees[index]


def random_personality(seed: int | None = None) -> dict:
    """A random but valid personality (traits, quirks and style)."""
    rng = random.Random(seed)
    personality = load_catalog()["personality"]
    traits = {a["key"]: rng.choice(personality["levels"]) for a in personality["axes"]}
    return {
        "traits": traits,
        "quirks": rng.sample(personality["quirks"], rng.randint(1, 2)),
        "style": {k: rng.choice(v) for k, v in personality["style"].items()},
    }


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
    rng: random.Random, catalog: dict, personality: dict, role_keys: list[str], name: str, traits: dict[str, int]
) -> Employee:
    roles = [catalog["roles"][k] for k in role_keys]
    return Employee(
        name=name,
        roles=list(role_keys),
        title=" + ".join(r.title for r in roles),
        model=max((r.model for r in roles), key=MODEL_RANK.__getitem__),
        permissions=sorted({p for r in roles for p in r.permissions}),
        traits=traits,
        quirks=rng.sample(personality["quirks"], rng.randint(1, 2)),
        style={k: rng.choice(v) for k, v in personality["style"].items()},
    )


# --- System prompt -----------------------------------------------------------------


def render_system_prompt(team: Team, employee: Employee, boss_name: str) -> str:
    """`boss_name` is the name of the person using Palabre (the CEO)."""
    catalog = load_catalog()
    mode = catalog["modes"][team.mode]
    boss = {**catalog["boss"], "name": boss_name}
    intro = (
        f"You are {employee.name}, {employee.title}, in a software development company "
        f"organized as a {mode['label']}."
    )
    sections = [
        intro,
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


def _render_role(role: Role) -> str:
    bullets = lambda items: "\n".join(f"- {i}" for i in items)  # noqa: E731
    working_notes = [
        "How you work:\n" + "\n".join(f"{n}. {step}" for n, step in enumerate(role.method, 1))
        if role.method
        else None,
        f"Watch points:\n{bullets(role.watch_points)}" if role.watch_points else None,
        f"A good deliverable: {role.deliverable_format}" if role.deliverable_format else None,
    ]
    sections = [
        f"## Position: {role.title}\nMission: {role.mission}",
        f"Responsibilities:\n{bullets(role.responsibilities)}",
        f"You do NOT:\n{bullets(role.forbidden)}",
        *(note for note in working_notes if note),
        f"Deliverables: {', '.join(role.deliverables)}\n"
        f"Escalation: {role.escalation}\n"
        f"Success criterion: {role.success}",
    ]
    return "\n\n".join(sections)


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
        f"Communication style: {employee.style['verbosity']}, tone {employee.style['tone']}"
        " (in the chat, even detailed stays a few sentences)."
    )
    lines.append("Your personality shapes your opinions, never your mission: you always do your job.")
    return "\n".join(lines)
