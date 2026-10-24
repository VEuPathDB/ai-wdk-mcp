from collections.abc import Iterator

import httpx
import pytest
import respx
from tests._support.listed_searches import list_searches
from veupathdb import JSONObject
from veupathdb.auth_context import veupathdb_auth_token_ctx
from veupathdb.domain.parameters import StringValue
from veupathdb.domain.strategy import CombineOp, StrategyAst, StrategyStepNode

from veupathdb_mcp.catalog.searches import UnlistedSearchError
from veupathdb_mcp.wdk.plan_counts import compute_plan_step_counts

SERVICE = "/orthomcl.qa/service"
SEQUENCE_BOOLEAN = "boolean_question_SequenceRecordClasses_SequenceRecordClass"
LISTED = {
    "group": [
        "GroupsByNameList",
        "boolean_question_GroupRecordClasses_GroupRecordClass",
    ],
    "sequence": ["FromGroups", SEQUENCE_BOOLEAN],
}
PARAMS: dict[str, list[JSONObject]] = {
    "GroupsByNameList": [{"name": "group_names", "type": "string"}],
    "FromGroups": [{"name": "group_answer", "type": "input-step"}],
    SEQUENCE_BOOLEAN: [
        {
            "name": "bq_left_op_SequenceRecordClasses_SequenceRecordClass",
            "type": "input-step",
        },
        {
            "name": "bq_right_op_SequenceRecordClasses_SequenceRecordClass",
            "type": "input-step",
        },
        {"name": "bq_operator", "type": "string"},
    ],
}


class OrthoSite:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self._next_step = 100

    def _search(self, record_type: str, name: str) -> httpx.Response:
        if name not in LISTED.get(record_type, []):
            return httpx.Response(404, text=f"{name} is not a {record_type} search")
        body: JSONObject = {
            "searchData": {
                "urlSegment": name,
                "paramNames": [str(p["name"]) for p in PARAMS[name]],
                "parameters": list(PARAMS[name]),
            },
            "validation": {"level": "DISPLAYABLE", "isValid": True},
        }
        return httpx.Response(200, json=body)

    def _report(self, record_type: str, name: str) -> httpx.Response:
        if name not in LISTED.get(record_type, []):
            return httpx.Response(404, text=f"{name} is not a {record_type} search")
        meta = {"totalCount": 12, "responseCount": 0}
        return httpx.Response(200, json={"meta": meta, "records": []})

    def _strategy(self) -> httpx.Response:
        steps: JSONObject = {
            str(step_id): {
                "id": step_id,
                "searchName": "FromGroups",
                "searchConfig": {"parameters": {}},
                "estimatedSize": step_id,
            }
            for step_id in range(101, self._next_step + 1)
        }
        return httpx.Response(
            200,
            json={
                "strategyId": 7000,
                "name": "step counts",
                "rootStepId": self._next_step,
                "stepTree": {"stepId": self._next_step},
                "steps": steps,
            },
        )

    def _new_step(self) -> httpx.Response:
        self._next_step += 1
        return httpx.Response(200, json={"id": self._next_step})

    def _answer(self, method: str, parts: list[str]) -> httpx.Response:
        match method, parts:
            case "GET", ["users", "current"]:
                answer = httpx.Response(200, json={"id": 42, "isGuest": False})
            case "GET", ["record-types", record_type, "searches", name]:
                answer = self._search(record_type, name)
            case "POST", ["record-types", record_type, "searches", name, *_]:
                answer = self._report(record_type, name)
            case "GET", ["record-types", record_type, "searches"]:
                listed = [{"urlSegment": name} for name in LISTED[record_type]]
                answer = httpx.Response(200, json=listed)
            case "POST", ["users", "42", "steps"]:
                answer = self._new_step()
            case "POST", ["users", "42", "strategies"]:
                answer = httpx.Response(200, json={"id": 7000})
            case "GET", ["users", "42", "strategies", "7000"]:
                answer = self._strategy()
            case "DELETE", ["users", "42", "strategies", "7000"]:
                answer = httpx.Response(204)
            case _:
                answer = httpx.Response(404, text="no such route")
        return answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.startswith(SERVICE):
            return httpx.Response(200, text="ok")
        path = request.url.path.removeprefix(SERVICE)
        query = request.url.query.decode()
        self.requests.append(f"{request.method} {path}{'?' + query if query else ''}")
        return self._answer(request.method, path.strip("/").split("/"))


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Iterator[OrthoSite]:
    list_searches(monkeypatch, LISTED)
    answering = OrthoSite()
    reset = veupathdb_auth_token_ctx.set("registered-token")
    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=answering)
        yield answering
    veupathdb_auth_token_ctx.reset(reset)


