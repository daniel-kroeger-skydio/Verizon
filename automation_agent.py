#!/usr/bin/env python3
"""
Config-driven browser automation agent powered by Playwright.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import yaml
from playwright.sync_api import sync_playwright


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
VAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def resolve_env_vars(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_vars(v) for v in value]
    if not isinstance(value, str):
        return value

    def repl(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.getenv(var_name, "")

    return ENV_PATTERN.sub(repl, value)


def render_template(value: Any, context: Dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: render_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, context) for v in value]
    if not isinstance(value, str):
        return value

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(context.get(key, ""))

    return VAR_PATTERN.sub(repl, value)


def read_workflow(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError("Workflow file must contain a top-level object.")
    resolved = resolve_env_vars(raw)
    steps = resolved.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Workflow must include a non-empty 'steps' list.")
    return resolved


def require(step: Dict[str, Any], key: str) -> Any:
    value = step.get(key)
    if value is None or value == "":
        raise ValueError(f"Step missing required field '{key}': {step}")
    return value


def _selector_candidates(raw: Any) -> List[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and raw and all(isinstance(item, str) and item for item in raw):
        return raw
    raise ValueError(
        "Selector must be a non-empty string or list of non-empty strings. "
        f"Got: {raw!r}"
    )


def resolve_selector(
    page: Any,
    raw_selector: Any,
    action: str,
    selector_timeout_ms: int = 2000,
    wait_state: str = "attached",
) -> str:
    candidates = _selector_candidates(raw_selector)
    for selector in candidates:
        try:
            page.wait_for_selector(selector, state=wait_state, timeout=selector_timeout_ms)
            return selector
        except Exception:
            continue
    raise ValueError(
        f"No selector candidate matched for action '{action}'. "
        f"Tried: {candidates}"
    )


def run_workflow(workflow_path: Path, headed_override: bool = False) -> None:
    workflow = read_workflow(workflow_path)
    name = workflow.get("name", workflow_path.stem)
    settings = workflow.get("settings", {}) or {}
    context: Dict[str, Any] = dict(workflow.get("variables", {}) or {})
    steps = workflow["steps"]

    headless = not headed_override and bool(settings.get("headless", True))
    timeout_ms = int(settings.get("timeout_ms", 15000))
    slow_mo_ms = int(settings.get("slow_mo_ms", 0))
    screenshot_dir = Path(settings.get("screenshot_dir", "artifacts/screenshots"))
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running workflow: {name}")
    print(f"Loaded {len(steps)} steps from {workflow_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        browser_context = browser.new_context()
        page = browser_context.new_page()
        page.set_default_timeout(timeout_ms)

        for i, raw_step in enumerate(steps, start=1):
            step = render_template(raw_step, context)
            action = step.get("action")
            if not action:
                raise ValueError(f"Step {i} does not define an action: {raw_step}")

            only_if_variable_set = step.get("only_if_variable_set")
            if only_if_variable_set is not None:
                keys = (
                    [only_if_variable_set]
                    if isinstance(only_if_variable_set, str)
                    else list(only_if_variable_set)
                )
                if not all(isinstance(k, str) and context.get(k) not in (None, "") for k in keys):
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_variable_set)")
                    continue

            only_if_variable_empty = step.get("only_if_variable_empty")
            if only_if_variable_empty is not None:
                keys = (
                    [only_if_variable_empty]
                    if isinstance(only_if_variable_empty, str)
                    else list(only_if_variable_empty)
                )
                if not all(isinstance(k, str) and context.get(k) in (None, "") for k in keys):
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_variable_empty)")
                    continue

            only_if_selector = step.get("only_if_selector")
            if only_if_selector is not None:
                try:
                    resolve_selector(
                        page,
                        only_if_selector,
                        action=action,
                        selector_timeout_ms=int(step.get("only_if_selector_timeout_ms", 1500)),
                        wait_state=str(step.get("only_if_selector_state", "attached")),
                    )
                except Exception:
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_selector)")
                    continue

            only_if_not_selector = step.get("only_if_not_selector")
            if only_if_not_selector is not None:
                try:
                    resolve_selector(
                        page,
                        only_if_not_selector,
                        action=action,
                        selector_timeout_ms=int(step.get("only_if_not_selector_timeout_ms", 1500)),
                        wait_state=str(step.get("only_if_not_selector_state", "attached")),
                    )
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_not_selector)")
                    continue
                except Exception:
                    pass

            only_if_url_regex = step.get("only_if_url_regex")
            if only_if_url_regex is not None:
                patterns = (
                    [only_if_url_regex]
                    if isinstance(only_if_url_regex, str)
                    else list(only_if_url_regex)
                )
                current_url = page.url
                if not any(re.search(str(pattern), current_url) for pattern in patterns):
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_url_regex)")
                    continue

            only_if_not_url_regex = step.get("only_if_not_url_regex")
            if only_if_not_url_regex is not None:
                patterns = (
                    [only_if_not_url_regex]
                    if isinstance(only_if_not_url_regex, str)
                    else list(only_if_not_url_regex)
                )
                current_url = page.url
                if any(re.search(str(pattern), current_url) for pattern in patterns):
                    print(f"[{i:02d}/{len(steps):02d}] {action} (skipped: only_if_not_url_regex)")
                    continue

            print(f"[{i:02d}/{len(steps):02d}] {action}")
            continue_on_error = bool(step.get("continue_on_error", False))
            try:
                if action == "goto":
                    url = require(step, "url")
                    wait_until = step.get("wait_until", "domcontentloaded")
                    page.goto(url, wait_until=wait_until)
                elif action == "fill":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    value = str(require(step, "value"))
                    if step.get("clear", True):
                        page.fill(selector, value)
                    else:
                        page.locator(selector).type(value)
                elif action == "click":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    page.click(
                        selector,
                        button=step.get("button", "left"),
                        click_count=int(step.get("click_count", 1)),
                        delay=float(step.get("delay_ms", 0)),
                    )
                elif action == "type":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    text = str(require(step, "text"))
                    page.locator(selector).type(text, delay=float(step.get("delay_ms", 0)))
                elif action == "press":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    key = str(require(step, "key"))
                    page.press(selector, key)
                elif action == "select":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    if "values" in step:
                        values = step["values"]
                    else:
                        values = require(step, "value")
                    page.select_option(selector, values)
                elif action == "check":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    page.check(selector, force=bool(step.get("force", False)))
                elif action == "uncheck":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    page.uncheck(selector, force=bool(step.get("force", False)))
                elif action == "set_checkbox":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    checked = bool(require(step, "checked"))
                    page.locator(selector).first.evaluate(
                        """(el, shouldCheck) => {
                            if (!(el instanceof HTMLInputElement) || el.type !== 'checkbox') {
                                throw new Error('set_checkbox target must be an <input type=\"checkbox\">');
                            }
                            el.checked = shouldCheck;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }""",
                        checked,
                    )
                elif action == "wait_for_selector":
                    state = step.get("state", "visible")
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", timeout_ms)),
                        wait_state=state,
                    )
                    page.wait_for_selector(selector, state=state)
                elif action == "wait_for_url":
                    wait_timeout_ms = int(step.get("timeout_ms", timeout_ms))
                    if "regex" in step:
                        pattern = re.compile(str(require(step, "regex")))
                        page.wait_for_url(pattern, timeout=wait_timeout_ms)
                    elif "contains" in step:
                        contains = str(require(step, "contains"))
                        pattern = re.compile(f".*{re.escape(contains)}.*")
                        page.wait_for_url(pattern, timeout=wait_timeout_ms)
                    else:
                        page.wait_for_url(str(require(step, "url")), timeout=wait_timeout_ms)
                elif action == "wait_for_timeout":
                    ms = int(require(step, "ms"))
                    page.wait_for_timeout(ms)
                elif action == "screenshot":
                    path_value = step.get("path")
                    if path_value:
                        screenshot_path = Path(path_value)
                    else:
                        screenshot_path = screenshot_dir / f"step_{i:02d}.png"
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=bool(step.get("full_page", False)))
                elif action == "extract_text":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    save_as = require(step, "save_as")
                    text = page.locator(selector).inner_text()
                    context[save_as] = text
                    print(f"    saved text into '{{{{ {save_as} }}}}'")
                elif action == "extract_attr":
                    selector = resolve_selector(
                        page,
                        require(step, "selector"),
                        action=action,
                        selector_timeout_ms=int(step.get("selector_timeout_ms", 2000)),
                    )
                    attr = require(step, "attr")
                    save_as = require(step, "save_as")
                    value = page.locator(selector).get_attribute(attr)
                    context[save_as] = "" if value is None else value
                    print(f"    saved attr into '{{{{ {save_as} }}}}'")
                elif action == "set_variable":
                    key = require(step, "name")
                    value = step.get("value", "")
                    context[str(key)] = value
                elif action == "normalize_variable":
                    key = str(require(step, "name"))
                    value = context.get(key, "")
                    if value is None:
                        value = ""
                    value = str(value)
                    mode = str(step.get("mode", "strip"))

                    if mode == "strip":
                        normalized = value.strip()
                    elif mode == "digits_only":
                        normalized = re.sub(r"[^0-9]", "", value)
                    else:
                        raise ValueError(f"Unsupported normalize mode '{mode}'")

                    min_length = step.get("min_length")
                    max_length = step.get("max_length")
                    if min_length is not None and len(normalized) < int(min_length):
                        raise ValueError(
                            f"Variable '{key}' has length {len(normalized)}; expected >= {int(min_length)}"
                        )
                    if max_length is not None and len(normalized) > int(max_length):
                        raise ValueError(
                            f"Variable '{key}' has length {len(normalized)}; expected <= {int(max_length)}"
                        )
                    context[key] = normalized
                elif action == "prompt_variable":
                    key = str(require(step, "name"))
                    if_empty_only = bool(step.get("if_empty_only", True))
                    required = bool(step.get("required", True))
                    secret = bool(step.get("secret", False))
                    default_value = step.get("default", "")

                    current = context.get(key)
                    if if_empty_only and current not in (None, ""):
                        continue

                    if not sys.stdin.isatty():
                        raise ValueError(
                            f"Step {i} requires interactive input for '{key}', but stdin is not a TTY. "
                            f"Set it in workflow variables or environment before running."
                        )

                    prompt_text = str(step.get("prompt", f"Enter value for {key}: "))
                    entered = (
                        getpass.getpass(prompt_text)
                        if secret
                        else input(prompt_text)
                    )
                    if entered == "":
                        entered = str(default_value)
                    if required and entered == "":
                        raise ValueError(f"Input required for variable '{key}'.")
                    context[key] = entered
                elif action == "set_variable_from_file":
                    key = str(require(step, "name"))
                    if_empty_only = bool(step.get("if_empty_only", True))
                    if if_empty_only and context.get(key) not in (None, ""):
                        continue

                    only_if_selector = step.get("only_if_selector")
                    if only_if_selector is not None:
                        try:
                            resolve_selector(
                                page,
                                only_if_selector,
                                action=action,
                                selector_timeout_ms=int(step.get("only_if_selector_timeout_ms", 1500)),
                            )
                        except Exception:
                            print(f"    skipped: selector for '{key}' not present")
                            continue

                    file_path = Path(str(require(step, "path")))
                    timeout_for_file_ms = int(step.get("timeout_ms", 300000))
                    poll_interval_ms = int(step.get("poll_interval_ms", 1000))
                    trim = bool(step.get("trim", True))
                    delete_after_read = bool(step.get("delete_after_read", False))

                    started = time.monotonic()
                    loaded_value = ""
                    while True:
                        if file_path.exists():
                            loaded_value = file_path.read_text(encoding="utf-8")
                            if trim:
                                loaded_value = loaded_value.strip()
                            if loaded_value != "":
                                break

                        elapsed_ms = int((time.monotonic() - started) * 1000)
                        if elapsed_ms >= timeout_for_file_ms:
                            raise ValueError(
                                f"Timed out waiting for value in '{file_path}' for variable '{key}'."
                            )
                        time.sleep(max(poll_interval_ms, 100) / 1000)

                    context[key] = loaded_value
                    if delete_after_read:
                        try:
                            file_path.unlink()
                        except OSError:
                            pass
                    print(f"    loaded variable '{key}' from file")
                elif action == "new_page":
                    page = browser_context.new_page()
                    page.set_default_timeout(timeout_ms)
                elif action == "close_page":
                    page.close()
                    page = browser_context.new_page()
                    page.set_default_timeout(timeout_ms)
                else:
                    raise ValueError(f"Unsupported action '{action}' in step {i}: {step}")
            except Exception as exc:
                if continue_on_error:
                    print(f"    warning: step failed but continuing (continue_on_error=true): {exc}")
                    continue
                raise

        browser_context.close()
        browser.close()

    print("Workflow completed successfully.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run website workflow automation from YAML.")
    parser.add_argument("workflow", type=Path, help="Path to YAML workflow file.")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (overrides workflow setting).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        run_workflow(args.workflow, headed_override=args.headed)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
