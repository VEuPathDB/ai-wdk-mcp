import asyncio

import httpx
import pytest
from veupathdb.jbrowse import (
    BigWigSummary,
    GenomeWindow,
    JBrowseError,
    SequenceNotIndexedError,
    SubTrack,
    TrackConfig,
    TrackList,
)

from veupathdb_mcp.audit import intron_coverage, intron_evidence, track_reads
from veupathdb_mcp.audit.intron_coverage import (
    COVERAGE_CANDIDATE_PAIRS,
    TRACK_LIST_RETRY_SECONDS,
    TRACK_LIST_TRIES,
    DepthRead,
    coverage_choice,
    read_depth,
    strand_of,
    stranded_pairs,
    unstranded_candidate,
)
from veupathdb_mcp.audit.intron_evidence import (
    PEPTIDE_MAX_GROUPS,
    peptide_splits,
    read_peptides,
    splice_motif,
)
from veupathdb_mcp.audit.introns import IntronDepth, PeptideSplit
from veupathdb_mcp.audit.track_reads import (
    GeneSite,
)

SEQID = "exa_chr1"
GENE = GeneSite(
    abbrev="exaA", seqid=SEQID, start=1001, end=1100, strand="+", window=(1, 2000)
)


def segment(start: int, end: int, parent: str, strand: str = "+") -> str:
    return (
        f"{SEQID}\tveupathdb\talign\t{start}\t{end}\t.\t{strand}\t1\t"
        f"ID=seg_{start}_{end};Parent={parent}"
    )


def peptide(start: int, end: int, own: str, strand: str = "+") -> str:
    return (
        f"{SEQID}\tveupathdb\tms_peptide\t{start}\t{end}\t.\t{strand}\t1\t"
        f'ID={own};ions_score="";peptide=EXAMPLE;spectrum_count=1'
    )


def test_segments_sharing_a_parent_are_one_split_peptide() -> None:
    lines = [
        segment(1010, 1026, "p1"),
        peptide(1010, 1060, "p1"),
        segment(1051, 1060, "p1"),
        segment(1070, 1090, "p2"),
        peptide(1070, 1090, "p2"),
    ]

    assert peptide_splits(lines, "+") == (
        PeptideSplit(before=(1010, 1026), after=(1051, 1060)),
    )


def test_a_peptide_on_the_other_strand_splits_nothing() -> None:
    lines = [segment(1010, 1026, "p1", "-"), segment(1051, 1060, "p1", "-")]

    assert peptide_splits(lines, "+") == ()


def test_a_minus_strand_motif_is_read_on_the_genes_strand() -> None:
    window = GenomeWindow(seqid=SEQID, start=1, sequence="AACTTTTTTTACAA")

    assert splice_motif(window, (3, 12), "-") == "GT..AG"
    assert splice_motif(window, (3, 12), "+") == "CT..AC"
    assert splice_motif(window, (3, 20), "+") is None


def subtrack(name: str, path: str) -> SubTrack:
    return SubTrack(url=f"/a/service/jbrowse/store?data={path}", name=name)


def track(label: str, *subs: SubTrack) -> TrackConfig:
    return TrackConfig(
        label=label,
        key=f"shown {label}",
        store_class="MultiBigWig/Store/SeqFeature/MultiBigWig",
        url_templates=list(subs),
    )


FORWARD = subtrack("s1 (unique forward)", "f.bw")
REVERSE = subtrack("s1 (unique reverse)", "r.bw")
SENSE = subtrack("s2 (sense)", "s.bw")
PLAIN = subtrack("s3 (unique)", "p.bw")
UNIFIED = subtrack("s4 (unique)", "u.bw")


FORWARD_B = subtrack("s5 (unique forward)", "f5.bw")
REVERSE_B = subtrack("s5 (unique reverse)", "r5.bw")


@pytest.mark.parametrize(
    ("tracks", "pairs"),
    [
        ([track("a", PLAIN), track("b", FORWARD, REVERSE)], [(FORWARD, REVERSE)]),
        (
            [track("d", FORWARD_B, REVERSE_B), track("c", FORWARD, REVERSE)],
            [(FORWARD, REVERSE), (FORWARD_B, REVERSE_B)],
        ),
        ([track("a", FORWARD), track("b", REVERSE)], []),
        ([track("a", FORWARD, REVERSE_B)], []),
        (
            [track("a", FORWARD, REVERSE), track("b", REVERSE, FORWARD)],
            [(FORWARD, REVERSE)],
        ),
        ([track("a", SENSE, FORWARD)], []),
    ],
)
def test_a_stranded_pair_is_one_experiment_on_both_strands_in_label_order(
    tracks: list[TrackConfig], pairs: list[tuple[SubTrack, SubTrack]]
) -> None:
    assert stranded_pairs(tracks) == pairs


