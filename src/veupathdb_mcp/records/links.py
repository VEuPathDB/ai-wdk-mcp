"""What a link into a configured site's web app shows, read from the site."""

from __future__ import annotations

from typing import Literal

from veupathdb.model import CamelModel
from veupathdb.text import strip_html_tags
from veupathdb.wdk import (
    ImportLink,
    OtherPageLink,
    RecordLink,
    SearchFormLink,
    SearchResultLink,
    StrategyLink,
    WDKSearch,
    parse_site_link,
)

from veupathdb_mcp.record_fields import GENE_RECORD_TYPES
from veupathdb_mcp.records.columns import (
    NameKind,
    UnknownNameError,
    UnreadableRecordError,
    searches_of,
)
from veupathdb_mcp.records.table import SearchTable, TableRequest, read_search_table

type LinkKind = Literal[
    "search_result",
    "search_form",
    "record",
    "strategy",
    "import",
    "other_page",
    "outside",
]


class LinkReading(CamelModel):
    """What one link shows: plain sentences, and the rows when it shows a table."""

    url: str
    site_id: str | None
    kind: LinkKind
    summary: str
    table: SearchTable | None = None


def _given(parameters: dict[str, str]) -> str:
    if not parameters:
        return "with no parameter values in the link"
    return "with " + "; ".join(
        f"{name} = {value}" for name, value in parameters.items()
    )


async def _search(link: SearchResultLink | SearchFormLink) -> WDKSearch:
    searches = await searches_of(link.site_id, link.record_type)
    found = next((s for s in searches if s.url_segment == link.search_name), None)
    if found is None:
        names = [s.url_segment for s in searches]
        where = f"The {link.record_type} records of {link.site_id}"
        raise UnknownNameError(NameKind.SEARCH, link.search_name, names, where)
    return found


async def _result(url: str, link: SearchResultLink) -> LinkReading:
    opening = (
        f"The link runs {link.search_name} on {link.site_id} {_given(link.parameters)}."
    )
    search = await _search(link)
    if link.record_type in GENE_RECORD_TYPES:
        return LinkReading(
            url=url,
            site_id=link.site_id,
            kind=link.kind,
            summary=(
                f"{opening} It shows {search.display_name}, a gene result. A gene "
                "result is built as a strategy step, not read as a table."
            ),
        )
    table = await read_search_table(
        link.site_id,
        TableRequest(
            record_type=link.record_type,
            search_name=link.search_name,
            parameters=link.parameters,
        ),
    )
    return LinkReading(
        url=url,
        site_id=link.site_id,
        kind=link.kind,
        summary=f"{opening} It shows {search.display_name}. {table.note}",
        table=table,
    )


async def _form(url: str, link: SearchFormLink) -> LinkReading:
    search = await _search(link)
    about = strip_html_tags(search.summary or search.description).strip()
    summary = (
        f"The link opens the form of {search.display_name} ({link.search_name}) on "
        f"{link.site_id} {_given(link.parameters)}. It returns {link.record_type} "
        f"records. Its parameters: {', '.join(search.param_names) or 'none'}."
    )
    return LinkReading(
        url=url,
        site_id=link.site_id,
        kind=link.kind,
        summary=f"{summary} {about}".strip(),
    )


def _sentence(link: RecordLink | StrategyLink | ImportLink | OtherPageLink) -> str:
    match link:
        case RecordLink():
            key = "/".join(link.primary_key)
            return (
                f"The link shows the {link.record_type} record {key} on {link.site_id}."
            )
        case StrategyLink():
            step = f", open at step {link.step_id}" if link.step_id else ""
            return (
                f"The link opens strategy {link.strategy_id}{step} on {link.site_id}. "
                "A strategy belongs to one account: it is read from the "
                "researcher's own strategies, and a strategy of another account "
                "is read from its share link."
            )
        case ImportLink():
            return (
                f"The link shares a strategy on {link.site_id} by its signature "
                f"{link.signature}."
            )
        case OtherPageLink():
            return (
                f"The link shows the page {link.path} on {link.site_id}, which holds "
                "no search, record or strategy."
            )


async def read_site_link(url: str) -> LinkReading:
    """Read what one link into a configured site's web app shows."""
    link = parse_site_link(url)
    if link is None:
        return LinkReading(
            url=url,
            site_id=None,
            kind="outside",
            summary=(
                "The link is not on a site this deployment reads, so nothing was "
                "read from it."
            ),
        )
    try:
        match link:
            case SearchResultLink():
                return await _result(url, link)
            case SearchFormLink():
                return await _form(url, link)
            case RecordLink() | StrategyLink() | ImportLink() | OtherPageLink():
                return LinkReading(
                    url=url,
                    site_id=link.site_id,
                    kind=link.kind,
                    summary=_sentence(link),
                )
    except UnreadableRecordError as exc:
        return LinkReading(
            url=url,
            site_id=link.site_id,
            kind=link.kind,
            summary=f"The link names {link.kind.replace('_', ' ')} on {link.site_id}, "
            f"but it could not be read: {exc}",
        )
