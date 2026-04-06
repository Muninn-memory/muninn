from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from huginn.tools.browser import preflight_browser_runtime


class _FakeBrowser:
    async def close(self) -> None:
        return


class _FakeChromium:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail

    async def launch(self, *, headless: bool):
        _ = headless
        if self._fail:
            raise RuntimeError("Executable doesn't exist")
        return _FakeBrowser()


class _FakePlaywrightContext:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail

    async def __aenter__(self):
        return types.SimpleNamespace(chromium=_FakeChromium(fail=self._fail))

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        _ = (exc_type, exc, tb)
        return False


def _fake_async_playwright_factory(*, fail: bool):
    def _factory():
        return _FakePlaywrightContext(fail=fail)

    return _factory


class BrowserPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_succeeds_when_chromium_launches(self) -> None:
        with patch(
            "huginn.tools.browser._import_async_playwright",
            return_value=_fake_async_playwright_factory(fail=False),
        ):
            await preflight_browser_runtime(headless=True)

    async def test_preflight_fails_with_install_hint_when_chromium_missing(self) -> None:
        with patch(
            "huginn.tools.browser._import_async_playwright",
            return_value=_fake_async_playwright_factory(fail=True),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                await preflight_browser_runtime(headless=True)

        message = str(ctx.exception)
        self.assertIn(".\\.venv\\Scripts\\Activate.ps1", message)
        self.assertIn("playwright install chromium", message)
        self.assertIn("Executable doesn't exist", message)


if __name__ == "__main__":
    unittest.main()
