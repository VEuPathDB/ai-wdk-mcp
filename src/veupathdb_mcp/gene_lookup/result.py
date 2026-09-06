"""Gene result building for lookup responses."""

from dataclasses import dataclass, field

DEFAULT_GENE_ATTRIBUTES = [
    "primary_key",
    "gene_source_id",
    "gene_name",
    "gene_product",
    "gene_type",
    "organism",
    "gene_location_text",
    "gene_previous_ids",
]


@dataclass
class GeneResult:
    """Typed gene result used throughout the lookup pipeline."""

    gene_id: str
    display_name: str = ""
    organism: str = ""
    product: str = ""
    gene_name: str = ""
    gene_type: str = ""
    location: str = ""
    previous_ids: str = ""
    matched_fields: list[str] | None = field(default=None)
