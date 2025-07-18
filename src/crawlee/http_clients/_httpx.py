from __future__ import annotations

from contextlib import asynccontextmanager
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import httpx
from typing_extensions import override

from crawlee._types import HttpHeaders
from crawlee._utils.blocked import ROTATE_PROXY_ERRORS
from crawlee._utils.docs import docs_group
from crawlee.errors import ProxyError
from crawlee.fingerprint_suite import HeaderGenerator
from crawlee.http_clients import HttpClient, HttpCrawlingResult, HttpResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from datetime import timedelta
    from ssl import SSLContext

    from crawlee import Request
    from crawlee._types import HttpMethod, HttpPayload
    from crawlee.proxy_configuration import ProxyInfo
    from crawlee.sessions import Session
    from crawlee.statistics import Statistics

logger = getLogger(__name__)


class _HttpxResponse:
    """Adapter class for `httpx.Response` to conform to the `HttpResponse` protocol."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def http_version(self) -> str:
        return self._response.http_version

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> HttpHeaders:
        return HttpHeaders(dict(self._response.headers))

    async def read(self) -> bytes:
        if not self._response.is_closed:
            raise RuntimeError('Use `read_stream` to read the body of the Response received from the `stream` method')
        return await self._response.aread()

    async def read_stream(self) -> AsyncIterator[bytes]:
        if self._response.is_stream_consumed:
            raise RuntimeError('Stream is already consumed.')
        else:
            async for chunk in self._response.aiter_bytes():
                yield chunk


class _HttpxTransport(httpx.AsyncHTTPTransport):
    """HTTP transport adapter that stores response cookies in a `Session`.

    This transport adapter modifies the handling of HTTP requests to update the session cookies
    based on the response cookies, ensuring that the cookies are stored in the session object
    rather than the `HTTPX` client itself.
    """

    @override
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        response.request = request

        if session := cast('Session', request.extensions.get('crawlee_session')):
            session.cookies.store_cookies(list(response.cookies.jar))

        if 'Set-Cookie' in response.headers:
            del response.headers['Set-Cookie']

        return response


@docs_group('HTTP clients')
class HttpxHttpClient(HttpClient):
    """HTTP client based on the `HTTPX` library.

    This client uses the `HTTPX` library to perform HTTP requests in crawlers (`BasicCrawler` subclasses)
    and to manage sessions, proxies, and error handling.

    See the `HttpClient` class for more common information about HTTP clients.

    ### Usage

    ```python
    from crawlee.crawlers import HttpCrawler  # or any other HTTP client-based crawler
    from crawlee.http_clients import HttpxHttpClient

    http_client = HttpxHttpClient()
    crawler = HttpCrawler(http_client=http_client)
    ```
    """

    _DEFAULT_HEADER_GENERATOR = HeaderGenerator()

    def __init__(
        self,
        *,
        persist_cookies_per_session: bool = True,
        http1: bool = True,
        http2: bool = True,
        verify: str | bool | SSLContext = True,
        header_generator: HeaderGenerator | None = _DEFAULT_HEADER_GENERATOR,
        **async_client_kwargs: Any,
    ) -> None:
        """Initialize a new instance.

        Args:
            persist_cookies_per_session: Whether to persist cookies per HTTP session.
            http1: Whether to enable HTTP/1.1 support.
            http2: Whether to enable HTTP/2 support.
            verify: SSL certificates used to verify the identity of requested hosts.
            header_generator: Header generator instance to use for generating common headers.
            async_client_kwargs: Additional keyword arguments for `httpx.AsyncClient`.
        """
        super().__init__(
            persist_cookies_per_session=persist_cookies_per_session,
        )
        self._http1 = http1
        self._http2 = http2

        self._async_client_kwargs = async_client_kwargs
        self._header_generator = header_generator

        self._ssl_context = httpx.create_ssl_context(verify=verify)

        self._transport: _HttpxTransport | None = None

        self._client_by_proxy_url = dict[str | None, httpx.AsyncClient]()

    @override
    async def crawl(
        self,
        request: Request,
        *,
        session: Session | None = None,
        proxy_info: ProxyInfo | None = None,
        statistics: Statistics | None = None,
    ) -> HttpCrawlingResult:
        client = self._get_client(proxy_info.url if proxy_info else None)
        headers = self._combine_headers(request.headers)

        http_request = client.build_request(
            url=request.url,
            method=request.method,
            headers=headers,
            content=request.payload,
            cookies=session.cookies.jar if session else None,
            extensions={'crawlee_session': session if self._persist_cookies_per_session else None},
        )

        try:
            response = await client.send(http_request)
        except httpx.TransportError as exc:
            if self._is_proxy_error(exc):
                raise ProxyError from exc
            raise

        if statistics:
            statistics.register_status_code(response.status_code)

        request.loaded_url = str(response.url)

        return HttpCrawlingResult(
            http_response=_HttpxResponse(response),
        )

    @override
    async def send_request(
        self,
        url: str,
        *,
        method: HttpMethod = 'GET',
        headers: HttpHeaders | dict[str, str] | None = None,
        payload: HttpPayload | None = None,
        session: Session | None = None,
        proxy_info: ProxyInfo | None = None,
    ) -> HttpResponse:
        client = self._get_client(proxy_info.url if proxy_info else None)

        http_request = self._build_request(
            client=client,
            url=url,
            method=method,
            headers=headers,
            payload=payload,
            session=session,
        )

        try:
            response = await client.send(http_request)
        except httpx.TransportError as exc:
            if self._is_proxy_error(exc):
                raise ProxyError from exc
            raise

        return _HttpxResponse(response)

    @asynccontextmanager
    @override
    async def stream(
        self,
        url: str,
        *,
        method: HttpMethod = 'GET',
        headers: HttpHeaders | dict[str, str] | None = None,
        payload: HttpPayload | None = None,
        session: Session | None = None,
        proxy_info: ProxyInfo | None = None,
        timeout: timedelta | None = None,
    ) -> AsyncGenerator[HttpResponse]:
        client = self._get_client(proxy_info.url if proxy_info else None)

        http_request = self._build_request(
            client=client,
            url=url,
            method=method,
            headers=headers,
            payload=payload,
            session=session,
            timeout=timeout,
        )

        response = await client.send(http_request, stream=True)

        try:
            yield _HttpxResponse(response)
        finally:
            await response.aclose()

    def _build_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        method: HttpMethod,
        headers: HttpHeaders | dict[str, str] | None,
        payload: HttpPayload | None,
        session: Session | None = None,
        timeout: timedelta | None = None,
    ) -> httpx.Request:
        """Build an `httpx.Request` using the provided parameters."""
        if isinstance(headers, dict) or headers is None:
            headers = HttpHeaders(headers or {})

        headers = self._combine_headers(headers)

        httpx_timeout = httpx.Timeout(None, connect=timeout.total_seconds()) if timeout else None

        return client.build_request(
            url=url,
            method=method,
            headers=dict(headers) if headers else None,
            content=payload,
            extensions={'crawlee_session': session if self._persist_cookies_per_session else None},
            timeout=httpx_timeout,
        )

    def _get_client(self, proxy_url: str | None) -> httpx.AsyncClient:
        """Retrieve or create an HTTP client for the given proxy URL.

        If a client for the specified proxy URL does not exist, create and store a new one.
        """
        if not self._transport:
            # Configure connection pool limits and keep-alive connections for transport
            limits = self._async_client_kwargs.get(
                'limits', httpx.Limits(max_connections=1000, max_keepalive_connections=200)
            )

            self._transport = _HttpxTransport(
                http1=self._http1,
                http2=self._http2,
                verify=self._ssl_context,
                limits=limits,
            )

        if proxy_url not in self._client_by_proxy_url:
            # Prepare a default kwargs for the new client.
            kwargs: dict[str, Any] = {
                'proxy': proxy_url,
                'http1': self._http1,
                'http2': self._http2,
                'follow_redirects': True,
            }

            # Update the default kwargs with any additional user-provided kwargs.
            kwargs.update(self._async_client_kwargs)

            kwargs.update(
                {
                    'transport': self._transport,
                    'verify': self._ssl_context,
                }
            )

            client = httpx.AsyncClient(**kwargs)
            self._client_by_proxy_url[proxy_url] = client

        return self._client_by_proxy_url[proxy_url]

    def _combine_headers(self, explicit_headers: HttpHeaders | None) -> HttpHeaders | None:
        """Merge default headers with explicit headers for an HTTP request.

        Generate a final set of request headers by combining default headers, a random User-Agent header,
        and any explicitly provided headers.
        """
        common_headers = self._header_generator.get_common_headers() if self._header_generator else HttpHeaders()
        user_agent_header = (
            self._header_generator.get_random_user_agent_header() if self._header_generator else HttpHeaders()
        )
        explicit_headers = explicit_headers or HttpHeaders()
        headers = common_headers | user_agent_header | explicit_headers
        return headers if headers else None

    @staticmethod
    def _is_proxy_error(error: httpx.TransportError) -> bool:
        """Determine whether the given error is related to a proxy issue.

        Check if the error is an instance of `httpx.ProxyError` or if its message contains known proxy-related
        error keywords.
        """
        if isinstance(error, httpx.ProxyError):
            return True

        if any(needle in str(error) for needle in ROTATE_PROXY_ERRORS):  # noqa: SIM103
            return True

        return False

    async def cleanup(self) -> None:
        for client in self._client_by_proxy_url.values():
            await client.aclose()
        self._client_by_proxy_url.clear()
        if self._transport:
            await self._transport.aclose()
            self._transport = None
