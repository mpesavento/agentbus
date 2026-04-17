# Build Plan: swarmbus init

**Spec:** `docs/superpowers/specs/2026-04-17-swarmbus-init.md`  
**Status:** Ready to execute  
**Created:** 2026-04-17  
**Estimated scope:** ~300 lines Python + tests; touches cli.py, adds tests/test_init.py

---

## Pre-work: read before starting

- `src/swarmbus/cli.py` — existing click group, understand command pattern
- `scripts/install-systemd.sh` — args interface (replicate in init's subprocess call)
- `scripts/setup-mosquitto.sh` — args interface
- `scripts/setup-cc-plugin.sh` and `setup-openclaw-plugin.sh` — args interface
- `tests/test_cli.py` or equivalent — existing test patterns

---

## Step 0: Doctor terminal colors

**File:** `src/swarmbus/cli.py` — `doctor` command, lines ~688–707

The doctor command already has `icon = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "·"}`.
Wrap each status line with `click.style()`. No new imports needed — `click` is already a dep.

```python
# Replace the render block:
icon_char = {"ok": "✓", "warn": "⚠", "fail": "✗", "skip": "·"}
color_map = {"ok": "green", "warn": "yellow", "fail": "red", "skip": None}

for i, (label, status, hint) in enumerate(results, 1):
    char = icon_char[status]
    fg = color_map[status]
    line = f"  [{char}] {i}. {label}"
    click.echo(click.style(line, fg=fg, bold=(status == "fail")))
    if hint:
        click.echo(f"        fix: {hint}")
```

`click.style()` is a no-op on non-TTY (pipes, logs) — no color=None needed; click handles it.

**Verify:** `swarmbus doctor --agent-id sparrow` shows green ✓, red ✗, yellow ⚠.

---

## Step 1: Add platform detection utility

**File:** `src/swarmbus/platform.py` (new)

```python
# Returns: "debian", "macos", "unknown"
def detect_platform() -> str: ...

# Returns: "rpi", "x86", "arm", "unknown"  
def detect_arch() -> str: ...

# Returns path to repo root (where scripts/ lives), or None.
# Walks up from swarmbus/__file__ looking for a scripts/ directory.
# Returns None for PyPI installs (scripts/ not in site-packages).
def find_repo_root() -> str | None: ...

# Resolves --broker value to actual hostname/IP.
# "tailscale" → runs `tailscale ip -4`, returns first IPv4.
# Any other value → returned as-is.
# Raises RuntimeError with clear message if tailscale CLI not found.
def resolve_broker_addr(broker: str) -> str: ...
```

Tests: mock `platform.system()`, `/proc/cpuinfo`, `shutil.which("apt")`, `shutil.which("tailscale")`.

For `detect_arch()`: mock `/proc/cpuinfo` content for RPi ("Raspberry Pi" string present),
mock `platform.machine()` for x86_64 and aarch64.

For `find_repo_root()`: test with `__file__` inside a temp dir that has `scripts/` N levels up
(found case), and without `scripts/` anywhere (returns None).

For `resolve_broker_addr()`: mock subprocess for tailscale IP; test non-tailscale passthrough;
test tailscale-not-found raises RuntimeError.

**Verify:** `python -c "from swarmbus.platform import detect_platform; print(detect_platform())"`

---

## Step 2: Add `init` subcommand skeleton

**File:** `src/swarmbus/cli.py` — append after existing commands

```python
@main.command()
@click.option("--agent-id", required=True, ...)
@click.option("--host-type", type=click.Choice(["cc", "openclaw", "none"]), default="none")
@click.option("--broker", default="localhost")
@click.option("--invoke", default=None)
@click.option("--inbox", default=None)
@click.option("--skip-broker", is_flag=True)
@click.option("--skip-plugin", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", is_flag=True)
def init(agent_id, host_type, broker, invoke, inbox, skip_broker, skip_plugin, dry_run, yes):
    """One-command agent setup: broker, daemon, plugin, doctor."""
    ...
```

At this stage: just flag validation + `--dry-run` print of planned steps. No subprocess calls yet.

**Verify:** `swarmbus init --help` shows all flags. `swarmbus init --dry-run --agent-id test` prints step plan.

---

## Step 3: Implement step functions

Each step is `_run_step(label, cmd, dry_run) -> bool`. The function:
1. Prints `Step N/M  Label ..... (running)`
2. In dry-run: prints `  would run: <cmd>` and returns True
3. In real mode: `subprocess.run(cmd, capture_output=True, text=True)`, prints stdout+stderr on failure
4. Returns True/False (both stdout and stderr surfaced on failure — setup scripts print to stdout)

Implement and wire the six steps:
1. `_step_broker(platform, broker, scripts_dir, dry_run, yes) -> bool`
   - `--broker tailscale`: call `resolve_broker_addr("tailscale")` to get actual IP for later steps;
     pass `--tailscale` to setup-mosquitto.sh
   - debian: `scripts/setup-mosquitto.sh [--tailscale|--tailscale-only]`
   - macOS+brew: `brew install mosquitto && brew services start mosquitto`
   - macOS+no-brew: print manual instructions; with `--yes` continue; without `--yes` prompt
   - **On failure: print error and call `sys.exit(1)` immediately — don't continue to systemd**
2. `_step_package(dry_run) -> bool`
3. `_step_systemd(agent_id, broker_addr, inbox, invoke, scripts_dir, dry_run) -> bool`
   - `broker_addr` is the resolved address (never the literal "tailscale")
4. `_step_wake_wrapper(agent_id, host_type, invoke, dry_run) -> bool`
   - If `invoke` is None (not supplied and repo_root was None): print `⚠ warn`, return True (not fail)
   - If invoke path doesn't exist on disk: same warn+skip
   - If invoke exists: verify it's executable, print path
5. `_step_plugin(agent_id, host_type, broker, scripts_dir, dry_run) -> bool`
   - cc: `scripts/setup-cc-plugin.sh <agent_id> <broker>` (positional args, not flags)
   - openclaw: `scripts/setup-openclaw-plugin.sh <agent_id> <broker>` (positional args)
   - none or --skip-plugin: skip
6. `_step_doctor(agent_id, dry_run) -> bool`

Wire them in sequence inside `init`. After step 1, early-exit on failure. Collect pass/fail for steps 2-6. Print summary.

**Verify:** `swarmbus init --dry-run --agent-id test --host-type cc` — all 6 steps print, exit 0.

---

## Step 4: Invoke derivation from host-type

If `--invoke` not set, derive from `--host-type`:

```python
def _derive_invoke(host_type: str, agent_id: str, repo_root: str | None) -> str | None:
    if repo_root is None:
        return None  # PyPI install — user must supply --invoke manually
    if host_type == "cc":
        return f"{repo_root}/examples/claude-code-wake.sh {agent_id}"
    if host_type == "openclaw":
        return f"{repo_root}/examples/openclaw-wake.sh {agent_id}"
    return None  # archive-only
```

`repo_root` from `find_repo_root()`. When None (PyPI install, no `--invoke` supplied):
- `_step_wake_wrapper` prints: `⚠ wake wrapper: scripts not found — pass --invoke <path> to wire reactive wake`
- Step returns True (warn, not fail) so init continues

**Verify:** `swarmbus init --dry-run --agent-id x --host-type cc` shows correct invoke path in step 3.

---

## Step 5: macOS broker handling

Platform detection returns "macos":
- Check `shutil.which("brew")`
- If present and not `--yes`: prompt "Install mosquitto via brew? [Y/n]"
- If yes (or `--yes`): run `brew install mosquitto && brew services start mosquitto`
- If no brew: print manual instructions, prompt "Press enter when mosquitto is running"
- If `--yes` and no brew: print instructions and continue (can't wait for confirm)

**Verify:** `swarmbus init --dry-run --agent-id x` on macOS prints correct branch.

---

## Step 6: Output formatting + exit codes

```
[swarmbus init] agent-id=<id> host-type=<ht> broker=<b>

Step 1/6  Broker ....................... ✓ mosquitto active (127.0.0.1:1883)
...

────────────────────────────
✓  <agent-id> is ready.

To set outbox archiving in your shell:
  export SWARMBUS_OUTBOX_<UPPER_ID>="$HOME/sync/<id>-outbox.md"

Send a test: swarmbus send --agent-id probe --to <id> --subject hello --body "init test"
────────────────────────────
```

On partial failure: print which steps failed, link to troubleshooting, exit 1.

**Verify:** run with a real agent-id on the RPi, confirm output matches spec.

---

## Step 7: Tests

**File:** `tests/test_init.py` (new)
**File:** `tests/test_platform.py` (new — separate file for platform.py unit tests)

### tests/test_platform.py

```python
# detect_platform()
def test_detect_platform_debian()          # mock shutil.which("apt") → truthy, sys="Linux" → "debian"
def test_detect_platform_macos()           # mock platform.system() → "Darwin" → "macos"
def test_detect_platform_linux_no_apt()    # sys="Linux", no apt → "unknown"
def test_detect_platform_other()           # sys="Windows" → "unknown"

# detect_arch()
def test_detect_arch_rpi()                 # mock /proc/cpuinfo to contain "Raspberry Pi" → "rpi"
def test_detect_arch_x86_64()              # mock platform.machine() → "x86_64" → "x86"
def test_detect_arch_aarch64()             # mock machine() → "aarch64" → "arm"
def test_detect_arch_unknown()             # no /proc/cpuinfo, unknown machine → "unknown"

# find_repo_root()
def test_find_repo_root_found(tmp_path)    # create tmp_path/a/b/scripts/, patch __file__ to a/b/c.py → returns tmp_path/a/b
def test_find_repo_root_not_found(tmp_path)# no scripts/ anywhere → None

# resolve_broker_addr()
def test_resolve_broker_addr_passthrough() # "localhost" → "localhost"
def test_resolve_broker_addr_tailscale()   # mock subprocess → "100.64.0.1"
def test_resolve_broker_addr_tailscale_missing() # shutil.which("tailscale") is None → RuntimeError
```

### tests/test_init.py

```python
# _run_step() unit tests
def test_run_step_dry_run()                # dry_run=True → prints command, returns True, no subprocess
def test_run_step_real_success()           # mock subprocess success → returns True
def test_run_step_real_failure()           # mock subprocess returncode=1 → returns False, prints stdout+stderr

# CLI flag validation (CliRunner, no subprocess)
def test_agent_id_valid()                  # [a-z0-9_-]+ accepted
def test_agent_id_invalid_chars()          # spaces, dots, slashes, uppercase → exit 2
def test_host_type_choices()               # cc/openclaw/none accepted; "docker" rejected
def test_help_shows_all_flags()            # --help exits 0, all flags present

# _derive_invoke()
def test_derive_invoke_cc()                # repo_root set, host-type cc → correct path
def test_derive_invoke_openclaw()          # repo_root set, host-type openclaw → correct path
def test_derive_invoke_none()              # host-type none → None
def test_derive_invoke_no_repo_root()      # repo_root=None → None regardless of host-type

# Smoke tests (dry-run via CliRunner, patches platform functions)
def test_dry_run_cc()                      # --dry-run --host-type cc exits 0, prints 6 steps
def test_dry_run_no_host()                 # --dry-run --host-type none exits 0, skips plugin step
def test_dry_run_shows_broker_step()       # broker step appears in dry-run output
def test_dry_run_skip_broker()             # --skip-broker → broker step marked skipped
def test_dry_run_skip_plugin()             # --skip-plugin → plugin step marked skipped

# _step_wake_wrapper behavior
def test_wake_wrapper_no_repo_root()       # repo_root=None, no --invoke → warns, returns True (not fail)
def test_wake_wrapper_path_exists()        # invoke path exists and executable → ok
def test_wake_wrapper_path_missing()       # invoke path doesn't exist → warns, returns True

# Step plugin positional args (verify subprocess call)
def test_plugin_step_cc_uses_positional_args()  # cc → subprocess gets [setup-cc-plugin.sh, id, broker]
def test_plugin_step_none_skipped()             # host-type none → no subprocess

# Exit code tests
def test_all_steps_pass_exits_0()          # mock all steps to succeed → exit 0
def test_broker_failure_exits_1()          # mock broker step to fail → exit 1 immediately
def test_partial_failure_exits_1()         # broker ok, doctor fail → exit 1
```

Run: `pytest tests/test_platform.py tests/test_init.py -v`

---

## Step 8: Update agent-onboarding.md

Replace steps 0-9 with:

```markdown
## Prerequisites

- Python 3.9+
- pip

## One-command setup

```bash
pip install "swarmbus[mcp]"
swarmbus init --agent-id <your-id> --host-type <cc|openclaw|none>
```

That's it. `init` installs the broker, configures systemd, installs the host plugin,
and runs doctor to verify. See `swarmbus init --help` for all options.
```

Keep the "healthy state" section and post-onboarding reading. Remove the 9-step walkthrough to a "Manual steps" collapsible or appendix for debugging.

---

## Step 9: Update README quickstart

Replace "Quickstart — two agents talking" step 3 (listener daemon) with:

```
swarmbus init --agent-id planner
swarmbus init --agent-id coder
```

---

## Step 10: Update post-ship-backlog

Mark `swarmbus init` as `[x]` with commit SHA.

---

## Completion criteria

- [ ] `swarmbus init --help` shows all flags
- [ ] `swarmbus init --dry-run --agent-id test --host-type cc` exits 0, prints 6-step plan
- [ ] `swarmbus init --agent-id sparrow --host-type cc` runs end-to-end on RPi, doctor passes
- [ ] `swarmbus doctor --agent-id sparrow` shows colored output (green ✓, red ✗, yellow ⚠)
- [ ] All unit tests pass (`pytest tests/test_platform.py tests/test_init.py -v`)
- [ ] `swarmbus init --broker tailscale --dry-run --agent-id x` shows resolved TS IP in step 3
- [ ] PyPI-install path: when `find_repo_root()` returns None and no `--invoke`, init warns (not fails)
- [ ] agent-onboarding.md reduced to ≤5 lines of user steps
- [ ] README quickstart updated

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 4 issues fixed, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**ENG REVIEW DECISIONS:**
- Added Step 0 (doctor terminal colors) — was in spec, missing from plan
- `resolve_broker_addr()` added to platform.py — `--broker tailscale` now resolves to actual TS IP before passing to systemd
- `_step_wake_wrapper()` gracefully handles PyPI installs (warns, doesn't fail)
- `_step_plugin()` uses positional args matching actual script interface
- Early exit on broker failure made explicit in Step 3
- Test plan expanded from 7 → ~30 tests; `tests/test_platform.py` added

**VERDICT:** ENG CLEARED — ready to implement.
