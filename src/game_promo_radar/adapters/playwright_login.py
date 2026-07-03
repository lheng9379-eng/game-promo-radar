from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def open_logged_in_page(url: str, profile_dir: str | Path = "data/browser-profile") -> str:
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        if "captcha" in page.content().lower() or "验证码" in page.content():
            input("检测到验证码，请在浏览器中手动完成后按 Enter 继续...")
        page.wait_for_timeout(1000)
        html = page.content()
        context.close()
    return html

