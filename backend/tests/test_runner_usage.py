"""Parsing of the token usage reported by a Claude run."""

from app.runner import _usage


def test_parse_claude_usage():
    parsed = _usage({"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 5})
    assert parsed == {"input_tokens": 3, "output_tokens": 4, "cache_creation_tokens": None, "cache_read_tokens": 5}
    assert _usage(None)["input_tokens"] is None
