"""Single entry point for running WDK enrichment analyses, for experiment
endpoints, gene set endpoints, and AI tools alike."""

import asyncio
import json

from veupathdb.domain.parameters.values import ParamValue
from veupathdb.errors import (
    ValidationError,
    VEuPathDBError,
    VEuPathDBErrorCode,
)
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.wdk.factory import get_strategy_api
from veupathdb.wdk.strategy_api import StrategyAPI
from veupathdb.wdk.value_decoding import encode_params
from veupathdb.wdk.wdk_models import (
    NewStepSpec,
    WDKSearchConfig,
    WDKStepTree,
)
from veupathdb.wdk.wdk_parameters import WDKParameter

from veupathdb_mcp.controls.control_helpers import delete_temp_strategy
from veupathdb_mcp.wdk.enrichment.parser import (
    ANALYSIS_TYPE_MAP,
    GO_ONTOLOGY_MAP,
    parse_enrichment_response,
    parse_enrichment_terms,
)
from veupathdb_mcp.wdk.enrichment.types import (
    AmbiguousBackgroundError,
    BackgroundSource,
    EnrichmentAnalysisType,
    EnrichmentResult,
)
from veupathdb_mcp.wdk.params import (
    encode_vocab_value,
    extract_default_params,
    extract_vocab_values,
)

logger = get_logger(__name__)

# WDK step analysis is unreliable under parallel load, so batches are capped
# process-wide. The cap applies to batches, not to analyses within a batch.
_WDK_ENRICHMENT_SEMAPHORE = asyncio.Semaphore(3)

DEFAULT_ENRICHMENT_STRATEGY_NAME = "enrichment analysis"


