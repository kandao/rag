import re


def _compress_group(raw_group: str) -> str:
    """Strip enterprise domain suffixes and normalize to a group: token."""
    name = raw_group
    name = re.sub(r"@company\.com$", "", name)
    name = re.sub(r"@[-\w]+\.company\.com$", "", name)
    name = name.lower()
    name = re.sub(r"[\s.]+", "-", name)
    return "group:" + name


def compress_groups_to_tokens(groups: list[str]) -> list[str]:
    """Convert raw group identifiers to normalized group: tokens.

    Strips enterprise domain suffixes, lowercases, replaces spaces/dots with hyphens,
    and prepends the 'group:' namespace. Deduplicates and sorts the result.
    """
    tokens = {_compress_group(g) for g in groups}
    return sorted(tokens)
