"""Every setting of config.py is documented in the README's Configuration section."""

import re
from pathlib import Path

from app.config import Settings

README = Path(__file__).resolve().parents[2] / "README.md"
SECTION_TITLE = "## Configuration"


def configuration_section() -> str:
    text = README.read_text()
    start = text.index(SECTION_TITLE)
    next_title = re.search(r"^## ", text[start + len(SECTION_TITLE):], re.MULTILINE)
    end = start + len(SECTION_TITLE) + next_title.start() if next_title else len(text)
    return text[start:end]


def test_every_setting_is_documented():
    section = configuration_section()
    missing = [
        name.upper()
        for name in Settings.model_fields
        if not re.search(rf"(?<![A-Z0-9_]){name.upper()}(?![A-Z0-9_])", section)
    ]
    assert not missing, f"Settings missing from the README Configuration section: {', '.join(missing)}"
