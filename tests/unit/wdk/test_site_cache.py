from veupathdb_mcp.wdk.site_cache import SiteCache


class Site:
    def __init__(self) -> None:
        self.reads: list[str] = []

    async def value(self, site_id: str) -> str:
        self.reads.append(site_id)
        return f"{site_id} value"


async def test_a_value_is_read_once_per_site() -> None:
    site = Site()
    cache: SiteCache[str] = SiteCache()

    first = await cache.read("plasmodb", site.value)
    again = await cache.read("plasmodb", site.value)
    other = await cache.read("toxodb", site.value)

    assert (first, again, other) == ("plasmodb value", "plasmodb value", "toxodb value")
    assert site.reads == ["plasmodb", "toxodb"]
