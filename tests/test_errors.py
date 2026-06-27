from __future__ import annotations

from midi_cleaner.errors import humanize_exception


def test_humanize_eof() -> None:
    message = humanize_exception(EOFError())
    assert "EOF" in message


def test_humanize_empty_sequence_as_no_notes() -> None:
    message = humanize_exception(ValueError("max() arg is an empty sequence"))
    assert message == "Pas de notes"

