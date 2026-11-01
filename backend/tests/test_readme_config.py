"""Every setting of config.py must appear in the README's Configuration section."""

import re
from pathlib import Path

from app.config import Settings

README = Path(__file__).resolve().parents[2] / "README.md"


def _configuration_section() -> str:
    text = README.read_text()
    start = text.index("\n## Configuration\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None]


def test_every_setting_is_documented_in_the_readme():
    section = _configuration_section()
    undocumented = [
        name for name in Settings.model_fields
        if not re.search(rf"(?<![A-Z0-9_]){name.upper()}(?![A-Z0-9_])", section)
    ]
    assert not undocumented, f"Settings missing from the README's Configuration section: {undocumented}"
