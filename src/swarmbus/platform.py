"""Platform detection utilities for swarmbus init.

All functions are pure (no side effects) or clearly documented when they
shell out. Kept separate from cli.py so they can be unit-tested with simple
mocks without importing click or the full CLI machinery.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path


def detect_platform() -> str:
    """Return a normalised platform string.

    Returns
    -------
    "debian"  — Linux with apt-get present (Debian / Ubuntu / RPi OS)
    "macos"   — macOS (Darwin)
    "unknown" — anything else
    """
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        if shutil.which("apt-get") or shutil.which("apt"):
            return "debian"
    return "unknown"


def detect_arch() -> str:
    """Return a normalised architecture string.

    Checks /proc/cpuinfo for Raspberry Pi before falling back to
    platform.machine() so RPi ARM boards are distinguished from generic ARM.

    Returns
    -------
    "rpi"     — Raspberry Pi (any model)
    "x86"     — x86_64 / AMD64
    "arm"     — 32- or 64-bit ARM (non-RPi)
    "unknown" — anything else
    """
    # RPi detection: /proc/cpuinfo contains "Raspberry Pi" on all RPi models.
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        try:
            content = cpuinfo.read_text(errors="replace")
            if "Raspberry Pi" in content:
                return "rpi"
        except OSError:
            pass

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "i686", "i386"):
        return "x86"
    if machine in ("aarch64", "arm64", "armv7l", "armv6l", "armhf"):
        return "arm"
    return "unknown"


def find_repo_root() -> str | None:
    """Return the swarmbus repo root (the directory containing ``scripts/``).

    Walks up the directory tree starting from this module's location. Works
    for editable installs (``pip install -e .``) where the source tree is on
    disk. Returns ``None`` for regular PyPI installs where ``scripts/`` is not
    present in site-packages.
    """
    try:
        start = Path(__file__).resolve().parent
    except Exception:
        return None

    # Walk up to filesystem root looking for a directory that contains scripts/
    candidate = start
    for _ in range(10):  # cap the search — don't walk forever
        if (candidate / "scripts").is_dir() and (candidate / "src").is_dir():
            return str(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return None


def resolve_broker_addr(broker: str) -> str:
    """Resolve the ``--broker`` value to an actual hostname or IP.

    For most values this is a no-op (returns the string unchanged).
    The special value ``"tailscale"`` triggers a ``tailscale ip -4`` lookup
    so the resolved Tailscale IPv4 address is used instead of the literal
    string "tailscale" (which would cause the daemon to fail DNS resolution).

    Parameters
    ----------
    broker:
        Value passed to ``--broker``. Typically "localhost", an IP address,
        or the special sentinel "tailscale".

    Returns
    -------
    The broker address to use in systemd unit and connection strings.

    Raises
    ------
    RuntimeError
        If broker == "tailscale" but the ``tailscale`` CLI is not on PATH,
        or if it returns no IPv4 address.
    """
    if broker != "tailscale":
        return broker

    if not shutil.which("tailscale"):
        raise RuntimeError(
            "tailscale CLI not found on PATH. "
            "Install tailscale (https://tailscale.com/download) and run 'tailscale up', "
            "then retry."
        )

    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("tailscale ip -4 timed out after 5s")

    if result.returncode != 0:
        raise RuntimeError(
            f"tailscale ip -4 failed (exit {result.returncode}): {result.stderr.strip()}"
        )

    ip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not ip:
        raise RuntimeError(
            "tailscale ip -4 returned no IPv4 address. "
            "Run 'tailscale up' and ensure the node has a Tailscale IP."
        )
    return ip
