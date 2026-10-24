import contextlib
import re
from collections.abc import Awaitable, Callable, Iterator

import pytest
from fastmcp import Client
from tests._support.control_run_wdk import (
    TESTED_STEP,
    RunFakeAPI,
    StepRunFakeAPI,
    gene_records,
    patch_control_account,
    patch_step_run,
)
from tests._support.dataset_trap import DatasetCreatedError, DatasetTrap
from tests._support.enrichment_wdk import GENE_SEARCHES, GO_ROW, FakeStrategyAPI
from tests._support.listed_searches import list_searches
from tests.unit.audit.test_no_chat_dataset import CHECKS
from tests.unit.gene_lookup import test_a_lookup_reads_by_record
from tests.unit.test_served_results_round_trip import RECORDED
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.wdk import WDKAnswer, WDKSearch

from veupathdb_mcp import server
from veupathdb_mcp.catalog import (
    experiments,
    parameters,
    search_inspection,
    searches,
    sites,
)
from veupathdb_mcp.catalog.experiment_card import ExperimentCard
from veupathdb_mcp.catalog.overview_formatting import SearchOverviewResult
from veupathdb_mcp.catalog.param_dag import ResolvedParams
from veupathdb_mcp.catalog.param_validation import ValidatedParams
from veupathdb_mcp.catalog.search_inspection import SearchInspection
from veupathdb_mcp.gene_lookup import GeneResult, lookup
from veupathdb_mcp.tools import catalog_tools, user_tools
from veupathdb_mcp.wdk import gene_set_steps, step_preview
from veupathdb_mcp.wdk.enrichment import service
from veupathdb_mcp.wdk.step_size import StepCountResult

SITE = "plasmodb"
GENE = "PF3D7_0100100"
DATASET_WRITE = (
    "writes one dataset into the calling user's WDK account, which WDK cannot delete."
)
WRITERS = [
    "create_gene_set_step",
    "enrich_gene_ids",
    "run_control_tests_on_search",
    "run_control_tests_on_step",
]

type Run = Callable[[], Awaitable[object]]
type Drive = Callable[[pytest.MonkeyPatch], Run]


def answering(
    monkeypatch: pytest.MonkeyPatch, owner: object, name: str, value: object
) -> None:
    async def answer(*_: object, **__: object) -> object:
        return value

    monkeypatch.setattr(owner, name, answer)


def inspection() -> SearchInspection:
    return SearchInspection(
        record_type="transcript",
        definition=WDKSearch(url_segment="GenesByText", parameters=[]),
        overview=SearchOverviewResult(
            search_name="GenesByText",
            display_name="GenesByText",
            description="",
            record_type="transcript",
        ),
    )


def catalog(owner: object, name: str, value: object, run: Callable[[], Run]) -> Drive:
    def drive(monkeypatch: pytest.MonkeyPatch) -> Run:
        answering(monkeypatch, owner, name, value)
        return run()

    return drive


def recorded(tool: str) -> Drive:
    return lambda monkeypatch: lambda: RECORDED[tool](monkeypatch)


def gene_split(monkeypatch: pytest.MonkeyPatch) -> Run:
    return CHECKS["audit_gene_split"](monkeypatch)


def resolve(monkeypatch: pytest.MonkeyPatch) -> Run:
    test_a_lookup_reads_by_record.replay(monkeypatch)
    return lambda: user_tools.resolve_gene_ids_to_records(
        SITE, test_a_lookup_reads_by_record.RESOLVED
    )


def lookup_records(monkeypatch: pytest.MonkeyPatch) -> Run:
    test_a_lookup_reads_by_record.replay(monkeypatch)
    [gene] = test_a_lookup_reads_by_record.HYDRATED
    answering(
        monkeypatch,
        lookup,
        "fetch_site_search_genes",
        ([GeneResult(gene_id=gene)], [], 1),
    )
    return lambda: user_tools.lookup_gene_records(SITE, gene)


