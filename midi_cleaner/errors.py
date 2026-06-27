from __future__ import annotations


def humanize_exception(exc: Exception) -> str:
    if isinstance(exc, EOFError):
        return "Fichier MIDI tronque ou illisible (EOF)."

    message = str(exc).strip()
    lowered = message.lower()
    if "max() arg is an empty sequence" in message or "empty sequence" in lowered:
        return "Pas de notes"
    if "no notes" in lowered:
        return "Pas de notes"
    if not message:
        return type(exc).__name__
    return f"{type(exc).__name__}: {message}"

