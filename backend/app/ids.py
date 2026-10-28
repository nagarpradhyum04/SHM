import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits


def new_id(prefix: str, length: int = 8) -> str:
    """Return a short, random, URL-safe identifier such as ``DEF-7K2QXM4A``."""
    return f"{prefix}-{''.join(secrets.choice(_ALPHABET) for _ in range(length))}"