@pytest.mark.parametrize(
    ("tracks", "picked"),
    [
        ([track("a", PLAIN), track("unified b", UNIFIED)], [UNIFIED]),
        ([track("c", SENSE), track("b", PLAIN), track("a", FORWARD)], [PLAIN]),
        ([track("a", SENSE, FORWARD)], []),
    ],
)
def test_with_no_pair_a_unified_then_any_unstranded_subtrack_is_read(
    tracks: list[TrackConfig], picked: list[SubTrack]
) -> None:
    assert unstranded_candidate(tracks) == picked


class Store:
    def __init__(
        self,
        tracks: list[TrackConfig],
        depths: dict[str, list[float]],
        summaries: dict[str, BigWigSummary],
    ) -> None:
        self.tracks = tracks
        self.depths = depths
        self.summaries = summaries
        self.refused: dict[str, JBrowseError] = {}
        self.list_refusal: httpx.HTTPError | None = None
        self.reads: list[str] = []

    async def coverage_tracks(self, abbrev: str) -> list[TrackConfig]:
        self.reads.append(f"list:{abbrev}")
        if self.list_refusal is not None:
            raise self.list_refusal
        return self.tracks

    def bigwig(self, client: "Store", path: str) -> "Reader":
        return Reader(self, path)


class Reader:
    def __init__(self, store: Store, path: str) -> None:
        self.store = store
        self.path = path

    async def summary(self) -> BigWigSummary | None:
        self.store.reads.append(f"summary:{self.path}")
        if self.path in self.store.refused:
            raise self.store.refused[self.path]
        return self.store.summaries.get(self.path)

    async def depth(self, seqid: str, start: int, end: int) -> list[float]:
        self.store.reads.append(f"depth:{self.path}")
        if self.path not in self.store.depths:
            raise SequenceNotIndexedError(self.path, seqid)
        return self.store.depths[self.path]


EXONS = [(1001, 1040), (1061, 1100)]
INTRON = (1041, 1060)


def flat(exon: float, intron: float) -> list[float]:
    return [intron if INTRON[0] <= p <= INTRON[1] else exon for p in range(1001, 1101)]


def gapped(depths: list[float], bases: int) -> list[float]:
    first = INTRON[0] - 1001
    return [0.0 if first <= i < first + bases else d for i, d in enumerate(depths)]


FORWARD_C = subtrack("s6 (unique forward)", "f6.bw")
REVERSE_C = subtrack("s6 (unique reverse)", "r6.bw")
FORWARD_D = subtrack("s7 (unique forward)", "f7.bw")
REVERSE_D = subtrack("s7 (unique reverse)", "r7.bw")
SMALL_F = subtrack("s8 (unique forward)", "sf.bw")
SMALL_R = subtrack("s8 (unique reverse)", "sr.bw")


def summary_of(covered: int, total: float) -> BigWigSummary:
    return BigWigSummary(
        bases_covered=covered,
        min_value=0.0,
        max_value=total,
        sum_data=total,
        sum_squares=0.0,
    )


def two_pairs(monkeypatch: pytest.MonkeyPatch) -> Store:
    store = Store(
        [track("d", FORWARD_B, REVERSE_B), track("c", FORWARD, REVERSE)],
        {
            "f.bw": flat(9.0, 9.0),
            "r.bw": flat(9.0, 9.0),
            "f5.bw": flat(2.0, 2.0),
            "r5.bw": gapped(flat(40.0, 12.0), 2),
        },
        {
            "f.bw": summary_of(1000, 1000.0),
            "r.bw": summary_of(1000, 500.0),
            "f5.bw": summary_of(1000, 3000.0),
            "r5.bw": summary_of(1000, 4000.0),
        },
    )
    monkeypatch.setattr(intron_coverage, "BigWigReader", store.bigwig)
    return store


async def test_every_shortlisted_subtrack_is_read_and_the_deepest_over_the_exons_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)

    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert found == DepthRead(
        depth={
            "1041-1060": IntronDepth(
                intron_median_depth=12.0,
                exon_median_depth=40.0,
                covered_share=0.9,
                track=REVERSE_B.name,
            )
        },
        notes=[],
    )
    assert store.reads == [
        "list:exaA",
        "summary:f.bw",
        "summary:r.bw",
        "summary:f5.bw",
        "summary:r5.bw",
        "depth:f5.bw",
        "depth:r5.bw",
        "depth:f.bw",
        "depth:r.bw",
    ]