class EnrichmentService:
    """Unified enrichment dispatcher.

    One instance serves one run, so the background it tests against is set
    when it is built.
    """

    def __init__(
        self,
        background: BackgroundSource | None = None,
        *,
        strategy_name: str = DEFAULT_ENRICHMENT_STRATEGY_NAME,
    ) -> None:
        self._background = background
        self._strategy_name = strategy_name

    def _background_organism(self) -> str | None:
        return None if self._background is None else self._background.organism

    async def run_batch(
        self,
        *,
        site_id: str,
        analysis_types: list[EnrichmentAnalysisType],
        step_id: int | None = None,
        search_name: str | None = None,
        record_type: str | None = None,
        parameters: dict[str, ParamValue] | None = None,
    ) -> tuple[list[EnrichmentResult], list[str]]:
        """Run multiple enrichment analyses concurrently on a shared step.

        Without a step id, one temporary step and strategy serves every
        analysis type, which keeps the WDK call count low.
        """
        errors: list[str] = []

        if step_id is not None:
            async with _WDK_ENRICHMENT_SEMAPHORE:
                return await self._run_analyses_on_step(
                    site_id,
                    step_id,
                    analysis_types,
                    errors,
                )

        if not search_name or parameters is None:
            msg = "Either step_id or search_name+parameters required"
            raise ValidationError(detail=msg)

        api = get_strategy_api(site_id)
        step = await api.create_step(
            NewStepSpec(
                search_name=search_name,
                search_config=WDKSearchConfig(parameters=encode_params(parameters)),
                custom_name="Enrichment target",
            ),
            record_type=record_type or "transcript",
        )
        shared_step_id = step.id
        root = WDKStepTree(step_id=shared_step_id)
        strategy_id: int | None = None

        async with _WDK_ENRICHMENT_SEMAPHORE:
            try:
                created = await api.create_strategy(
                    step_tree=root,
                    name=self._strategy_name,
                    description=None,
                    is_internal=True,
                )
                strategy_id = created.id

                return await self._run_analyses_on_step(
                    site_id,
                    shared_step_id,
                    analysis_types,
                    errors,
                )
            finally:
                await delete_temp_strategy(api, strategy_id)

    async def _execute_analysis(
        self,
        api: StrategyAPI,
        step_id: int,
        analysis_type: EnrichmentAnalysisType,
        analyzed_gene_count: int,
    ) -> EnrichmentResult:
        """Run one analysis on a step and parse the result.

        Parameter names and defaults come from the WDK analysis form metadata.
        The GO ontology and the background organism are the two overrides.
        """
        wdk_analysis_type = ANALYSIS_TYPE_MAP.get(analysis_type)
        if not wdk_analysis_type:
            return EnrichmentResult(
                analysis_type=analysis_type,
                terms=[],
                total_genes_analyzed=0,
                background_size=0,
            )

        # Analysis creation validates with no fill, so the form's values are the
        # only source of the parameters it demands.
        form_meta = await api.get_analysis_type(step_id, wdk_analysis_type)
        wdk_params: list[WDKParameter] = form_meta.search_data.parameters or []
        # The form lists the organisms in the result. The plugin tests one of
        # them against its own genome, so a result of several needs a choice.
        organisms = extract_vocab_values(wdk_params, "organism")
        if self._background_organism() is None and len(organisms) > 1:
            raise AmbiguousBackgroundError(organisms)
        analysis_params: JSONObject = extract_default_params(wdk_params)
        logger.debug(
            "Fetched analysis form defaults",
            analysis_type=wdk_analysis_type,
            param_names=list(analysis_params.keys()),
        )

        # The set of GO ontologies differs per site.
        if analysis_type in GO_ONTOLOGY_MAP:
            requested_ontology = GO_ONTOLOGY_MAP[analysis_type]
            available = extract_vocab_values(wdk_params, "goAssociationsOntologies")

            if available and requested_ontology not in available:
                logger.info(
                    "GO ontology not available on this site, skipping",
                    analysis_type=analysis_type,
                    requested=requested_ontology,
                    available=available,
                )
                return EnrichmentResult(
                    analysis_type=analysis_type,
                    terms=[],
                    total_genes_analyzed=0,
                    background_size=0,
                )

            analysis_params["goAssociationsOntologies"] = json.dumps(
                [requested_ontology]
            )

        # The organism parameter picks the background genome. WDK refuses one
        # that no gene in the result belongs to.
        background_organism = self._background_organism()
        if background_organism is not None:
            analysis_params["organism"] = encode_vocab_value(background_organism)

        logger.info(
            "Running enrichment analysis",
            analysis_type=analysis_type,
            wdk_type=wdk_analysis_type,
            step_id=step_id,
            params=analysis_params,
        )

        # The WDK step analysis endpoint returns 5xx under load, so retry it.
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                result = await api.run_step_analysis(
                    step_id=step_id,
                    analysis_type=wdk_analysis_type,
                    parameters=analysis_params,
                )
                break
            except VEuPathDBError as exc:
                last_err = exc
                err_str = str(exc)
                if "500" in err_str or "502" in err_str or "503" in err_str:
                    logger.warning(
                        "WDK enrichment 5xx, retrying",
                        attempt=attempt + 1,
                        analysis_type=wdk_analysis_type,
                        error=err_str,
                    )
                    await asyncio.sleep(2**attempt)
                    continue
                raise
        else:
            if last_err is not None:
                raise last_err
            raise VEuPathDBError(
                code=VEuPathDBErrorCode.INTERNAL_ERROR,
                title="Enrichment analysis failed",
                status=500,
                detail="the analysis did not answer after retries",
            )

        envelope = parse_enrichment_response(result)
        terms = parse_enrichment_terms(envelope.result_data, analysis_type)

        return EnrichmentResult(
            analysis_type=analysis_type,
            terms=terms,
            total_genes_analyzed=analyzed_gene_count,
        )

    async def _run_analyses_on_step(
        self,
        site_id: str,
        step_id: int,
        analysis_types: list[EnrichmentAnalysisType],
        errors: list[str],
    ) -> tuple[list[EnrichmentResult], list[str]]:
        """Run multiple analysis types on a single step concurrently.

        Analyses run in parallel to keep total time under the proxy timeout.
        The step's own count is the size every analysis reports as analyzed.
        """
        api = get_strategy_api(site_id)
        analyzed_gene_count = await api.get_step_count(step_id)

        async def _run_one(
            analysis_type: EnrichmentAnalysisType,
        ) -> EnrichmentResult:
            try:
                return await self._execute_analysis(
                    api, step_id, analysis_type, analyzed_gene_count
                )
            except (VEuPathDBError, RuntimeError) as exc:
                logger.warning(
                    "Enrichment failed",
                    analysis_type=analysis_type,
                    error=str(exc),
                )
                error_msg = str(exc)
                errors.append(f"{analysis_type}: {error_msg}")
                return EnrichmentResult(
                    analysis_type=analysis_type,
                    terms=[],
                    total_genes_analyzed=0,
                    background_size=0,
                    error=error_msg,
                )

        results = list(await asyncio.gather(*[_run_one(t) for t in analysis_types]))
        return results, errors
