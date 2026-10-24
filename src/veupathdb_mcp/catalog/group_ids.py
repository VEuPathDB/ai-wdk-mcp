import re

GROUP_ID = re.compile(r"OG(?:\d+|(?P<residual>R\d+r\d+))_\d+")


def is_group_id(word: str) -> bool:
    return GROUP_ID.fullmatch(word) is not None


def is_residual(group: str) -> bool:
    found = GROUP_ID.fullmatch(group)
    return found is not None and found.group("residual") is not None