def _groups(step_id: str, search_name: str = "GroupsByNameList") -> StrategyStepNode:
    return StrategyStepNode(
        id=step_id,
        search_name=search_name,
        parameters={"group_names": StringValue(value="OG7_0000001")},
    )


def _proteins(step_id: str, groups: StrategyStepNode) -> StrategyStepNode:
    return StrategyStepNode(id=step_id, search_name="FromGroups", primary_input=groups)


async def test_a_group_leaf_under_a_sequence_root_is_created_as_a_group_step(
    site: OrthoSite,
) -> None:
    plan = StrategyAst(
        record_type="sequence", root=_proteins("proteins", _groups("groups"))
    )

    counts = await compute_plan_step_counts(plan, "orthomcl")

    assert counts == {"groups": 101, "proteins": 102}
    assert site.requests == [
        "GET /record-types/group/searches/GroupsByNameList?expandParams=true",
        "GET /users/current",
        "POST /users/42/steps",
        "GET /record-types/sequence/searches/FromGroups?expandParams=true",
        "POST /users/42/steps",
        "POST /users/42/strategies",
        "GET /users/42/strategies/7000",
        "DELETE /users/42/strategies/7000",
    ]


async def test_a_combine_of_proteins_is_created_under_the_class_of_its_inputs(
    site: OrthoSite,
) -> None:
    plan = StrategyAst(
        record_type="sequence",
        root=StrategyStepNode(
            id="both",
            search_name="__combine__",
            operator=CombineOp.INTERSECT,
            primary_input=_proteins("left", _groups("a")),
            secondary_input=_proteins("right", _groups("b")),
        ),
    )

    await compute_plan_step_counts(plan, "orthomcl")

    reads = list(
        dict.fromkeys(r for r in site.requests if r.startswith("GET /record-types/"))
    )
    assert reads == [
        "GET /record-types/group/searches/GroupsByNameList?expandParams=true",
        "GET /record-types/sequence/searches/FromGroups?expandParams=true",
        "GET /record-types/sequence/searches",
        f"GET /record-types/sequence/searches/{SEQUENCE_BOOLEAN}?expandParams=true",
    ]
    assert site.requests.count("POST /users/42/steps") == 5


async def test_a_step_whose_search_no_record_type_lists_is_refused_before_a_request(
    site: OrthoSite,
) -> None:
    plan = StrategyAst(
        record_type="sequence",
        root=_proteins("proteins", _groups("groups", "GroupsByNothing")),
    )

    with pytest.raises(
        UnlistedSearchError, match="orthomcl lists no search GroupsByNothing"
    ):
        await compute_plan_step_counts(plan, "orthomcl")

    assert site.requests == []


async def test_a_lone_group_leaf_stated_as_sequence_is_counted_as_a_group_search(
    site: OrthoSite,
) -> None:
    plan = StrategyAst(record_type="sequence", root=_groups("groups"))

    counts = await compute_plan_step_counts(plan, "orthomcl")

    assert counts == {"groups": 12}
    assert site.requests == [
        "POST /record-types/group/searches/GroupsByNameList/reports/standard"
    ]


async def test_a_lone_leaf_no_record_type_lists_is_refused_before_a_request(
    site: OrthoSite,
) -> None:
    plan = StrategyAst(record_type="group", root=_groups("groups", "GroupsByNothing"))

    with pytest.raises(
        UnlistedSearchError, match="orthomcl lists no search GroupsByNothing"
    ):
        await compute_plan_step_counts(plan, "orthomcl")

    assert site.requests == []