def enrichment_site(monkeypatch: pytest.MonkeyPatch) -> FakeStrategyAPI:
    api = FakeStrategyAPI()
    api.rows["go-enrichment"] = [GO_ROW]
    list_searches(monkeypatch, GENE_SEARCHES)
    monkeypatch.setattr(service, "get_strategy_api", lambda site_id: api)
    monkeypatch.setattr(gene_set_steps, "get_strategy_api", lambda site_id: api)
    gene_set_steps._FROZEN_STEPS.clear()
    return api


def enrich(monkeypatch: pytest.MonkeyPatch) -> Run:
    enrichment_site(monkeypatch)
    return lambda: user_tools.enrich_gene_ids(SITE, [GENE])


def gene_set_step(monkeypatch: pytest.MonkeyPatch) -> Run:
    enrichment_site(monkeypatch)
    return lambda: user_tools.create_gene_set_step(SITE, [GENE])


def search_controls(monkeypatch: pytest.MonkeyPatch) -> Run:
    patch_control_account(monkeypatch, RunFakeAPI())
    return lambda: user_tools.run_control_tests_on_search(
        SITE, "GenesByMolecularWeight", {}, positive_controls=[GENE]
    )


def step_controls(monkeypatch: pytest.MonkeyPatch) -> Run:
    patch_step_run(monkeypatch, StepRunFakeAPI(gene_records(GENE)))
    return lambda: user_tools.run_control_tests_on_step(
        SITE, TESTED_STEP, positive_controls=[GENE]
    )


class _Results:
    async def get_download_url(
        self, step_id: int, output_format: str, attributes: object
    ) -> str:
        return f"https://qa.plasmodb.org/temporary-results/{step_id}.{output_format}"


def download_url(monkeypatch: pytest.MonkeyPatch) -> Run:
    monkeypatch.setattr(step_preview, "get_results_api", lambda site_id: _Results())
    return lambda: user_tools.get_step_download_url(SITE, 42)


def step_gene_ids(monkeypatch: pytest.MonkeyPatch) -> Run:
    monkeypatch.setattr(user_tools, "get_strategy_api", lambda site_id: site_id)
    answering(monkeypatch, user_tools, "fetch_gene_ids_from_step", [GENE])
    return lambda: user_tools.get_step_gene_ids(SITE, 42)


CARD = ExperimentCard(
    site_id="cryptodb",
    dataset_id="DS_c1",
    name="Oocyst excystation time course",
    organism="Cryptosporidium parvum Iowa II",
    assay="RNASeq",
    attribution="Lippuner et al. 2018",
    record_url="https://qa.cryptodb.org/cryptodb.qa/app/record/dataset/DS_c1",
)

