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

## Verizon business login workflow

The repository includes a Verizon-specific starter flow:

```bash
export VZW_BUSINESS_USERNAME="your_username"
export VZW_BUSINESS_PASSWORD="your_password"
export VZW_BUSINESS_OTP="123456"
python automation_agent.py workflows/verizon_business_login.yaml --headed
```

Because some enterprise login pages vary by session/account, selector fields can
be either a single string or a list of selector fallbacks.
The Verizon workflow also includes OTP selection/code-entry steps using
`VZW_BUSINESS_OTP` with optional fallbacks.
If `VZW_BUSINESS_OTP` is not set, the workflow prompts you at runtime for the
current OTP code (so rotating OTPs are handled each run).
In non-interactive cloud runs (no TTY), it can also wait for a runtime OTP file.
After authentication, the same workflow navigates to Verizon BYOD and validates
the BYOD route and core device-entry content are loaded.
OTP prompt timing is now gated to appear only when the OTP entry field is visible.
If Verizon routes to `/login/options`, the workflow selects the Password branch automatically.
The workflow now also fills BYOD fields and clicks **Confirm devices**.

### Get exact selectors from your network/browser

If a page uses anti-bot controls, run this helper from your own machine/network:

```bash
python discover_selectors.py \
  --url "https://mblogin.verizonwireless.com/account/business/login/unifiedlogin" \
  --headed \
  --wait-seconds 15
```

Then copy the most specific selectors (`#id`, `name`, `data-testid`) into your workflow.

## Workflow format

Each workflow file has:

- `settings`: runtime options (`headless`, `timeout_ms`, `slow_mo_ms`, `screenshot_dir`)
- `variables`: reusable values (`{{ variable_name }}`)
- `steps`: ordered browser actions

For selector-based actions, `selector` can be a single CSS/text selector string
or a list of selectors tried in order.
Set `continue_on_error: true` on a step when it is optional for some account flows.
Use `only_if_variable_set` / `only_if_variable_empty` for branch-like step control.
Use `only_if_selector` / `only_if_not_selector` to run steps only on matching screens.
Use `only_if_url_regex` / `only_if_not_url_regex` to gate steps by current URL.
Use `selector_state` (for example `visible`) to avoid hidden-element matches.

### Supported actions

- `goto` (`url`, optional `wait_until`)
- `fill` (`selector`, `value`, optional `clear`)
- `click` (`selector`, optional `button`, `click_count`, `delay_ms`)
- `type` (`selector`, `text`, optional `delay_ms`)
- `press` (`selector`, `key`)
- `select` (`selector`, and `value` or `values`)
- `check` / `uncheck` (`selector`)
- `wait_for_selector` (`selector`, optional `state`)
- `wait_for_url` (`url` or `contains` or `regex`, optional `timeout_ms`)
- `wait_for_timeout` (`ms`)
- `screenshot` (optional `path`, `full_page`)
- `extract_text` (`selector`, `save_as`)
- `extract_attr` (`selector`, `attr`, `save_as`)
- `set_variable` (`name`, optional `value`)
- `normalize_variable` (`name`, `mode` = `strip` or `digits_only`, optional `min_length`, `max_length`)
- `set_input_value` (`selector`, `value`, optional `selector_state`, `dispatch_events`)
- `prompt_variable` (`name`, optional `prompt`, `secret`, `if_empty_only`, `required`, `default`)
- `set_variable_from_file` (`name`, `path`, optional `if_empty_only`, `only_if_selector`, `timeout_ms`, `poll_interval_ms`, `delete_after_read`)
- `set_checkbox` (`selector`, `checked`)
- conditional step gates: `only_if_variable_set`, `only_if_variable_empty`
- selector-based gates: `only_if_selector`, `only_if_not_selector`
- URL-based gates: `only_if_url_regex`, `only_if_not_url_regex`
- `new_page`
- `close_page`

### Handling rotating OTP in non-interactive runs

When the OTP screen is reached and no `VZW_BUSINESS_OTP` is set, the Verizon
workflow waits for `.runtime/verizon_otp.txt`.

Run the workflow:

```bash
unset VZW_BUSINESS_OTP
xvfb-run -a python3 automation_agent.py workflows/verizon_business_login.yaml --headed
```

When Verizon sends your OTP, write it to the file from another shell:

```bash
mkdir -p .runtime
printf '%s' '123456' > .runtime/verizon_otp.txt
```

The agent reads it and (by default) deletes the file.

### BYOD form inputs

The Verizon workflow is currently configured to submit:

- number mode: **I want a new phone number**
- device IMEI: `358339770214328`
- SIM mode: **I have a physical SIM (pSIM) to activate**
- contract term: **Month to Month**

The only per-run BYOD variable is **SIM ICCID**:

- set `BYOD_SIM_ICCID` in env, or
- leave it unset and the workflow prompts: `Enter BYOD SIM ICCID (20 digits):`

Before clicking **Confirm devices**, the workflow now waits for the button to
be enabled. If it does not enable, BYOD input validation likely failed (most
commonly an invalid/format-mismatched ICCID).
The ICCID input is normalized to digits-only and validated to 20 digits before
submission. A pre-submit screenshot is saved to
`artifacts/screenshots/byod_before_confirm.png`.
The flow also attempts to dismiss the cookie banner and explicitly sets the
promo toggle checkbox off for the Month-to-Month selection path.
If the visual toggle still appears ON, a forced fallback click is applied.
BYOD field targeting prefers Verizon form control selectors (for example,
`formcontrolname='deviceId'`, `simType`, and `simId`) for stability.

## Example snippet

```yaml
variables:
  username: "${APP_USERNAME}"

steps:
  - action: goto
    url: "https://example.com/login"
  - action: fill
    selector:
      - "input#username"
      - "input[name='username']"
    value: "{{ username }}"
  - action: click
    selector:
      - "button[type='submit']"
      - "button:has-text('Sign in')"
```

## Notes for production workflows

- Use stable selectors (IDs, data-testid, or name attributes).
- Keep secrets in environment variables, never directly in YAML.
- Add screenshots after critical clicks/submissions for auditability.
- For websites with bot protection/CAPTCHAs, a manual or API-assisted step may still be required.
