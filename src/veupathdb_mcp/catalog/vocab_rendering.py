"""Vocabulary tree rendering and value extraction.

Pure module (no I/O). Formats WDK vocabulary trees for display and
extracts allowed parameter values from typed vocabulary data.
"""

from veupathdb.domain.parameters.wdk_vocab import (
    FAKE_ALL_SENTINEL,
    VocabOption,
    WDKTreeBoxVocabNode,
    WDKVocabulary,
    dedupe_options,
    flatten_vocab,
)

# Cap rendered vocab entries so the LLM tool response stays within a
# manageable size; large WDK vocabularies can have thousands of values.
_MAX_VOCAB_ENTRIES = 50


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


def allowed_values(vocab: WDKVocabulary | None) -> list[VocabOption]:
    """Extract WDK-accepted parameter values from a vocabulary.

    Returns ``VocabOption`` objects (value + display) so the LLM knows
    both *what to pass* and *what it means*. Capped at 50.
    """
    if not vocab:
        return []
    return dedupe_options(flatten_vocab(vocab))[:_MAX_VOCAB_ENTRIES]
