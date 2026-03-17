# Website Workflow Automation Agent

This repository contains a configurable browser automation agent that can:

- Open multiple websites in sequence
- Enter data into forms
- Click buttons/links
- Wait for page state changes
- Extract values and reuse them later
- Capture screenshots for verification

It uses [Playwright](https://playwright.dev/python/) and a YAML workflow file.

## 1) Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## 2) Create credentials as environment variables

```bash
export APP_USERNAME="your_username"
export APP_PASSWORD="your_password"
```

Environment variables are referenced in workflow files with `${VAR_NAME}` syntax.

## 3) Run the example workflow

```bash
python automation_agent.py workflows/example_workflow.yaml
```

If you want to see the browser:

```bash
python automation_agent.py workflows/example_workflow.yaml --headed
```

## Workflow format

Each workflow file has:

- `settings`: runtime options (`headless`, `timeout_ms`, `slow_mo_ms`, `screenshot_dir`)
- `variables`: reusable values (`{{ variable_name }}`)
- `steps`: ordered browser actions

### Supported actions

- `goto` (`url`, optional `wait_until`)
- `fill` (`selector`, `value`, optional `clear`)
- `click` (`selector`, optional `button`, `click_count`, `delay_ms`)
- `type` (`selector`, `text`, optional `delay_ms`)
- `press` (`selector`, `key`)
- `select` (`selector`, and `value` or `values`)
- `check` / `uncheck` (`selector`)
- `wait_for_selector` (`selector`, optional `state`)
- `wait_for_timeout` (`ms`)
- `screenshot` (optional `path`, `full_page`)
- `extract_text` (`selector`, `save_as`)
- `extract_attr` (`selector`, `attr`, `save_as`)
- `set_variable` (`name`, optional `value`)
- `new_page`
- `close_page`

## Example snippet

```yaml
variables:
  username: "${APP_USERNAME}"

steps:
  - action: goto
    url: "https://example.com/login"
  - action: fill
    selector: "input[name='username']"
    value: "{{ username }}"
  - action: click
    selector: "button[type='submit']"
```

## Notes for production workflows

- Use stable selectors (IDs, data-testid, or name attributes).
- Keep secrets in environment variables, never directly in YAML.
- Add screenshots after critical clicks/submissions for auditability.
- For websites with bot protection/CAPTCHAs, a manual or API-assisted step may still be required.
