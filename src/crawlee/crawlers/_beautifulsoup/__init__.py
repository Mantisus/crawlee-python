try:
    from ._beautifulsoup_crawler import BeautifulSoupCrawler
    from ._beautifulsoup_crawling_context import BeautifulSoupCrawlingContext
    from ._beautifulsoup_parser import BeautifulSoupParserType
except ImportError as exc:
    raise ImportError(
        "To import this, you need to install the 'beautifulsoup' extra. "
        "For example, if you use pip, run `pip install 'crawlee[beautifulsoup]'`.",
    ) from exc

__all__ = [
    'BeautifulSoupCrawler',
    'BeautifulSoupCrawlingContext',
    'BeautifulSoupParserType',
]
