"""A parameter sheet whose organism parameter is the one its declaration marks."""

from __future__ import annotations

from veupathdb.wdk import WDKParameter

from veupathdb_mcp.catalog import ParameterInfo, format_param_info_typed


def param_infos(params: list[WDKParameter]) -> list[ParameterInfo]:
    organism = next((p.name for p in params if p.is_organism), None)
    return format_param_info_typed(params, organism=organism)
