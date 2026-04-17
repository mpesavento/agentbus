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

## Step 1: Add platform detection utility

**File:** `src/swarmbus/platform.py` (new)

```python
# Returns: "debian", "macos", "unknown"
def detect_platform() -> str: ...

# Returns: "rpi", "x86", "arm", "unknown"  
def detect_arch() -> str: ...

# Returns path to repo root (where scripts/ lives), or None
def find_repo_root() -> str | None: ...
```

Tests: mock `platform.system()`, `/proc/cpuinfo`, `shutil.which("apt")`.

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
3. In real mode: `subprocess.run(cmd, ...)`, captures stderr, prints on failure
4. Returns True/False

Implement and wire the six steps:
1. `_step_broker(platform, broker, scripts_dir, dry_run, yes)` 
2. `_step_package(dry_run)`
3. `_step_systemd(agent_id, broker, inbox, invoke, host_type, scripts_dir, dry_run)`
4. `_step_wake_wrapper(agent_id, host_type, scripts_dir, invoke, dry_run)`  
5. `_step_plugin(agent_id, host_type, scripts_dir, dry_run)`
6. `_step_doctor(agent_id, dry_run)`

Wire them in sequence inside `init`. Collect pass/fail. Print summary.

**Verify:** `swarmbus init --dry-run --agent-id test --host-type cc` — all 6 steps print, exit 0.

---

## Step 4: Invoke derivation from host-type

If `--invoke` not set, derive from `--host-type`:

```python
def _derive_invoke(host_type: str, agent_id: str, repo_root: str) -> str | None:
    if host_type == "cc":
        return f"{repo_root}/examples/claude-code-wake.sh {agent_id}"
    if host_type == "openclaw":
        return f"{repo_root}/examples/openclaw-wake.sh {agent_id}"
    return None  # archive-only
```

`repo_root` from `find_repo_root()`. If repo root not found, warn and skip wake wrapper step.

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

```python
# Unit tests (no subprocesses)
def test_agent_id_validation()  # rejects reserved names, bad chars
def test_host_type_choices()    # cc/openclaw/none accepted; other rejected
def test_derive_invoke_cc()     # correct path derivation
def test_derive_invoke_none()   # returns None for archive-only
def test_platform_detection()   # mocked; returns "debian"/"macos"/"unknown"

# Smoke tests (subprocess dry-run)
def test_dry_run_cc()           # --dry-run --host-type cc exits 0, prints 6 steps
def test_dry_run_no_host()      # --dry-run --host-type none exits 0, skips plugin step
```

Run: `pytest tests/test_init.py -v`

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
- [ ] All unit tests pass (`pytest tests/test_init.py -v`)
- [ ] agent-onboarding.md reduced to ≤5 lines of user steps
- [ ] README quickstart updated

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**VERDICT:** NO REVIEWS YET — ready to execute after eng review.
