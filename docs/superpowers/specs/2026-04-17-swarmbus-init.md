# Spec: swarmbus init

**Status:** Draft  
**Created:** 2026-04-17  
**Author:** Sparrow (Claude Code)  
**Context:** Post-deployment operational insight; see post-ship-backlog.md §2026-04-16

---

## Problem

Current onboarding requires 4-5 human-executed steps in a specific order:

1. Install mosquitto: `bash scripts/setup-mosquitto.sh`
2. Install Python package: `pip install "swarmbus[mcp]"`
3. Install systemd unit: `bash scripts/install-systemd.sh <agent-id> --invoke ...`
4. Optionally install host plugin: `bash scripts/setup-cc-plugin.sh <agent-id>`
5. Verify: `swarmbus doctor --agent-id <id>`

Each step has platform-specific variations (Debian vs macOS, tailscale vs local). The error surface is large — wrong order, wrong paths, stale daemon after pip upgrade, missing env vars. Agent onboarding doc is 9 steps long.

**Goal:** `swarmbus init --agent-id <id>` executes the entire sequence in one command. User provides agent identity and host type; init handles the rest and prints a `swarmbus start` command they can verify.

---

## Scope

### In scope (v1)

- New `swarmbus init` CLI subcommand (Python, click)
- Platform detection: Debian/Ubuntu/RPi (apt), macOS (brew/manual)
- Broker install: invoke `setup-mosquitto.sh` or equivalent (Debian only for v1; macOS: print manual instructions)
- Package self-check: verify swarmbus is installed at the correct version; print pip install hint if not (init is invoked after pip, so this is a sanity check)
- Systemd setup: invoke `install-systemd.sh` with sane defaults
- Host plugin install: invoke `setup-cc-plugin.sh` or `setup-openclaw-plugin.sh` if `--host-type` is given
- Doctor run: invoke `swarmbus doctor --agent-id <id>` and surface pass/fail
- Output: print verified `swarmbus start` command on success

### Out of scope (v1)

- macOS broker install (document as manual; flag clearly)
- Multi-agent init (one agent-id per invocation)
- Config file (`~/.swarmbus/config.toml`) — deferred per backlog
- Broker auth/TLS setup — deferred per backlog
- Web UI, registry setup
- `curl | bash` bootstrap script (separate artifact; init assumes pip install already done)

### Later (`curl | bash` bootstrap — v2)

A `curl -sL get.swarmbus.dev | bash` that does the full cold-start: install Python, pip install swarmbus, then call `swarmbus init`. This requires a hosted endpoint and is deferred to any public launch.

---

## Interface

```
$ swarmbus init --agent-id sparrow
$ swarmbus init --agent-id wren --host-type openclaw
$ swarmbus init --agent-id coder --host-type cc --broker tailscale
$ swarmbus init --agent-id coder --invoke "/path/to/wake.sh coder" --skip-broker
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--agent-id` | required | Agent identifier (lowercase, alphanumeric + `-_`) |
| `--host-type` | `none` | `cc` (Claude Code), `openclaw`, `none` (archive-only) |
| `--broker` | `localhost` | Broker address. Special: `tailscale` → runs setup-mosquitto.sh --tailscale |
| `--invoke` | derived from `--host-type` | Override the invoke wrapper path passed to install-systemd |
| `--inbox` | `~/sync/<agent-id>-inbox.md` | Inbox file path |
| `--skip-broker` | false | Skip broker install (broker already running) |
| `--skip-plugin` | false | Skip host plugin install |
| `--dry-run` | false | Print what would be run without executing |
| `--yes` | false | Non-interactive; accept all prompts |

### Exit codes

- `0` — all steps succeeded, doctor passed
- `1` — one or more steps failed; stderr has details
- `2` — usage error (bad flags)

---

## Execution sequence

