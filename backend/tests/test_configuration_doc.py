"""Every setting of config.py is documented in docs/configuration.md."""

import re
from pathlib import Path

from app.config import Settings

CONFIGURATION_DOC = Path(__file__).resolve().parents[2] / "docs" / "configuration.md"


def test_every_setting_is_documented():
    text = CONFIGURATION_DOC.read_text()
    missing = [
        name.upper()
        for name in Settings.model_fields
        if not re.search(rf"(?<![A-Z0-9_]){name.upper()}(?![A-Z0-9_])", text)
    ]
    assert not missing, f"Settings missing from docs/configuration.md: {', '.join(missing)}"
