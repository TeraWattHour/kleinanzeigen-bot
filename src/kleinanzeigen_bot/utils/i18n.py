from collections.abc import Sized

__all__ = [
    "pluralize",
]

def pluralize(noun: str, count: int | Sized, *, prefix_with_count: bool = True) -> str:
    count = int(count) if isinstance(count, int) else len(count)
    if count < 0:
        raise ValueError("Count must be a non-negative integer or sized object")

    prefix = f"{count} " if prefix_with_count else ""

    if count == 1:
        return f"{prefix}{noun}"

    if len(noun) < 2:
        return f"{prefix}{noun}s"
    if noun.endswith(("s", "sh", "ch", "x", "z")):
        return f"{prefix}{noun}es"
    if noun.endswith("y") and noun[-2].lower() not in "aeiou":
        return f"{prefix}{noun[:-1]}ies"
    return f"{prefix}{noun}s"
