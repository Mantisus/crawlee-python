from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from crawlee._utils.docs import docs_group
from crawlee.crawlers._abstract_http import AbstractHttpParser
from crawlee.crawlers._types import BlockedInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from crawlee.http_clients import HttpResponse


@docs_group('HTTP parsers')
class NoParser(AbstractHttpParser[bytes, bytes]):
    """A no-op parser that returns raw response content without any processing.

    This is useful when you only need the raw response data and don't require HTML
    parsing, link extraction, or content selection functionality.
    """

    @override
    async def parse(self, response: HttpResponse) -> bytes:
        return await response.read()

    @override
    async def parse_text(self, text: str) -> bytes:
        raise NotImplementedError

    @override
    async def select(self, parsed_content: bytes, selector: str) -> Sequence[bytes]:
        raise NotImplementedError

    @override
    def is_blocked(self, parsed_content: bytes) -> BlockedInfo:  # Intentional unused argument.
        return BlockedInfo(reason='')

    @override
    def is_matching_selector(self, parsed_content: bytes, selector: str) -> bool:  # Intentional unused argument.
        return False

    @override
    def find_links(self, parsed_content: bytes, selector: str) -> Iterable[str]:  # Intentional unused argument.
        return []
