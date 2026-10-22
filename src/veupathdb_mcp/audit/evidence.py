"""The evidence a gene record serves (structures, peptides, cross-references, edits,
notes and screens) and the provenance an organism record states, as served."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)
from veupathdb.model import CamelModel
from veupathdb.wdk import WDKAnswer, WDKRecordInstance

from veupathdb_mcp.audit.gene_ids import GeneId, check_resolved
from veupathdb_mcp.audit.gene_models import ORGANISM_ATTRIBUTE

TRANSCRIPT_TABLE = "GeneTranscripts"
PDB_TABLE = "PdbSimilarities"
PEPTIDE_TABLE = "MassSpecDownload"
ALPHAFOLD_TABLE = "AlphaFoldLinkouts"
LINKOUT_TABLE = "GeneLinkouts"
SEQEDIT_TABLE = "Seqedits"
COMMENT_TABLE = "UserComments"
PUBMED_TABLE = "PubMed"
NOTE_TABLE = "Notes"
EVIDENCE_TABLES = (
    TRANSCRIPT_TABLE,
    PDB_TABLE,
    PEPTIDE_TABLE,
    ALPHAFOLD_TABLE,
    LINKOUT_TABLE,
    SEQEDIT_TABLE,
    COMMENT_TABLE,
    PUBMED_TABLE,
    NOTE_TABLE,
)
SCREEN_DATA_TABLES = (
    "EdaPhenotypeGraphsDataTable",
    "PhenotypeScoreGraphsDataTable",
    "PhenotypeGraphsDataTable",
    "CrisprPhenotypeGraphsDataTable",
)
_ORGANISM_PREFIX = re.compile(r"^([a-z]{4}[A-Za-z0-9]+)_")
_SCREEN = "phenotype"
_NOT_A_SCREEN = ("graph", "dataset", "image")


class _Link(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    display_text: str = Field(validation_alias="displayText")


_CELL: TypeAdapter[_Link | str | None] = TypeAdapter(_Link | str | None)
_NUMBER: TypeAdapter[int | str | None] = TypeAdapter(int | str | None)
_FLAG: TypeAdapter[Literal["yes", "no"] | bool] = TypeAdapter(
    Literal["yes", "no"] | bool
)


def _text(value: JsonValue) -> str | None:
    match _CELL.validate_python(value):
        case _Link() as link:
            return link.display_text or None
        case text:
            return text or None


def _number(value: JsonValue) -> int | str | None:
    match _NUMBER.validate_python(value, strict=True):
        case "":
            return None
        case number:
            return number


def _yes(value: JsonValue) -> bool:
    return _FLAG.validate_python(value, strict=True) in {"yes", True}


def _numbered(build: int | None) -> int | None:
    return build or None


type ServedText = Annotated[str | None, BeforeValidator(_text)]
type ServedInt = Annotated[int | None, BeforeValidator(_number)]
type ServedBuild = Annotated[
    int | None, BeforeValidator(_number), AfterValidator(_numbered)
]
_SCREEN_ROWS: TypeAdapter[dict[str, list[dict[str, ServedText]]]] = TypeAdapter(
    dict[str, list[dict[str, ServedText]]]
)


def _is_screen(table: str) -> bool:
    name = table.lower()
    return table in SCREEN_DATA_TABLES or (
        _SCREEN in name and not any(word in name for word in _NOT_A_SCREEN)
    )


def requested_tables(declared: list[str]) -> list[str]:
    return [name for name in declared if name in EVIDENCE_TABLES or _is_screen(name)]


class PdbHit(CamelModel):
    model_config = ConfigDict(frozen=True)

    transcript: str
    pdb_id: str
    title: str | None
    taxon: str | None
    identity: int
    protein_covered_percent: int
    evalue: float
    chains: list[str]


class GeneTranscript(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    transcript_id: str
    transcript_type: str
    protein_length: ServedInt
    exon_count: int


class Peptide(CamelModel):
    model_config = ConfigDict(frozen=True)

    transcript: str
    sequence: str
    start: int
    end: int
    experiments: list[str]
    spectra: int


class AlphaFoldModel(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    uniprot_id: str
    source: str = Field(validation_alias="uniprot_source")
    first: int
    last: int
    length: int = Field(validation_alias="prediction_length")


class Linkout(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    database: str = Field(validation_alias="dataset")
    external_id: str = Field(validation_alias=AliasChoices("ext_id", "externalId"))


class SeqEdit(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: ServedText = Field(validation_alias="type")
    length_diff: ServedText
    location: ServedText
    diff: ServedText


class PhenotypeScreen(CamelModel):
    model_config = ConfigDict(frozen=True)

    table: str
    rows: list[dict[str, ServedText]]


class _PdbRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    transcript: str = Field(validation_alias="transcript_id")
    chain: str = Field(validation_alias="pdb_chain")
    pdb_id: str
    title: ServedText = Field(validation_alias="pdb_title")
    taxon: ServedText
    identity: int = Field(validation_alias="percent_identity")
    protein_covered_percent: int = Field(validation_alias="percent_plasmo_coverage")
    mantissa: str = Field(validation_alias="evalue_mant")
    exponent: int = Field(validation_alias="evalue_exp")

    @property
    def key(self) -> tuple[str, str, int, int, float]:
        evalue = float(f"{self.mantissa}e{self.exponent}")
        return (
            self.transcript,
            self.pdb_id,
            self.identity,
            self.protein_covered_percent,
            evalue,
        )

    def hit(self, chains: list[str]) -> PdbHit:
        return PdbHit(
            transcript=self.transcript,
            pdb_id=self.pdb_id,
            title=self.title,
            taxon=self.taxon,
            identity=self.identity,
            protein_covered_percent=self.protein_covered_percent,
            evalue=self.key[-1],
            chains=chains,
        )


class _PeptideRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    transcript: str = Field(validation_alias="transcript_id")
    sequence: str
    start: int = Field(validation_alias="protein_start")
    end: int = Field(validation_alias="protein_end")
    experiment: str
    spectra: int = Field(validation_alias="spectrum_count")

    @property
    def key(self) -> tuple[str, int, int, str]:
        return self.transcript, self.start, self.end, self.sequence


class _Tables(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transcripts: list[GeneTranscript] = Field(
        default=[], validation_alias=TRANSCRIPT_TABLE
    )
    pdb: list[_PdbRow] = Field(default=[], validation_alias=PDB_TABLE)
    peptides: list[_PeptideRow] = Field(default=[], validation_alias=PEPTIDE_TABLE)
    alphafold: list[AlphaFoldModel] = Field(
        default=[], validation_alias=ALPHAFOLD_TABLE
    )
    linkouts: list[Linkout] = Field(default=[], validation_alias=LINKOUT_TABLE)
    seqedits: list[SeqEdit] = Field(default=[], validation_alias=SEQEDIT_TABLE)
    comments: list[JsonValue] = Field(default=[], validation_alias=COMMENT_TABLE)
    pubmed: list[JsonValue] = Field(default=[], validation_alias=PUBMED_TABLE)
    notes: list[JsonValue] = Field(default=[], validation_alias=NOTE_TABLE)


def _pdb_hits(rows: list[_PdbRow]) -> list[PdbHit]:
    chains: defaultdict[tuple[str, str, int, int, float], list[str]] = defaultdict(list)
    first: dict[tuple[str, str, int, int, float], _PdbRow] = {}
    for row in rows:
        chains[row.key].append(row.chain)
        first.setdefault(row.key, row)
    return [row.hit(chains[key]) for key, row in first.items()]


def _peptides(rows: list[_PeptideRow]) -> list[Peptide]:
    seen: defaultdict[tuple[str, int, int, str], list[_PeptideRow]] = defaultdict(list)
    for row in rows:
        seen[row.key].append(row)
    return [
        Peptide(
            transcript=transcript,
            sequence=sequence,
            start=start,
            end=end,
            experiments=sorted({row.experiment for row in found}),
            spectra=sum(row.spectra for row in found),
        )
        for (transcript, start, end, sequence), found in sorted(seen.items())
    ]


class _Organism(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    abbrev: str = Field(validation_alias=ORGANISM_ATTRIBUTE, min_length=1)


def _screens(
    record: WDKRecordInstance, asked: list[str]
) -> tuple[list[PhenotypeScreen], list[PhenotypeScreen]]:
    own_prefix = f"{_Organism.model_validate(record.attributes).abbrev}_"
    names = [name for name in asked if _is_screen(name) and name in record.tables]
    own = [name for name in names if name.startswith(own_prefix)]
    unprefixed = [
        name
        for name in names
        if name not in own and _ORGANISM_PREFIX.match(name) is None
    ]
    rows = _SCREEN_ROWS.validate_python(
        {name: record.tables[name] for name in [*own, *unprefixed]}
    )
    return (
        [PhenotypeScreen(table=name, rows=rows[name]) for name in own],
        [PhenotypeScreen(table=name, rows=rows[name]) for name in unprefixed],
    )


class GeneEvidence(CamelModel):
    model_config = ConfigDict(frozen=True)

    gene_ids: list[GeneId]
    gene: str
    pdb_hits: list[PdbHit]
    peptides: list[Peptide]
    alphafold: list[AlphaFoldModel]
    linkouts: list[Linkout]
    seqedits: list[SeqEdit]
    transcripts: list[GeneTranscript]
    comments: int
    pubmed: int
    notes: int
    phenotypes: list[PhenotypeScreen]
    unprefixed_tables: list[PhenotypeScreen]
    unserved: list[str]

    @model_validator(mode="after")
    def _named_as_resolved(self) -> Self:
        check_resolved(self.gene_ids, [self.gene])
        return self

    @classmethod
    def from_record(
        cls, named: GeneId, record: WDKRecordInstance, declared: list[str]
    ) -> GeneEvidence:
        tables = _Tables.model_validate(record.tables)
        asked = requested_tables(declared)
        phenotypes, unprefixed = _screens(record, asked)
        unserved = (
            set(EVIDENCE_TABLES).difference(declared)
            | set(record.table_errors)
            | {name for name in asked if name not in record.tables}
        )
        return cls(
            gene_ids=[named],
            gene=named.resolved,
            pdb_hits=_pdb_hits(tables.pdb),
            peptides=_peptides(tables.peptides),
            alphafold=tables.alphafold,
            linkouts=tables.linkouts,
            seqedits=tables.seqedits,
            transcripts=tables.transcripts,
            comments=len(tables.comments),
            pubmed=len(tables.pubmed),
            notes=len(tables.notes),
            phenotypes=phenotypes,
            unprefixed_tables=unprefixed,
            unserved=sorted(unserved),
        )


class GenomeProvenance(CamelModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str = Field(validation_alias=AliasChoices("source_id", "recordId"))
    organism: str = Field(validation_alias="organism_full", min_length=1)
    genome_source: ServedText
    genome_version: ServedText
    annotation_source: ServedText
    annotation_version: ServedText
    database_version: ServedText
    build_introduced: ServedBuild
    build_latest_update: ServedBuild
    reference_strain: Annotated[bool, BeforeValidator(_yes)] = Field(
        validation_alias=AliasChoices("is_reference_strain", "referenceStrain")
    )
    ncbi_taxon: ServedText = Field(
        validation_alias=AliasChoices("ncbi_tax_id", "ncbiTaxon")
    )


def provenance_of(answer: WDKAnswer, organism: str) -> GenomeProvenance | None:
    return next(
        (
            GenomeProvenance.model_validate(record.attributes)
            for record in answer.records
            if record.attribute_text("organism_full") == organism
        ),
        None,
    )
