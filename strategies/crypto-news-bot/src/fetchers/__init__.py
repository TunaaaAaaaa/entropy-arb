from .rss_fetcher import RSSFetcher

FETCHER_FACTORIES = {"rss": RSSFetcher}


def build_fetchers(config):
    return [FETCHER_FACTORIES[kind](settings) for kind, settings in config.get("sources", {}).items()]