```
1. Validate flags (agent-id format, host-type enum)
2. Detect platform
   a. Linux: check for apt → Debian-class; check /proc/cpuinfo for RPi
   b. macOS: detect brew
   c. Unknown: warn and continue where possible
3. Install/verify broker (skip if --skip-broker)
   a. Linux: subprocess scripts/setup-mosquitto.sh [--tailscale if broker=tailscale]
   b. macOS: print manual brew instructions, ask user to confirm before continuing
4. Verify swarmbus package version (warn if outdated; don't block)
5. Install systemd unit
   a. subprocess scripts/install-systemd.sh <agent-id> [--invoke ...] [--broker ...] [--inbox ...]
   b. Derive --invoke from --host-type if not explicitly set
6. Install host plugin (skip if --skip-plugin or host-type=none)
   a. cc: subprocess scripts/setup-cc-plugin.sh <agent-id>
   b. openclaw: subprocess scripts/setup-openclaw-plugin.sh <agent-id>
7. Configure outbox env var
   a. Detect shell rc file (.bashrc, .zshrc)
   b. Print export SWARMBUS_OUTBOX_<ID>=~/sync/<id>-outbox.md with instruction to source it
   c. Do NOT auto-write to shell rc (too magic)
8. Run swarmbus doctor --agent-id <agent-id>
9. Print summary:
   - Passed / failed
   - Verified start command
   - Next steps if any failures
```

---

## Output design

```
$ swarmbus init --agent-id sparrow --host-type cc

[swarmbus init] agent-id=sparrow host-type=cc broker=localhost

Step 1/6  Broker ....................... ✓ mosquitto active (127.0.0.1:1883)
Step 2/6  Package ...................... ✓ swarmbus 0.18.2 at /usr/local/bin/swarmbus
Step 3/6  Systemd unit ................. ✓ swarmbus-sparrow.service active
Step 4/6  Wake wrapper ................. ✓ /home/you/projects/swarmbus/examples/claude-code-wake.sh sparrow
Step 5/6  Host plugin .................. ✓ Claude Code skill installed at ~/.claude/skills/using-swarmbus/
Step 6/6  Doctor ....................... ✓ all green

────────────────────────────────────────────────────────
✓  sparrow is ready.

To set outbox archiving in your shell:
  export SWARMBUS_OUTBOX_SPARROW="$HOME/sync/sparrow-outbox.md"

The daemon is running. Your agent can now receive messages.
Send a test: swarmbus send --agent-id probe --to sparrow --subject hello --body "init test"
────────────────────────────────────────────────────────
```

On failure:
```
Step 3/6  Systemd unit ................. ✗ unit failed to start
  fix: check journalctl --user -u swarmbus-sparrow | tail -20
```

---

## Implementation notes

- Implement as `src/swarmbus/cli.py` — new `@main.command()` named `init`
- Subprocess calls use `subprocess.run(..., check=True)` with captured stderr piped to the user on failure
- Each step is a function `_step_N_name(ctx) -> bool` — bool is pass/fail; collect all results for summary
- Steps 1-4 are ordered with early-exit on broker failure; steps 5-6 continue even if non-critical steps fail (doctor surfaces the full picture)
- `--dry-run` prints the subprocess calls without executing
- No interactive prompts if `--yes` is set (macOS broker step prints instructions instead of waiting for confirm)

---

## Tests

- Unit: flag validation, platform detection, invoke derivation from host-type
- Integration: `--dry-run` output is parseable and matches expected subprocess commands
- Smoke: `swarmbus init --dry-run --agent-id test --host-type cc` exits 0 and prints all steps
- Not tested: actual broker install (requires sudo/apt; integration test environment handles this)

---

## Open questions

1. Should `swarmbus init` be idempotent? (Re-running on an already-configured agent.) Probably yes — systemd install-systemd.sh is already idempotent; doctor re-runs fine. Flag as safe to re-run.
2. Should macOS use brew to install mosquitto automatically? Brew install is non-interactive and safe, but brew itself may not be present. For v1: detect brew, if present offer to run `brew install mosquitto`; if absent, print manual instructions.
3. Should init write the outbox env var to the shell rc automatically? Decision: no for v1 — too magic, hard to undo, wrong file guessing. Print and instruct.