def broad_and_narrow(monkeypatch: pytest.MonkeyPatch) -> Store:
    store = Store(
        [
            track("a", SMALL_F, SMALL_R),
            track("b", FORWARD, REVERSE),
            track("c", FORWARD_B, REVERSE_B),
            track("d", FORWARD_C, REVERSE_C),
            track("e", FORWARD_D, REVERSE_D),
        ],
        {path: flat(5.0, 5.0) for path in ("f.bw", "r.bw", "f5.bw", "r5.bw")}
        | {"f6.bw": flat(30.0, 30.0), "r6.bw": flat(1.0, 1.0)},
        {
            "sf.bw": summary_of(10, 9e9),
            "sr.bw": summary_of(10, 9e9),
            "f.bw": summary_of(5000, 10.0),
            "r.bw": summary_of(5000, 10.0),
            "f5.bw": summary_of(4000, 10.0),
            "r5.bw": summary_of(4000, 10.0),
            "f6.bw": summary_of(4000, 20.0),
            "r6.bw": summary_of(4000, 20.0),
            "f7.bw": summary_of(100, 10.0),
            "r7.bw": summary_of(100, 10.0),
        },
    )
    monkeypatch.setattr(intron_coverage, "BigWigReader", store.bigwig)
    return store


async def test_a_deep_narrow_pair_never_enters_the_shortlist_ahead_of_a_broad_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = broad_and_narrow(monkeypatch)

    choice = await coverage_choice(store, "exaA")
    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert choice.candidates == [
        FORWARD,
        REVERSE,
        FORWARD_C,
        REVERSE_C,
        FORWARD_B,
        REVERSE_B,
    ]
    assert len(choice.candidates) == 2 * COVERAGE_CANDIDATE_PAIRS
    assert found.depth is not None
    assert found.depth["1041-1060"].track == FORWARD_C.name
    depths = [read for read in store.reads if read.startswith("depth:")]
    assert len(depths) == 2 * COVERAGE_CANDIDATE_PAIRS
    assert "depth:sf.bw" not in depths


async def test_no_shortlisted_experiment_with_reads_leaves_the_depth_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(
        [track("c", FORWARD, REVERSE)],
        {"f.bw": flat(0.0, 0.0), "r.bw": flat(0.0, 0.0)},
        {"f.bw": summary_of(1000, 1000.0), "r.bw": summary_of(1000, 500.0)},
    )
    monkeypatch.setattr(intron_coverage, "BigWigReader", store.bigwig)

    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert found == DepthRead(
        depth=None,
        notes=["no shortlisted RNA-seq experiment has reads over this gene"],
    )


async def test_an_organisms_headers_are_read_once_for_every_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)

    await read_depth(store, GENE, EXONS, [INTRON])
    await read_depth(store, GENE, EXONS, [INTRON])

    assert [r for r in store.reads if not r.startswith("depth:")] == [
        "list:exaA",
        "summary:f.bw",
        "summary:r.bw",
        "summary:f5.bw",
        "summary:r5.bw",
    ]


async def test_headers_past_the_bound_are_not_read_and_the_evidence_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)
    monkeypatch.setattr(intron_coverage, "COVERAGE_HEADERS_READ", 2)

    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert found.notes == [
        "exaA lists 4 stranded coverage files; the first 2 in label order were measured"
    ]
    assert found.depth is not None
    assert found.depth["1041-1060"].track == FORWARD.name
    assert [r for r in store.reads if r.startswith("summary:")] == [
        "summary:f.bw",
        "summary:r.bw",
    ]


async def test_a_sequence_the_bigwig_does_not_list_is_unread_never_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(
        [track("b", FORWARD, REVERSE)],
        {},
        {"f.bw": summary_of(10, 10.0), "r.bw": summary_of(10, 10.0)},
    )
    monkeypatch.setattr(intron_coverage, "BigWigReader", store.bigwig)

    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert found == DepthRead(
        depth=None,
        notes=[
            (
                f"the depth read of {FORWARD.name} failed: the index of f.bw names "
                f"no sequence {SEQID}"
            ),
            (
                f"the depth read of {REVERSE.name} failed: the index of r.bw names "
                f"no sequence {SEQID}"
            ),
            (
                f"no coverage track read {SEQID}:1001-1100 "
                f"({FORWARD.name}, {REVERSE.name})"
            ),
        ],
    )


