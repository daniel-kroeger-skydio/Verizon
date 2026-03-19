#!/usr/bin/env python3
"""
Quick helper to inspect a live page and print candidate selectors.
Run this from an environment/network where the target site is reachable.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from playwright.sync_api import sync_playwright


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover form/button selectors on a page.")
    parser.add_argument("--url", required=True, help="Page URL to inspect.")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (useful for login pages/challenges).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=8,
        help="Seconds to wait before scraping selectors.",
    )
    return parser


def discover(url: str, headed: bool, wait_seconds: int) -> Dict[str, Any]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(wait_seconds * 1000)
        data = page.evaluate(
            """() => {
              const makeSelectors = (el) => {
                const out = [];
                const tag = el.tagName.toLowerCase();
                const esc = (v) => (window.CSS && CSS.escape ? CSS.escape(v) : v);
                const id = el.getAttribute('id');
                const name = el.getAttribute('name');
                const testid = el.getAttribute('data-testid');
                const type = el.getAttribute('type');
                const aria = el.getAttribute('aria-label');
                if (id) out.push(`#${esc(id)}`);
                if (name) out.push(`${tag}[name="${name}"]`);
                if (testid) out.push(`${tag}[data-testid="${testid}"]`);
                if (type) out.push(`${tag}[type="${type}"]`);
                if (aria) out.push(`${tag}[aria-label="${aria}"]`);
                return [...new Set(out)];
              };

              const summarize = (el) => ({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                id: el.getAttribute('id') || '',
                name: el.getAttribute('name') || '',
                placeholder: el.getAttribute('placeholder') || '',
                aria_label: el.getAttribute('aria-label') || '',
                text: (el.innerText || '').trim().slice(0, 120),
                selectors: makeSelectors(el),
              });

              return {
                title: document.title,
                url: location.href,
                inputs: Array.from(document.querySelectorAll('input, textarea')).map(summarize),
                buttons: Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]')).map(summarize),
              };
            }"""
        )
        status = response.status if response else None
        context.close()
        browser.close()
    data["http_status"] = status
    return data


def main() -> int:
    args = build_parser().parse_args()
    result = discover(args.url, args.headed, args.wait_seconds)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
