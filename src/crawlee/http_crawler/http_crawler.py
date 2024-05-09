from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator, Iterable

from typing_extensions import Unpack

from crawlee.basic_crawler.basic_crawler import BasicCrawler, BasicCrawlerOptions
from crawlee.basic_crawler.context_pipeline import ContextPipeline
from crawlee.basic_crawler.errors import SessionError
from crawlee.http_clients.httpx_client import HttpxClient
from crawlee.http_crawler.types import HttpCrawlingContext

if TYPE_CHECKING:
    from crawlee.basic_crawler.types import BasicCrawlingContext


class HttpCrawler(BasicCrawler[HttpCrawlingContext]):
    """A crawler that fetches the request URL using `httpx`."""

    def __init__(
        self,
        *,
        additional_http_error_status_codes: Iterable[int] = (),
        ignore_http_error_status_codes: Iterable[int] = (),
        **kwargs: Unpack[BasicCrawlerOptions[HttpCrawlingContext]],
    ) -> None:
        """Initialize the HttpCrawler.

        Args:
            additional_http_error_status_codes: HTTP status codes that should be considered errors (and trigger a retry)

            ignore_http_error_status_codes: HTTP status codes that are normally considered errors but we want to treat
                them as successful

            kwargs: Arguments to be forwarded to the underlying BasicCrawler
        """
        kwargs['_context_pipeline'] = (
            ContextPipeline().compose(self._make_http_request).compose(self._handle_blocked_request)
        )

        kwargs.setdefault(
            'http_client',
            HttpxClient(
                additional_http_error_status_codes=additional_http_error_status_codes,
                ignore_http_error_status_codes=ignore_http_error_status_codes,
            ),
        )

        super().__init__(**kwargs)

    async def _make_http_request(
        self, crawling_context: BasicCrawlingContext
    ) -> AsyncGenerator[HttpCrawlingContext, None]:
        result = await self._http_client.crawl(crawling_context.request, crawling_context.session)

        yield HttpCrawlingContext(
            request=crawling_context.request,
            session=crawling_context.session,
            send_request=crawling_context.send_request,
            add_requests=crawling_context.add_requests,
            http_response=result.http_response,
        )

    async def _handle_blocked_request(
        self, crawling_context: HttpCrawlingContext
    ) -> AsyncGenerator[HttpCrawlingContext, None]:
        if self._retry_on_blocked:
            status_code = crawling_context.http_response.status_code

            if crawling_context.session and crawling_context.session.is_blocked_status_code(status_code=status_code):
                raise SessionError(f'Assuming the session is blocked based on HTTP status code {status_code}')

        yield crawling_context