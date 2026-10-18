"""A test reads and writes catalogs outside the warm cache the image serves."""

from tests._support.recordings import TEST_ROOT

from veupathdb_mcp.settings import DEFAULT_CATALOG_CACHE_DIR, get_mcp_settings


def test_the_catalog_cache_of_a_test_is_not_the_warm_cache() -> None:
    warm = (TEST_ROOT.parent / DEFAULT_CATALOG_CACHE_DIR).resolve()

    assert get_mcp_settings().catalog_cache_dir.resolve() != warm
