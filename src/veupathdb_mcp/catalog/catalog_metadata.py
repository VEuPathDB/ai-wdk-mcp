"""Catalog metadata helpers: dataset cards, ontology categories, record type processing."""

from pydantic import ConfigDict, Field
from veupathdb import JSONObject, get_logger
from veupathdb.errors import VEuPathDBError
from veupathdb.model import CamelModel
from veupathdb.wdk import VEuPathDBClient, WDKRecordType, WDKSearch, get_site_router

from veupathdb_mcp.catalog.disk_cache import DatasetReport
from veupathdb_mcp.catalog.experiment_card import ExperimentCard

logger = get_logger(__name__)


DATASET_REPORT_PATH = "/record-types/dataset/searches/AllDatasets/reports/standard"

# The attributes and tables a card reads, and nothing else.
_CARD_ATTRIBUTES = [
    "primary_key",
    "display_name",
    "type",
    "newcategory",
    "organism_prefix",
    "short_attribution",
    "summary",
]
_CARD_TABLES = ["References", "Publications"]


def dataset_report_request() -> JSONObject:
    """The body of the report request a catalog build posts."""
    return {
        "searchConfig": {"parameters": {}},
        "reportConfig": {
            "attributes": list(_CARD_ATTRIBUTES),
            "tables": list(_CARD_TABLES),
        },
    }


async def load_dataset_metadata(
    client: VEuPathDBClient, site_id: str
) -> list[ExperimentCard]:
    """Read every dataset the site publishes as a card. Return none on failure."""
    try:
        answer = await client.post(DATASET_REPORT_PATH, json=dataset_report_request())
        report = DatasetReport.model_validate(answer)
    except VEuPathDBError, OSError, ValueError, TypeError:
        logger.warning(
            "Failed to load dataset metadata (non-fatal)",
            site_id=site_id,
            exc_info=True,
        )
        return []
    site = get_site_router().get_site(site_id)
    cards = [record.card(site) for record in report.records if record.dataset_id]
    logger.info("Dataset metadata loaded", site_id=site_id, datasets=len(cards))
    return cards


class OntologyCategories:
    """Mappings from search name to ontology category and label."""

    __slots__ = ("available_categories", "search_categories", "search_category_labels")

    def __init__(
        self,
        search_categories: dict[str, str],
        available_categories: set[str],
        search_category_labels: dict[str, str],
    ) -> None:
        self.search_categories = search_categories
        self.available_categories = available_categories
        self.search_category_labels = search_category_labels


class _OntologyNodeProps(CamelModel):
    """Properties on a Categories ontology node."""

    model_config = ConfigDict(extra="ignore")

    label: list[str] = Field(default_factory=list)
    eu_path_db_alternative_term: list[str] = Field(
        default_factory=list,
        alias="EuPathDB alternative term",
    )

    @property
    def label_str(self) -> str:
        return str(self.label[0]) if self.label else ""

    @property
    def display_name(self) -> str:
        if self.eu_path_db_alternative_term:
            return str(self.eu_path_db_alternative_term[0])
        return self.label_str


class _OntologyNode(CamelModel):
    """One node of the Categories ontology tree."""

    model_config = ConfigDict(extra="ignore")

    properties: _OntologyNodeProps = Field(default_factory=_OntologyNodeProps)
    children: list[_OntologyNode] = Field(default_factory=list)


class _OntologyResponse(CamelModel):
    """Top-level Categories ontology response."""

    model_config = ConfigDict(extra="ignore")

    tree: _OntologyNode = Field(default_factory=_OntologyNode)


async def load_ontology_categories(
    client: VEuPathDBClient, site_id: str
) -> OntologyCategories:
    """Map each search to its ontology subcategory and readable label.

    Return empty mappings on failure.
    """
    search_categories: dict[str, str] = {}
    search_category_labels: dict[str, str] = {}
    available_categories: set[str] = set()

    try:
        data = await client.get("/ontologies/Categories")
        response = _OntologyResponse.model_validate(data)
        tree = response.tree

        def walk(
            node: _OntologyNode,
            ancestors: list[str],
            ancestor_display_names: list[str],
        ) -> None:
            label = node.properties.label_str
            display_name = node.properties.display_name

            if not node.children and "GeneQuestions" in label:
                search_name = label.split(".")[-1]
                for ancestor in reversed(ancestors):
                    if ancestor.startswith("searchCategory-"):
                        search_categories[search_name] = ancestor
                        available_categories.add(ancestor)
                        break
                for anc_display in reversed(ancestor_display_names):
                    if anc_display and not anc_display.startswith("searchCategory-"):
                        search_category_labels[search_name] = anc_display
                        break

            for child in node.children:
                walk(
                    child, [*ancestors, label], [*ancestor_display_names, display_name]
                )

        walk(tree, [], [])
        logger.info(
            "Ontology categories loaded",
            site_id=site_id,
            categorized_searches=len(search_categories),
            categories=len(available_categories),
            labeled_searches=len(search_category_labels),
        )
    except VEuPathDBError, OSError, ValueError, TypeError:
        logger.warning(
            "Failed to load ontology categories (non-fatal)",
            site_id=site_id,
            exc_info=True,
        )
    return OntologyCategories(
        search_categories=search_categories,
        available_categories=available_categories,
        search_category_labels=search_category_labels,
    )


async def load_searches_for_rt(
    client: VEuPathDBClient, rt_name: str
) -> list[WDKSearch] | None:
    """Fetch searches for a record type. Return None on error."""
    try:
        return await client.get_searches(rt_name)
    except VEuPathDBError as e:
        logger.warning(
            "Failed to load searches",
            record_type=rt_name,
            error=str(e),
        )
        return None


def process_record_type_entry(
    rt: WDKRecordType,
    *,
    expanded_supported: bool,
) -> tuple[WDKRecordType, list[WDKSearch] | None] | None:
    """Return the record type and its inline searches.

    Return None to skip the entry. A None search list means the searches need a
    separate fetch.
    """
    if not rt.url_segment:
        return None

    if expanded_supported and rt.searches is not None:
        return rt, rt.searches
    return rt, None