async def test_a_header_the_site_refuses_drops_its_pair_once_for_the_organism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)
    store.refused["r5.bw"] = JBrowseError("GET", "https://qa.example/r5.bw", 404)

    first = await read_depth(store, GENE, EXONS, [INTRON])
    second = await read_depth(store, GENE, EXONS, [INTRON])

    refusal = (
        "the header read of r5.bw failed: GET https://qa.example/r5.bw answered 404"
    )
    assert first.notes == second.notes == [refusal]
    assert first.depth is not None
    assert first.depth["1041-1060"].track == FORWARD.name
    assert [r for r in store.reads if r.startswith(("list:", "summary:"))] == [
        "list:exaA",
        "summary:f.bw",
        "summary:r.bw",
        "summary:f5.bw",
        "summary:r5.bw",
    ]


async def test_a_refused_track_list_is_read_again_by_the_next_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)
    store.list_refusal = httpx.ReadTimeout("timed out")

    refused = await read_depth(store, GENE, EXONS, [INTRON])
    store.list_refusal = None
    read = await read_depth(store, GENE, EXONS, [INTRON])
    again = await read_depth(store, GENE, EXONS, [INTRON])

    reason = "the RNA-seq track list read failed: ReadTimeout timed out"
    assert refused == DepthRead(depth=None, notes=[reason])
    assert read.depth is not None
    assert again == read
    assert store.reads.count("list:exaA") == 2


class Clock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = 1000.0
        monkeypatch.setattr(intron_coverage, "monotonic", lambda: self.now)


async def test_past_its_tries_an_organisms_coverage_waits_out_a_cool_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(monkeypatch)
    store = two_pairs(monkeypatch)
    store.list_refusal = httpx.ReadTimeout("timed out")

    found = [
        await read_depth(store, GENE, EXONS, [INTRON]) for _ in range(TRACK_LIST_TRIES)
    ]
    clock.now += TRACK_LIST_RETRY_SECONDS - 1
    waiting = await read_depth(store, GENE, EXONS, [INTRON])

    reason = "the RNA-seq track list read failed: ReadTimeout timed out"
    assert [one.notes for one in found] == [[reason]] * TRACK_LIST_TRIES
    cooling = (
        f"the RNA-seq track list of exaA failed {TRACK_LIST_TRIES} times; "
        "it is read again in 1 seconds"
    )
    assert waiting.notes == [cooling]
    assert store.reads == ["list:exaA"] * TRACK_LIST_TRIES


async def test_after_the_cool_down_a_read_track_list_keeps_its_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock(monkeypatch)
    store = two_pairs(monkeypatch)
    store.list_refusal = httpx.ReadTimeout("timed out")
    for _ in range(TRACK_LIST_TRIES):
        await read_depth(store, GENE, EXONS, [INTRON])

    clock.now += TRACK_LIST_RETRY_SECONDS
    store.list_refusal = None
    read = await read_depth(store, GENE, EXONS, [INTRON])
    store.list_refusal = httpx.ReadTimeout("timed out")
    again = await read_depth(store, GENE, EXONS, [INTRON])

    assert read.depth is not None
    assert again == read
    assert store.reads.count("list:exaA") == TRACK_LIST_TRIES + 1


async def test_genes_at_once_spend_one_try_on_one_refused_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)
    store.list_refusal = httpx.ReadTimeout("timed out")

    await asyncio.gather(
        read_depth(store, GENE, EXONS, [INTRON]),
        read_depth(store, GENE, EXONS, [INTRON]),
    )
    store.list_refusal = None
    read = await read_depth(store, GENE, EXONS, [INTRON])

    assert read.depth is not None
    assert store.reads.count("list:exaA") == 2


async def test_two_genes_at_once_read_an_organisms_headers_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = two_pairs(monkeypatch)

    await asyncio.gather(
        read_depth(store, GENE, EXONS, [INTRON]),
        read_depth(store, GENE, EXONS, [INTRON]),
    )

    assert [r for r in store.reads if not r.startswith("depth:")] == [
        "list:exaA",
        "summary:f.bw",
        "summary:r.bw",
        "summary:f5.bw",
        "summary:r5.bw",
    ]


@pytest.mark.parametrize(
    ("name", "strand"),
    [
        ("liver (unique forward)", "+"),
        ("liver (+)", "+"),
        ("liver plus strand", "+"),
        ("surplus tissue", None),
        ("C-terminus (unique)", None),
        ("liver (antisense)", "unread"),
    ],
)
def test_a_strand_is_read_off_a_whole_word(name: str, strand: str | None) -> None:
    assert strand_of(subtrack(name, "x.bw")) == strand