DRIVERS: dict[str, Drive] = {
    "list_record_types": catalog(
        sites,
        "get_record_types",
        [],
        lambda: lambda: catalog_tools.list_record_types(SITE),
    ),
    "search_for_searches": catalog(
        searches,
        "search_for_searches",
        [],
        lambda: lambda: catalog_tools.search_for_searches(SITE, "kinase"),
    ),
    "browse_search_categories": catalog(
        catalog_tools,
        "list_search_categories",
        [],
        lambda: lambda: catalog_tools.browse_search_categories(SITE),
    ),
    "list_searches": catalog(
        catalog_tools,
        "list_search_listings",
        [],
        lambda: lambda: catalog_tools.list_searches(SITE),
    ),
    "list_transforms": catalog(
        catalog_tools,
        "list_transform_listings",
        [],
        lambda: lambda: catalog_tools.list_transforms(SITE),
    ),
    "lookup_phyletic_codes": catalog(
        parameters,
        "lookup_phyletic_codes",
        {},
        lambda: lambda: catalog_tools.lookup_phyletic_codes(SITE, "pfal"),
    ),
    "search_example_plans": catalog(
        catalog_tools,
        "rank_example_plans",
        [],
        lambda: lambda: catalog_tools.search_example_plans(SITE, "kinases"),
    ),
    "get_search_overview": catalog(
        search_inspection,
        "inspect_search",
        inspection(),
        lambda: lambda: catalog_tools.get_search_overview(SITE, "GenesByText"),
    ),
    "get_search_param_specs": catalog(
        search_inspection,
        "inspect_search",
        inspection(),
        lambda: lambda: catalog_tools.get_search_param_specs(SITE, "GenesByText"),
    ),
    "get_parameter_options": catalog(
        search_inspection,
        "read_parameter_options",
        {},
        lambda: (
            lambda: catalog_tools.get_parameter_options(
                SITE, "GenesByTaxon", "organism"
            )
        ),
    ),
    "validate_search_parameters": catalog(
        catalog_tools,
        "validate_parameters",
        ValidatedParams(params={}, record_class="transcript"),
        lambda: (
            lambda: catalog_tools.validate_search_parameters(SITE, "GenesByText", {})
        ),
    ),
    "resolve_search_parameters": catalog(
        catalog_tools,
        "resolve_params_with_intent",
        ResolvedParams(),
        lambda: lambda: catalog_tools.resolve_search_parameters(SITE, "GenesByText"),
    ),
    "search_catalog_index": catalog(
        catalog_tools,
        "search_index",
        [],
        lambda: lambda: catalog_tools.search_catalog_index(SITE, "kinase"),
    ),
    "rank_experiments_elsewhere": catalog(
        experiments,
        "rank_experiments_elsewhere",
        [],
        lambda: lambda: catalog_tools.rank_experiments_elsewhere(SITE, "excystation"),
    ),
    "read_experiment": catalog(
        experiments,
        "read_experiment",
        CARD,
        lambda: lambda: catalog_tools.read_experiment("cryptodb", "DS_c1"),
    ),
    "lookup_gene_records": lookup_records,
    "resolve_gene_ids_to_records": resolve,
    "get_ai_expression_summary": catalog(
        user_tools,
        "get_gene_expression_summary",
        None,
        lambda: lambda: user_tools.get_ai_expression_summary(SITE, GENE),
    ),
    "get_step_estimated_size": catalog(
        user_tools,
        "get_estimated_size_for_site",
        StepCountResult(step_id=42, count=3),
        lambda: lambda: user_tools.get_step_estimated_size(SITE, 42),
    ),
    "get_step_sample_records": catalog(
        user_tools,
        "step_sample_answer",
        WDKAnswer.model_validate({"meta": {"totalCount": 0}, "records": []}),
        lambda: lambda: user_tools.get_step_sample_records(SITE, 42, "transcript"),
    ),
    "get_step_download_url": download_url,
    "get_step_gene_ids": step_gene_ids,
    "count_plan_steps": catalog(
        user_tools,
        "compute_plan_step_counts",
        {},
        lambda: lambda: user_tools.count_plan_steps(SITE, None),
    ),
    "run_control_tests_on_step": step_controls,
    "create_gene_set_step": gene_set_step,
    "run_control_tests_on_search": search_controls,
    "enrich_gene_ids": enrich,
    "audit_gene_split": gene_split,
    **{name: recorded(name) for name in RECORDED},
}


async def descriptions() -> dict[str, str]:
    async with Client(server.build_server()) as client:
        return {
            tool.name: re.sub(r"\s+", " ", tool.description or "")
            for tool in await client.list_tools()
        }


@pytest.fixture(autouse=True)
def researcher() -> Iterator[None]:
    reset = veupathdb_auth_token_ctx.set("researcher.registered.token")
    yield
    veupathdb_auth_token_ctx.reset(reset)


async def test_every_served_tool_is_driven() -> None:
    assert sorted(DRIVERS) == sorted(await descriptions())


async def test_the_tools_that_write_a_dataset_are_the_tools_that_say_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writers: list[str] = []
    for name in sorted(DRIVERS):
        with monkeypatch.context() as patched:
            run = DRIVERS[name](patched)
            trap = DatasetTrap(patched)
            with contextlib.suppress(DatasetCreatedError):
                await run()
            if trap.calls:
                writers.append(name)

    described = sorted(
        name for name, text in (await descriptions()).items() if DATASET_WRITE in text
    )
    assert writers == described == WRITERS
