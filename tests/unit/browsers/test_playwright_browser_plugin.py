from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from crawlee.browsers import PlaywrightBrowserPlugin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from yarl import URL


@pytest.fixture
async def plugin() -> AsyncGenerator[PlaywrightBrowserPlugin, None]:
    async with PlaywrightBrowserPlugin() as plugin:
        yield plugin


async def test_initial_state() -> None:
    plugin = PlaywrightBrowserPlugin(
        browser_type='chromium',
        browser_launch_options={'headless': False},
        browser_new_context_options={'viewport': {'width': 1920, 'height': 1080}},
        max_open_pages_per_browser=10,
    )

    # Test initial state
    assert plugin.browser_type == 'chromium'
    assert 'headless' in plugin.browser_launch_options
    assert plugin.browser_launch_options['headless'] is False
    assert plugin.browser_new_context_options == {'viewport': {'width': 1920, 'height': 1080}}
    assert plugin.max_open_pages_per_browser == 10


async def test_new_browser(plugin: PlaywrightBrowserPlugin, server_url: URL) -> None:
    browser_controller = await plugin.new_browser()

    assert browser_controller.is_browser_connected

    page = await browser_controller.new_page()
    await page.goto(str(server_url))

    await page.close()
    await browser_controller.close()

    assert not browser_controller.is_browser_connected


async def test_multiple_new_browsers(plugin: PlaywrightBrowserPlugin) -> None:
    browser_controller_1 = await plugin.new_browser()
    browser_controller_2 = await plugin.new_browser()

    assert browser_controller_1 is not browser_controller_2


async def test_methods_raise_error_when_not_active() -> None:
    plugin = PlaywrightBrowserPlugin()

    assert plugin.active is False

    with pytest.raises(RuntimeError, match=r'Plugin is not active'):
        await plugin.new_browser()

    with pytest.raises(RuntimeError, match=r'Plugin is already active.'):
        async with plugin, plugin:
            pass

    async with plugin:
        assert plugin.active is True


async def raise_error_if_use_chrome_and_executable_path() -> None:
    with pytest.raises(
        ValueError, match=r'Cannot use `use_chrome` with `Configuration.default_browser_path` or `executable_path` set.'
    ):
        PlaywrightBrowserPlugin(
            browser_type='chromium',
            use_chrome=True,
            browser_launch_options={'executable_path': '/path/to/chrome'},
        )


async def raise_error_if_use_chrome_with_firefox() -> None:
    with pytest.raises(ValueError, match=r'`use_chrome` can only be used with `chromium` `browser_type`.'):
        PlaywrightBrowserPlugin(
            browser_type='firefox',
            use_chrome=True,
        )
