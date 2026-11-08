#!/usr/bin/env python3
"""
Batch resolver: read embed URLs from stdin (one per line),
launch one Chromium, and print  <m3u8-url>  per line on stdout
in the same order as input. Errors print 'ERROR: <msg>'.

Usage:
    cat urls.txt | python3 resolve-island.py > out.txt
"""
import sys
import time
from playwright.sync_api import sync_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)

# How long to wait for the player to fire /fetch -> m3u8 (seconds)
PER_CHANNEL_TIMEOUT = 30


def resolve_all(embed_urls):
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        ctx = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        # Block images/fonts to speed up page loads and reduce bandwidth
        ctx.route("**/*", lambda route: (
            route.abort()
            if route.request.resource_type in ("image", "font", "media")
            else route.continue_()
        ))

        for url in embed_urls:
            url = url.strip()
            if not url:
                results.append("ERROR: empty url")
                continue
            captured = {}
            page = ctx.new_page()

            def on_response(resp, c=captured):
                if ".m3u8" in resp.url and "m3u8" not in c:
                    c["m3u8"] = resp.url

            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                deadline = time.time() + PER_CHANNEL_TIMEOUT
                while time.time() < deadline and "m3u8" not in captured:
                    page.wait_for_timeout(500)
                if "m3u8" in captured:
                    results.append(captured["m3u8"])
                else:
                    results.append(f"ERROR: no m3u8 captured for {url}")
            except Exception as e:
                results.append(f"ERROR: {type(e).__name__}: {e}")
            finally:
                page.close()

        browser.close()
    return results


def main():
    urls = [line.rstrip("\n") for line in sys.stdin if line.strip()]
    if not urls:
        print("ERROR: no urls on stdin", file=sys.stderr)
        sys.exit(1)
    for line in resolve_all(urls):
        print(line)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
