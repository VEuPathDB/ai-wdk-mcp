"""Record the gene and transcript record reads, and the JBrowse store reads, that the
record-read and staged intron tests replay from QA sites.

Run it from the repository root as the test account (WDK_TEST_TOKEN, or
WDK_TEST_EMAIL and WDK_TEST_PASSWORD):
``uv run python -m scripts.record_audit_records [--out DIR]``.
"""

import argparse
import asyncio
import base64
import lzma
import statistics
from pathlib import Path

import httpx
from pydantic import Base64Bytes, BaseModel, ConfigDict, Field, JsonValue
from scripts.record_audit_fixtures import FIXTURES, act_as_the_test_account
from veupathdb import MetricAttrs, NoObserver, set_observer
from veupathdb.devtools import use_qa_sites
from veupathdb.errors import VEuPathDBError
from veupathdb.jbrowse import (
    BigWigReader,
    GenomeReader,
    JBrowseClient,
    TabixReader,
    TrackReadError,
)
from veupathdb.wdk import (
    WDKRecordInstance,
    close_all_clients,
    get_site,
    get_strategy_api,
    get_wdk_client,
)

from veupathdb_mcp.audit.gene_models import (
    MODEL_TABLE,
    ORGANISM_ATTRIBUTE,
    GeneModel,
)
from veupathdb_mcp.audit.genes import (
    ORTHOLOG_TABLE,
    PROTEIN_ATTRIBUTE,
    OrthologGroup,
    OrthologRow,
)
from veupathdb_mcp.audit.intron_coverage import (
    coverage_choice,
    read_depth,
)
from veupathdb_mcp.audit.intron_evidence import (
    peptide_track,
)
from veupathdb_mcp.audit.introns_inputs import (
    INTRON_JUNCTION_PAD,
    INTRON_READ_THROUGH,
    ortholog_choice,
)
from veupathdb_mcp.audit.record_reads import (
    RECORD_ATTRIBUTES,
    TRANSCRIPT_RECORD,
    TRANSCRIPT_TABLE,
    record_row,
)
from veupathdb_mcp.audit.track_reads import (
    GeneSite,
)

WDK_BUDGET = 190
STORE_BUDGET = 160
COVERAGE_BUDGET = 40
XZ_SUFFIX = ".xz"
XZ_PRESET = 9 | lzma.PRESET_EXTREME
TRANSCRIPT_TYPE_PATH = f"/record-types/{TRANSCRIPT_RECORD}"
REFUSED = 400


class RecordExchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_type: str
    primary_key: dict[str, str]
    attributes: list[str]
    tables: list[str]
    status: int
    body: JsonValue


