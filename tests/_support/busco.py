from pathlib import Path

from pydantic import TypeAdapter
from veupathdb import JSONObject

FIXTURES = Path(__file__).resolve().parents[1] / "unit/audit/fixtures"
NF135 = "Plasmodium falciparum NF135.C10"
_RECORDS: TypeAdapter[list[JSONObject]] = TypeAdapter(list[JSONObject])


def served_organisms(site: str = "plasmodb") -> list[JSONObject]:
    return _RECORDS.validate_json((FIXTURES / f"busco_{site}.json").read_text())
