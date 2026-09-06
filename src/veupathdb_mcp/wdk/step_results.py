"""Shared service for browsing WDK step results: attributes, records,
distributions, and step analyses."""

from veupathdb.domain.wdk_values import WDKSortDirection
from veupathdb.errors import VEuPathDBError
from veupathdb.json_types import JSONObject
from veupathdb.logging import get_logger
from veupathdb.wdk.factory import get_site, get_strategy_api
from veupathdb.wdk.strategy_api.api import StrategyAPI
from veupathdb.wdk.wdk_models import (
    WDKAnswer,
    WDKColumnDistribution,
    WDKSortSpec,
    WDKStrategyDetails,
)

from veupathdb_mcp.wdk.helpers import (
    build_attribute_list,
    extract_detail_attributes,
    merge_analysis_params,
    order_primary_key,
)
from veupathdb_mcp.wdk.step_results_models import (
    AttributesResponse,
    RecordAttribute,
    RecordDetailResponse,
)

logger = get_logger(__name__)


class StepResultsService:
    """Provides read-only access to the results of one WDK step."""

    def __init__(
        self,
        api: StrategyAPI,
        *,
        step_id: int,
        record_type: str,
    ) -> None:
        self._api = api
        self._step_id = step_id
        self._record_type = record_type

    async def get_attributes(self) -> AttributesResponse:
        """Get available attributes for the record type."""
        info = await self._api.get_record_type_info(self._record_type)
        attrs = info.attributes or list((info.attributes_map or {}).values())
        raw = build_attribute_list(attrs)
        return AttributesResponse(
            attributes=[RecordAttribute.model_validate(a) for a in raw],
            record_type=self._record_type,
        )

    async def get_records(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        sort: str | None = None,
        direction: WDKSortDirection = "ASC",
        attributes: list[str] | None = None,
    ) -> WDKAnswer:
        """Get paginated result records."""
        sorting: list[WDKSortSpec] | None = None
        if sort:
            sorting = [WDKSortSpec(attribute_name=sort, direction=direction)]

        return await self._api.get_step_records(
            step_id=self._step_id,
            attributes=attributes,
            pagination={"offset": offset, "numRecords": limit},
            sorting=sorting,
        )

    async def get_distribution(self, attribute_name: str) -> WDKColumnDistribution:
        """Get distribution data for an attribute."""
        return await self._api.get_column_distribution(self._step_id, attribute_name)

    async def list_analysis_types(self) -> JSONObject:
        """List available WDK step analysis types."""
        types = await self._api.list_analysis_types(self._step_id)
        return {"analysisTypes": [t.model_dump(by_alias=True) for t in types]}

    async def get_strategy(self, strategy_id: int) -> WDKStrategyDetails:
        """Get the WDK strategy tree."""
        return await self._api.get_strategy(strategy_id)

    async def run_analysis_raw(
        self,
        analysis_name: str,
        parameters: JSONObject,
    ) -> tuple[JSONObject, JSONObject]:
        """Run a WDK step analysis with merged defaults.

        Returns the raw result and the merged parameters.
        """
        form_meta = await self._api.get_analysis_type(self._step_id, analysis_name)
        params = merge_analysis_params(
            form_meta.search_data.parameters or [], parameters
        )

        logger.info(
            "Running WDK step analysis",
            step_id=self._step_id,
            analysis_type=analysis_name,
        )

        result = await self._api.run_step_analysis(
            step_id=self._step_id,
            analysis_type=analysis_name,
            parameters=params,
        )

        return result, params

    async def get_record_detail(
        self,
        primary_key: list[dict[str, str]],
        site_id: str,
    ) -> RecordDetailResponse:
        """Get a single record's full details by primary key."""
        pk_parts = primary_key
        detail_attrs: list[str] = []
        display_names: dict[str, str] = {}
        try:
            info = await self._api.get_record_type_info(self._record_type)

            pk_refs = info.primary_key_column_refs
            if pk_refs:
                site = get_site(site_id)
                pk_parts = order_primary_key(
                    pk_parts,
                    pk_refs,
                    pk_defaults={"project_id": site.project_id},
                )

            attrs = info.attributes or list((info.attributes_map or {}).values())
            detail_attrs, display_names = extract_detail_attributes(attrs)
        except VEuPathDBError:
            logger.warning(
                "Failed to fetch record type info; falling back to raw PK",
                record_type=self._record_type,
                site_id=site_id,
                exc_info=True,
            )

        record_instance = await self._api.get_single_record(
            record_type=self._record_type,
            primary_key=pk_parts,
            attributes=detail_attrs or None,
        )
        return RecordDetailResponse(
            display_name=record_instance.display_name,
            id=record_instance.id,
            record_class_name=record_instance.record_class_name,
            attributes=record_instance.attributes,
            attribute_names=display_names,
            tables=record_instance.tables,
            table_errors=record_instance.table_errors,
        )


def step_results_service(
    *,
    site_id: str,
    step_id: int,
    record_type: str,
) -> StepResultsService:
    """The reader for one built step of a site."""
    return StepResultsService(
        get_strategy_api(site_id),
        step_id=step_id,
        record_type=record_type,
    )
