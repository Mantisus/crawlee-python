import asyncio

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext
from crawlee.proxy_configuration import ProxyConfiguration


async def main() -> None:
    # Create a ProxyConfiguration object and pass it to the crawler.
    proxy_configuration = ProxyConfiguration(
        proxy_urls=[
            'http://proxy-1.com/',
            'http://proxy-2.com/',
        ]
    )
    crawler = PlaywrightCrawler(proxy_configuration=proxy_configuration)

    # Define the default request handler, which will be called for every request.
    @crawler.router.default_handler
    async def default_handler(context: PlaywrightCrawlingContext) -> None:
        # Extract data from the page.
        data = {
            'url': context.request.url,
            'title': await context.page.title(),
        }
        context.log.info(f'Extracted data: {data}')

    # Run the crawler with the initial list of requests.
    await crawler.run(['https://crawlee.dev/'])


if __name__ == '__main__':
    asyncio.run(main())
