from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncGenerator, Iterable, Literal

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from crawlee import EnqueueStrategy
from crawlee._request import BaseRequestData
from crawlee._utils.blocked import RETRY_CSS_SELECTORS
from crawlee._utils.docs import docs_group
from crawlee._utils.urls import convert_to_absolute_url, is_url_absolute
from crawlee.basic_crawler import BasicCrawler, BasicCrawlerOptions, ContextPipeline
from crawlee.beautifulsoup_crawler._beautifulsoup_crawling_context import BeautifulSoupCrawlingContext
from crawlee.errors import SessionError
from crawlee.http_clients import HttpxHttpClient
from crawlee.http_crawler import HttpCrawlingContext

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from crawlee._types import BasicCrawlingContext, EnqueueLinksKwargs

BeautifulSoupParser = Literal['html.parser', 'lxml', 'xml', 'html5lib']


@docs_group('Classes')
class BeautifulSoupCrawler(BasicCrawler[BeautifulSoupCrawlingContext]):
    """A web crawler for performing HTTP requests and parsing HTML/XML content.

    The `BeautifulSoupCrawler` builds on top of the `BasicCrawler`, which means it inherits all of its features.
    On top of that it implements the HTTP communication using the HTTP clients and HTML/XML parsing using the
    `BeautifulSoup` library. The class allows integration with any HTTP client that implements the `BaseHttpClient`
    interface. The HTTP client is provided to the crawler as an input parameter to the constructor.

    The HTTP client-based crawlers are ideal for websites that do not require JavaScript execution. However,
    if you need to execute client-side JavaScript, consider using browser-based crawler like the `PlaywrightCrawler`.

    ### Usage

    ```python
    from crawlee.beautifulsoup_crawler import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

    crawler = BeautifulSoupCrawler()

    # Define the default request handler, which will be called for every request.
    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        context.log.info(f'Processing {context.request.url} ...')

        # Extract data from the page.
        data = {
            'url': context.request.url,
            'title': context.soup.title.string if context.soup.title else None,
        }

        # Push the extracted data to the default dataset.
        await context.push_data(data)

    await crawler.run(['https://crawlee.dev/'])
    ```
    """

    def __init__(
        self,
        *,
        parser: BeautifulSoupParser = 'lxml',
        additional_http_error_status_codes: Iterable[int] = (),
        ignore_http_error_status_codes: Iterable[int] = (),
        **kwargs: Unpack[BasicCrawlerOptions[BeautifulSoupCrawlingContext]],
    ) -> None:
        """A default constructor.

        Args:
            parser: The type of parser that should be used by `BeautifulSoup`.
            additional_http_error_status_codes: Additional HTTP status codes to treat as errors, triggering
                automatic retries when encountered.
            ignore_http_error_status_codes: HTTP status codes typically considered errors but to be treated
                as successful responses.
            kwargs: Additional keyword arguments to pass to the underlying `BasicCrawler`.
        """
        self._parser = parser

        kwargs['_context_pipeline'] = (
            ContextPipeline()
            .compose(self._make_http_request)
            .compose(self._parse_http_response)
            .compose(self._handle_blocked_request)
        )

        kwargs.setdefault(
            'http_client',
            HttpxHttpClient(
                additional_http_error_status_codes=additional_http_error_status_codes,
                ignore_http_error_status_codes=ignore_http_error_status_codes,
            ),
        )

        kwargs.setdefault('_logger', logging.getLogger(__name__))

        super().__init__(**kwargs)

    async def _make_http_request(self, context: BasicCrawlingContext) -> AsyncGenerator[HttpCrawlingContext, None]:
        """Executes an HTTP request using a configured HTTP client.

        Args:
            context: The crawling context from the `BasicCrawler`.

        Yields:
            The enhanced crawling context with the HTTP response.
        """
        result = await self._http_client.crawl(
            request=context.request,
            session=context.session,
            proxy_info=context.proxy_info,
            statistics=self._statistics,
        )

        yield HttpCrawlingContext(
            request=context.request,
            session=context.session,
            proxy_info=context.proxy_info,
            add_requests=context.add_requests,
            send_request=context.send_request,
            push_data=context.push_data,
            use_state=context.use_state,
            get_key_value_store=context.get_key_value_store,
            log=context.log,
            http_response=result.http_response,
        )

    async def _handle_blocked_request(
        self,
        context: BeautifulSoupCrawlingContext,
    ) -> AsyncGenerator[BeautifulSoupCrawlingContext, None]:
        """Try to detect if the request is blocked based on the HTTP status code or the response content.

        Args:
            context: The current crawling context.

        Raises:
            SessionError: If the request is considered blocked.

        Yields:
            The original crawling context if no errors are detected.
        """
        if self._retry_on_blocked:
            status_code = context.http_response.status_code

            # TODO: refactor to avoid private member access
            # https://github.com/apify/crawlee-python/issues/708
            if (
                context.session
                and status_code not in self._http_client._ignore_http_error_status_codes  # noqa: SLF001
                and context.session.is_blocked_status_code(status_code=status_code)
            ):
                raise SessionError(f'Assuming the session is blocked based on HTTP status code {status_code}')

            matched_selectors = [
                selector for selector in RETRY_CSS_SELECTORS if context.soup.select_one(selector) is not None
            ]

            if matched_selectors:
                raise SessionError(
                    'Assuming the session is blocked - '
                    f"HTTP response matched the following selectors: {'; '.join(matched_selectors)}"
                )

        yield context

    async def _parse_http_response(
        self,
        context: HttpCrawlingContext,
    ) -> AsyncGenerator[BeautifulSoupCrawlingContext, None]:
        """Parse the HTTP response using the `BeautifulSoup` library and implements the `enqueue_links` function.

        Args:
            context: The current crawling context.

        Yields:
            The enhanced crawling context with the `BeautifulSoup` selector and the `enqueue_links` function.
        """
        soup = await asyncio.to_thread(lambda: BeautifulSoup(context.http_response.read(), self._parser))

        async def enqueue_links(
            *,
            selector: str = 'a',
            label: str | None = None,
            user_data: dict[str, Any] | None = None,
            **kwargs: Unpack[EnqueueLinksKwargs],
        ) -> None:
            kwargs.setdefault('strategy', EnqueueStrategy.SAME_HOSTNAME)

            requests = list[BaseRequestData]()
            user_data = user_data or {}

            link: Tag
            for link in soup.select(selector):
                link_user_data = user_data

                if label is not None:
                    link_user_data.setdefault('label', label)

                if (url := link.attrs.get('href')) is not None:
                    url = url.strip()

                    if not is_url_absolute(url):
                        url = convert_to_absolute_url(context.request.url, url)

                    try:
                        request = BaseRequestData.from_url(url, user_data=link_user_data)
                    except ValidationError as exc:
                        context.log.debug(
                            f'Skipping URL "{url}" due to invalid format: {exc}. '
                            'This may be caused by a malformed URL or unsupported URL scheme. '
                            'Please ensure the URL is correct and retry.'
                        )
                        continue

                    requests.append(request)

            await context.add_requests(requests, **kwargs)

        yield BeautifulSoupCrawlingContext(
            request=context.request,
            session=context.session,
            proxy_info=context.proxy_info,
            enqueue_links=enqueue_links,
            add_requests=context.add_requests,
            send_request=context.send_request,
            push_data=context.push_data,
            use_state=context.use_state,
            get_key_value_store=context.get_key_value_store,
            log=context.log,
            http_response=context.http_response,
            soup=soup,
        )