async def test_with_no_pair_the_unstranded_subtrack_is_read_without_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store([track("unified a", UNIFIED)], {"u.bw": flat(10.0, 5.0)}, {})
    monkeypatch.setattr(intron_coverage, "BigWigReader", store.bigwig)

    found = await read_depth(store, GENE, EXONS, [INTRON])

    assert found.depth is not None
    assert found.depth["1041-1060"].track == UNIFIED.name
    assert store.reads == ["list:exaA", "depth:u.bw"]


class Peptides:
    def __init__(self, groups: int) -> None:
        self.groups = groups
        self.counted: list[tuple[str, int, int]] = []
        self.lines_read: list[tuple[str, int, int]] = []

    async def track_list(self, kind: str, abbrev: str) -> TrackList:
        return TrackList.model_validate(
            {
                "tracks": [
                    {
                        "storeClass": "JBrowse/Store/SeqFeature/GFF3Tabix",
                        "urlTemplate": "/a/service/jbrowse/store?data=ExaA/gff/"
                        "unifiedGenomicMassSpec.gff.gz",
                    }
                ]
            }
        )

    def reader(self, client: "Peptides") -> "Peptides":
        return self

    async def chunk_group_count(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> int:
        self.counted.append((seqid, start, end))
        return self.groups

    async def lines(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> list[str]:
        self.lines_read.append((seqid, start, end))
        return [segment(1010, 1040, "p1"), segment(1061, 1070, "p1")]


async def test_peptides_in_at_most_two_chunk_groups_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Peptides(PEPTIDE_MAX_GROUPS)
    monkeypatch.setattr(track_reads, "TabixReader", site.reader)

    found = await read_peptides(site, GENE)

    assert found == (PeptideSplit(before=(1010, 1040), after=(1061, 1070)),)
    assert site.counted == site.lines_read == [(SEQID, 1001, 1100)]


async def test_a_third_peptide_chunk_group_leaves_the_arm_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Peptides(PEPTIDE_MAX_GROUPS + 1)
    monkeypatch.setattr(track_reads, "TabixReader", site.reader)

    found = await read_peptides(site, GENE)

    assert found == (
        f"the peptides over {SEQID}:1001-1100 lie in 3 chunk groups; at most 2 are read"
    )
    assert site.lines_read == []


def test_a_gene_reads_at_most_one_window_two_peptide_groups_and_two_depths() -> None:
    assert intron_evidence.INTRON_STORE_READS == 1 + 2 + 3 * 2 * (1 + 4 + 2)


def test_an_organism_reads_at_most_200_coverage_headers_per_run() -> None:
    assert intron_coverage.COVERAGE_HEADERS_READ == 200


class Unindexed(Peptides):
    async def chunk_group_count(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> int:
        raise SequenceNotIndexedError(track.data_path, seqid)


async def test_a_sequence_the_peptide_index_does_not_name_holds_no_peptide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = Unindexed(0)
    monkeypatch.setattr(track_reads, "TabixReader", site.reader)

    assert await read_peptides(site, GENE) == ()
    assert site.lines_read == []


class RefusedPeptides(Peptides):
    def __init__(self, failure: Exception, at: str) -> None:
        super().__init__(1)
        self.failure = failure
        self.at = at

    async def track_list(self, kind: str, abbrev: str) -> TrackList:
        if self.at == "list":
            raise self.failure
        return await super().track_list(kind, abbrev)

    async def lines(
        self, track: TrackConfig, seqid: str, start: int, end: int
    ) -> list[str]:
        if self.at == "lines":
            raise self.failure
        return await super().lines(track, seqid, start, end)


@pytest.mark.parametrize(
    ("failure", "at", "reason"),
    [
        (
            JBrowseError("GET", "https://qa.example/list", 500),
            "list",
            "the peptide reads failed: GET https://qa.example/list answered 500",
        ),
        (
            httpx.ConnectError("refused"),
            "lines",
            "the peptide reads failed: ConnectError refused",
        ),
    ],
)
async def test_a_peptide_read_the_site_refuses_is_a_stated_reason(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, at: str, reason: str
) -> None:
    site = RefusedPeptides(failure, at)
    monkeypatch.setattr(track_reads, "TabixReader", site.reader)

    assert await read_peptides(site, GENE) == reason
