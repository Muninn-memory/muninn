from __future__ import annotations

import json
import os
from urllib.parse import quote_plus

from huginn.config import get_settings

PLAYWRIGHT_INSTALL_HINT = (
    "Browser runtime indisponivel. Corrija com:\n"
    "1) .\\.venv\\Scripts\\Activate.ps1\n"
    "2) playwright install chromium"
)


def _import_async_playwright():
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"playwright unavailable: {exc}") from exc
    return async_playwright


async def preflight_browser_runtime(*, headless: bool) -> None:
    """
    Valida runtime de browser no startup.
    Falha se Playwright nao puder importar ou iniciar/fechar Chromium.
    """
    async_playwright = _import_async_playwright()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            await browser.close()
    except Exception as exc:
        raise RuntimeError(f"{PLAYWRIGHT_INSTALL_HINT}\nOriginal: {exc}") from exc


async def browser_navigate(
    *,
    task: str,
    url: str | None = None,
    screenshot: bool = False,
) -> dict[str, object]:
    """
    Browser efemero para tarefas de navegacao.
    Em caso de indisponibilidade do Playwright, retorna erro estruturado.
    """
    settings = get_settings()
    if not settings.browser_tools_enabled:
        return {"status": "disabled", "message": "browser tools disabled by config"}

    try:
        async_playwright = _import_async_playwright()
    except RuntimeError as exc:
        return {"status": "error", "message": f"playwright unavailable: {exc}"}

    target_url = (url or "").strip() or f"https://duckduckgo.com/?q={quote_plus(task)}"
    screenshot_path = ""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.browser_headless)
            page = await browser.new_page()
            await page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=settings.exec_timeout_seconds * 1000,
            )
            await page.wait_for_timeout(800)
            title = await page.title()
            body_excerpt = await page.evaluate("() => document.body.innerText.slice(0, 2200)")

            if screenshot:
                os.makedirs("logs", exist_ok=True)
                screenshot_path = os.path.join(
                    "logs", f"browser_{settings.huginn_mode}_{int(os.times().elapsed)}.png"
                )
                await page.screenshot(path=screenshot_path, full_page=True)

            await browser.close()
        return {
            "status": "ok",
            "task": task,
            "url": target_url,
            "title": title,
            "excerpt": body_excerpt,
            "screenshot": screenshot_path,
        }
    except Exception as exc:
        return {
            "status": "error",
            "task": task,
            "url": target_url,
            "message": str(exc),
        }


def browser_result_to_text(result: dict[str, object]) -> str:
    if result.get("status") != "ok":
        return f"browser_navigate falhou: {result.get('message', 'erro desconhecido')}"
    payload = {
        "title": result.get("title", ""),
        "url": result.get("url", ""),
        "excerpt": result.get("excerpt", ""),
        "screenshot": result.get("screenshot", ""),
    }
    return json.dumps(payload, ensure_ascii=False)