class StoreExchange(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    byte_range: str
    status: int
    body: Base64Bytes


class RecordWire(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    site: str
    transcript_key: list[str]
    records: list[RecordExchange]
    store: list[StoreExchange] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    site: str
    gene: str
    file: str
    orthologs: bool


CASES = (
    Case(
        site="fungidb",
        gene="Afu8g00850",
        file="introns_afumAf293_afu8g00850.json.xz",
        orthologs=True,
    ),
    Case(
        site="vectorbase",
        gene="AGAP007279",
        file="introns_agamPEST_agap007279.json.xz",
        orthologs=False,
    ),
    Case(
        site="toxodb",
        gene="TGME49_224540",
        file="introns_tgonME49_tgme49_224540.json.xz",
        orthologs=False,
    ),
    Case(
        site="vectorbase",
        gene="AGAP003685",
        file="introns_agamPEST_agap003685.json.xz",
        orthologs=True,
    ),
)
MISSING_PROTEINS = {
    "introns_pcynM_pkac_proteins.json": (
        "plasmodb",
        ["PVP01_1143600", "Py17XNL_000801943", "POWCR01_070036800", "PVPCR_0803510"],
    ),
    "introns_afumAf293_dmaw_proteins.json": (
        "fungidb",
        [
            "AN11194",
            "BO72DRAFT_529148",
            "P174DRAFT_379803",
            "FPRO_13655",
            "FPRN_06665",
            "ASPACDRAFT_47294",
            "BDV34DRAFT_226942",
            "FOXG_13322",
            "FOBCDRAFT_230538",
        ],
    ),
}
PIGA_SITE = "plasmodb"
PIGA = "PF3D7_1032400"
PIGA_FILE = "records_pfal3D7_piga.json"
PREVIOUS_ID = "previous ID"
ALTERNATE_ID = "alternate ID"


class RecordingStoppedError(RuntimeError):
    pass


class Tally(NoObserver):
    def __init__(self) -> None:
        self.wdk: list[str] = []
        self.store: list[str] = []

    def on_wdk_request(self, _seconds: float, attrs: MetricAttrs, /) -> None:
        self.wdk.append(str(dict(attrs)))

    def on_jbrowse_request(self, _seconds: float, attrs: MetricAttrs, /) -> None:
        self.store.append(str(dict(attrs)))


class Store(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        kept: list[StoreExchange],
        recorded: list[StoreExchange] | None = None,
    ) -> None:
        self._inner = inner
        self._kept = kept
        self._recorded = {(e.url, e.byte_range): e for e in recorded or []}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        known = self._recorded.get((str(request.url), request.headers.get("Range", "")))
        if known is not None:
            return httpx.Response(known.status, content=known.body, request=request)
        if len(TOTALS.store_sent) >= TOTALS.store_budget:
            msg = f"the recording spent its {TOTALS.store_budget} store reads"
            raise RecordingStoppedError(msg)
        TOTALS.store_sent.append(str(request.url))
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        self._kept.append(
            StoreExchange(
                url=str(request.url),
                byte_range=request.headers.get("Range", ""),
                status=response.status_code,
                body=base64.b64encode(body),
            )
        )
        if response.status_code >= REFUSED:
            msg = f"the store answered {response.status_code} to {request.url}"
            raise RecordingStoppedError(msg)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class Totals:
    def __init__(self) -> None:
        self.wdk_sent = 0
        self.store_sent: list[str] = []
        self.store_budget = STORE_BUDGET


TOTALS = Totals()


class Reader:
    def __init__(self, site: str, transcript_key: list[str]) -> None:
        self.site = site
        self.transcript_key = transcript_key
        self.records: list[RecordExchange] = []

    def gene_key(self, gene: str) -> dict[str, str]:
        return {"source_id": gene, "project_id": get_site(self.site).project_id}

    def transcript_pk(self, gene: str, transcript: str) -> dict[str, str]:
        values = {
            "gene_source_id": gene,
            "source_id": transcript,
            "project_id": get_site(self.site).project_id,
        }
        return {name: values[name] for name in self.transcript_key}

    async def read(
        self,
        record_type: str,
        key: dict[str, str],
        attributes: list[str],
        tables: list[str],
    ) -> JsonValue:
        if TOTALS.wdk_sent >= WDK_BUDGET:
            msg = f"the recording spent its {WDK_BUDGET} WDK requests"
            raise RecordingStoppedError(msg)
        TOTALS.wdk_sent += 1
        try:
            record = await get_strategy_api(self.site).get_single_record(
                record_type,
                [{"name": name, "value": value} for name, value in key.items()],
                attributes=attributes,
                tables=tables,
            )
        except VEuPathDBError as exc:
            self.records.append(
                RecordExchange(
                    record_type=record_type,
                    primary_key=key,
                    attributes=attributes,
                    tables=tables,
                    status=exc.status,
                    body=exc.detail,
                )
            )
            raise
        body = record.model_dump(mode="json", by_alias=True)
        self.records.append(
            RecordExchange(
                record_type=record_type,
                primary_key=key,
                attributes=attributes,
                tables=tables,
                status=200,
                body=body,
            )
        )
        return body


class _Table(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[OrthologRow] = Field(validation_alias=ORTHOLOG_TABLE)


class _Located(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sequence_id: str
    start_min: int
    end_max: int
    strand_plus_minus: str


class _Transcript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcript_id: str
    protein_length: str | None = None


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")

    attributes: dict[str, JsonValue] = {}
    tables: dict[str, list[dict[str, JsonValue]]] = {}


def longest_transcript(body: JsonValue) -> str | None:
    rows = [
        _Transcript.model_validate(row)
        for row in _Body.model_validate(body).tables.get(TRANSCRIPT_TABLE, [])
    ]
    coding = [r for r in rows if (r.protein_length or "").isdigit()]
    if not coding:
        return None
    best = min(coding, key=lambda r: (-int(r.protein_length or 0), r.transcript_id))
    return best.transcript_id


async def protein_reads(reader: Reader, gene: str) -> None:
    body = await reader.read("gene", reader.gene_key(gene), [], [TRANSCRIPT_TABLE])
    transcript = longest_transcript(body)
    if transcript is not None:
        await reader.read(
            TRANSCRIPT_RECORD,
            reader.transcript_pk(gene, transcript),
            [PROTEIN_ATTRIBUTE],
            [],
        )


async def store_reads(
    client: JBrowseClient, abbrev: str, where: _Located, intron_window: tuple[int, int]
) -> None:
    start, end = where.start_min, where.end_max
    seqid = where.sequence_id
    tabix = TabixReader(client)
    for track in await client.junction_tracks(abbrev):
        try:
            await tabix.lines(
                track, seqid, start - INTRON_JUNCTION_PAD, end + INTRON_JUNCTION_PAD
            )
        except TrackReadError as exc:
            print("junctions unread", track.data_path, exc.detail)
    track = await peptide_track(client, abbrev)
    if track is not None:
        try:
            await tabix.lines(track, seqid, start, end)
        except TrackReadError as exc:
            print("peptides unread", exc.detail)
    await GenomeReader(client).window(abbrev, seqid, *intron_window)
    for sub in (await coverage_choice(client, abbrev)).candidates:
        try:
            depth = await BigWigReader(client, sub.data_path).depth(seqid, start, end)
            print("coverage", sub.name, statistics.median(depth))
        except TrackReadError as exc:
            print("coverage unread", sub.name, exc.detail)


async def record_case(case: Case, key: list[str], into: Path) -> None:
    reader = Reader(case.site, key)
    kept: list[StoreExchange] = []
    client = JBrowseClient(
        base_url=get_site(case.site).web_base_url,
        transport=Store(httpx.AsyncHTTPTransport(), kept),
    )
    pk = reader.gene_key(case.gene)
    try:
        located = await reader.read(
            "gene", pk, list(RECORD_ATTRIBUTES), [TRANSCRIPT_TABLE]
        )
        where = _Located.model_validate(_Body.model_validate(located).attributes)
        model = await reader.read("gene", pk, [ORGANISM_ATTRIBUTE], [MODEL_TABLE])
        abbrev = GeneModel.from_record(
            WDKRecordInstance.model_validate(model)
        ).organism_abbrev
        await store_reads(
            client,
            abbrev,
            where,
            (
                max(1, where.start_min - INTRON_READ_THROUGH),
                where.end_max + INTRON_READ_THROUGH,
            ),
        )
        table = await reader.read("gene", pk, [], [ORTHOLOG_TABLE])
        if case.orthologs:
            await protein_reads(reader, case.gene)
            row = record_row(case.site, WDKRecordInstance.model_validate(located))
            group = OrthologGroup(
                gene=case.gene,
                members=[
                    member
                    for member in _Table.model_validate(
                        WDKRecordInstance.model_validate(table).tables
                    ).rows
                    if member.gene != case.gene
                ],
            )
            named = list(ortholog_choice(group, row))
            print(case.gene, "orthologs named", named)
            for gene in named:
                await protein_reads(reader, gene)
    finally:
        await client.close()
        write(
            into,
            case.file,
            RecordWire(
                site=case.site, transcript_key=key, records=reader.records, store=kept
            ),
        )


def write(into: Path, name: str, wire: RecordWire) -> None:
    into.mkdir(parents=True, exist_ok=True)
    text = (wire.model_dump_json(indent=1) + "\n").encode()
    (into / name).write_bytes(
        lzma.compress(text, preset=XZ_PRESET) if name.endswith(XZ_SUFFIX) else text
    )
    print("wrote", name, len(wire.records), "records", len(wire.store), "store reads")


def read_wire(path: Path) -> RecordWire:
    raw = path.read_bytes()
    return RecordWire.model_validate_json(
        lzma.decompress(raw) if path.name.endswith(XZ_SUFFIX) else raw
    )


async def record_proteins(
    name: str, site: str, genes: list[str], key: list[str], into: Path
) -> None:
    reader = Reader(site, key)
    try:
        for gene in genes:
            await protein_reads(reader, gene)
    finally:
        write(
            into,
            name,
            RecordWire(site=site, transcript_key=key, records=reader.records),
        )


class _TypeKey(BaseModel):
    model_config = ConfigDict(extra="ignore")

    primary_key_column_refs: list[str] = Field(alias="primaryKeyColumnRefs")


class _Alias(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alias: str
    id_type: str


async def record_piga(key: list[str], into: Path) -> None:
    reader = Reader(PIGA_SITE, key)
    pk = reader.gene_key(PIGA)
    try:
        await reader.read("gene", pk, list(RECORD_ATTRIBUTES), [TRANSCRIPT_TABLE])
        await protein_reads(reader, PIGA)
        aliases = await reader.read("gene", pk, [], ["Alias"])
        rows = [
            _Alias.model_validate(row)
            for row in _Body.model_validate(aliases).tables["Alias"]
        ]
        print("aliases", [(r.alias, r.id_type) for r in rows])
        old = next(r.alias for r in rows if r.id_type == PREVIOUS_ID)
        alias = next(r.alias for r in rows if r.id_type == ALTERNATE_ID)
        for given in (old, alias, f"{PIGA}.1"):
            await reader.read("gene", reader.gene_key(given), [], [])
        await reader.read("gene", pk, [PROTEIN_ATTRIBUTE], [])
    finally:
        write(
            into,
            PIGA_FILE,
            RecordWire(site=PIGA_SITE, transcript_key=key, records=reader.records),
        )


async def record(into: Path, *, piga_only: bool = False) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    tally = Tally()
    set_observer(tally)
    try:
        TOTALS.wdk_sent += 1
        served = await get_wdk_client(PIGA_SITE).get(TRANSCRIPT_TYPE_PATH)
        key = _TypeKey.model_validate(served).primary_key_column_refs
        print("transcript key", key)
        if not piga_only:
            for case in CASES:
                await record_case(case, key, into)
            for name, (site, genes) in MISSING_PROTEINS.items():
                await record_proteins(name, site, genes, key, into)
        await record_piga(key, into)
    finally:
        await close_all_clients()
        print("wdk sent", TOTALS.wdk_sent, "observed", len(tally.wdk), tally.wdk)
        print("store sent", len(TOTALS.store_sent), "observed", tally.store)


async def record_coverage(case: Case, into: Path) -> None:
    use_qa_sites()
    await act_as_the_test_account()
    tally = Tally()
    set_observer(tally)
    TOTALS.store_budget = COVERAGE_BUDGET
    wire = read_wire(into / case.file)
    located = next(
        r.body
        for r in wire.records
        if r.record_type == "gene" and r.tables == [TRANSCRIPT_TABLE] and r.attributes
    )
    where = _Located.model_validate(_Body.model_validate(located).attributes)
    model = next(r.body for r in wire.records if r.tables == [MODEL_TABLE])
    abbrev = GeneModel.from_record(
        WDKRecordInstance.model_validate(model)
    ).organism_abbrev
    kept: list[StoreExchange] = []
    client = JBrowseClient(
        base_url=get_site(case.site).web_base_url,
        transport=Store(httpx.AsyncHTTPTransport(), kept, wire.store),
    )
    try:
        gene = GeneSite(
            abbrev=abbrev,
            seqid=where.sequence_id,
            start=where.start_min,
            end=where.end_max,
            strand="+" if where.strand_plus_minus == "+" else "-",
            window=(where.start_min, where.end_max),
        )
        span = (where.start_min, where.end_max)
        found = await read_depth(client, gene, [span], [span])
        print("coverage", found)
    finally:
        await client.close()
        write(into, case.file, wire.model_copy(update={"store": [*wire.store, *kept]}))
        print(
            "wdk observed", len(tally.wdk), "store", len(TOTALS.store_sent), tally.store
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=FIXTURES)
    parser.add_argument("--piga-only", action="store_true")
    parser.add_argument("--coverage-of", choices=[c.gene for c in CASES])
    arguments = parser.parse_args()
    if arguments.coverage_of:
        [case] = [c for c in CASES if c.gene == arguments.coverage_of]
        asyncio.run(record_coverage(case, arguments.out))
    else:
        asyncio.run(record(arguments.out, piga_only=arguments.piga_only))
