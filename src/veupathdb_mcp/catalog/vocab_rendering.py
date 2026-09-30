"""Vocabulary tree rendering and value extraction.

Pure module (no I/O). Formats WDK vocabulary trees for display and
extracts allowed parameter values from typed vocabulary data.
"""

import re

from veupathdb.domain.parameters import (
    FAKE_ALL_SENTINEL,
    VocabOption,
    WDKTreeBoxVocabNode,
    WDKVocabulary,
    dedupe_options,
    flatten_vocab,
)

# The entries a whole vocabulary shows; a query reaches the rest.
_MAX_VOCAB_ENTRIES = 50
# The entries a query-narrowed vocabulary shows. A narrowed list travels whole below it.
_MAX_NARROWED_ENTRIES = 300


def _count_descendants(node: WDKTreeBoxVocabNode) -> int:
    """Count all descendants of a vocab tree node (excluding itself)."""
    total = len(node.children)
    for child in node.children:
        total += _count_descendants(child)
    return total


def render_vocab_tree(
    node: WDKTreeBoxVocabNode,
    *,
    max_lines: int = 80,
    _depth: int = 0,
    _lines: list[str] | None = None,
) -> list[str]:
    """Render a WDK tree vocabulary as indented text lines.

    Each line is ``"  " * depth + term``.  When the tree exceeds
    *max_lines*, top-level categories are always shown with descendant
    counts so the model knows what exists beyond the truncation point.
    """
    if _lines is None:
        _lines = []
    if len(_lines) >= max_lines:
        return _lines

    term = node.data.term
    is_fake_root = not term or term == FAKE_ALL_SENTINEL

    if not is_fake_root:
        _lines.append(f"{'  ' * _depth}{term}")

    for child in node.children:
        if len(_lines) >= max_lines:
            # Show remaining top-level categories as summaries.
            remaining = node.children[node.children.index(child) :]
            for r in remaining:
                r_term = r.data.term
                if r_term and r_term != FAKE_ALL_SENTINEL:
                    desc_count = _count_descendants(r)
                    if desc_count > 0:
                        _lines.append(
                            f"{'  ' * (_depth + 1)}{r_term} ({desc_count} entries, "
                            f"use query='{r_term.split()[0].lower()}' to see)"
                        )
                    else:
                        _lines.append(f"{'  ' * (_depth + 1)}{r_term}")
            break
        render_vocab_tree(child, max_lines=max_lines, _depth=_depth + 1, _lines=_lines)

    return _lines


# A label that asks for a choice ("Choose chromosome", "Choose a Module") or
# names no choice ("--None--"). A vocabulary query unions such a row in as a
# prompt; WDK marks it no other way.
_PROMPT_LABEL = re.compile(r"choose\b.*|--.*--", re.IGNORECASE | re.DOTALL)


def is_prompt_entry(option: VocabOption) -> bool:
    """Whether a vocabulary entry is the site's prompt rather than a value."""
    return bool(_PROMPT_LABEL.fullmatch(option.display.strip()))


def entries_of(vocab: WDKVocabulary | None) -> list[VocabOption]:
    """Every entry of a vocabulary, flattened, prompts left out."""
    return [option for option in flatten_vocab(vocab) if not is_prompt_entry(option)]


def prompts_of(vocab: WDKVocabulary | None) -> list[str]:
    """The terms of the prompt entries a vocabulary ships."""
    return [option.value for option in flatten_vocab(vocab) if is_prompt_entry(option)]


def vocab_options(vocab: WDKVocabulary | None) -> list[VocabOption]:
    """Every WDK-accepted value of a vocabulary with its label, in order."""
    return dedupe_options(entries_of(vocab))
