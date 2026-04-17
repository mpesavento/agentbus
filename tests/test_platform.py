"""Tests for swarmbus.platform — detect_platform, detect_arch,
find_repo_root, resolve_broker_addr."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from swarmbus.platform import (
    detect_arch,
    detect_platform,
    find_repo_root,
    resolve_broker_addr,
)


# ---------------------------------------------------------------------------
# detect_platform
# ---------------------------------------------------------------------------

class TestDetectPlatform:
    def test_debian(self):
        with patch("platform.system", return_value="Linux"), \
             patch("shutil.which", side_effect=lambda x: "/usr/bin/apt" if x == "apt" else None):
            assert detect_platform() == "debian"

    def test_debian_via_apt_get(self):
        with patch("platform.system", return_value="Linux"), \
             patch("shutil.which", side_effect=lambda x: "/usr/bin/apt-get" if x == "apt-get" else None):
            assert detect_platform() == "debian"

    def test_macos(self):
        with patch("platform.system", return_value="Darwin"):
            assert detect_platform() == "macos"

    def test_linux_no_apt(self):
        with patch("platform.system", return_value="Linux"), \
             patch("shutil.which", return_value=None):
            assert detect_platform() == "unknown"

    def test_unknown_os(self):
        with patch("platform.system", return_value="Windows"):
            assert detect_platform() == "unknown"


# ---------------------------------------------------------------------------
# detect_arch
# ---------------------------------------------------------------------------

class TestDetectArch:
    def test_rpi(self, tmp_path):
        cpuinfo = tmp_path / "cpuinfo"
        cpuinfo.write_text("Hardware\t: BCM2835\nRevision\t: d03115\nModel\t: Raspberry Pi 4 Model B Rev 1.5\n")
        with patch("swarmbus.platform.Path") as MockPath:
            # Make /proc/cpuinfo point to our temp file
            def path_side_effect(p):
                if str(p) == "/proc/cpuinfo":
                    return cpuinfo
                return Path(p)
            MockPath.side_effect = path_side_effect
            assert detect_arch() == "rpi"

    def test_x86_64(self, tmp_path):
        # No /proc/cpuinfo or no RPi string
        fake_cpuinfo = tmp_path / "cpuinfo"
        fake_cpuinfo.write_text("vendor_id: GenuineIntel\n")
        with patch("swarmbus.platform.Path") as MockPath:
            def path_side_effect(p):
                if str(p) == "/proc/cpuinfo":
                    return fake_cpuinfo
                return Path(p)
            MockPath.side_effect = path_side_effect
            with patch("platform.machine", return_value="x86_64"):
                assert detect_arch() == "x86"

    def test_aarch64(self, tmp_path):
        fake_cpuinfo = tmp_path / "cpuinfo"
        fake_cpuinfo.write_text("Hardware\t: Qualcomm\n")
        with patch("swarmbus.platform.Path") as MockPath:
            def path_side_effect(p):
                if str(p) == "/proc/cpuinfo":
                    return fake_cpuinfo
                return Path(p)
            MockPath.side_effect = path_side_effect
            with patch("platform.machine", return_value="aarch64"):
                assert detect_arch() == "arm"

    def test_no_cpuinfo_unknown_machine(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with patch("swarmbus.platform.Path") as MockPath:
            def path_side_effect(p):
                if str(p) == "/proc/cpuinfo":
                    return missing
                return Path(p)
            MockPath.side_effect = path_side_effect
            with patch("platform.machine", return_value="mips"):
                assert detect_arch() == "unknown"


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_found(self, tmp_path):
        # Create fake repo structure: tmp_path/src/swarmbus/platform.py and tmp_path/scripts/
        src = tmp_path / "src" / "swarmbus"
        src.mkdir(parents=True)
        (src / "platform.py").write_text("")
        (tmp_path / "scripts").mkdir()
        (tmp_path / "src").mkdir(exist_ok=True)

        with patch("swarmbus.platform.__file__", str(src / "platform.py")):
            result = find_repo_root()
        assert result == str(tmp_path)

    def test_not_found(self, tmp_path):
        # No scripts/ anywhere in the tree
        src = tmp_path / "src" / "swarmbus"
        src.mkdir(parents=True)
        (src / "platform.py").write_text("")
        # Explicitly NO scripts/ directory

        with patch("swarmbus.platform.__file__", str(src / "platform.py")):
            result = find_repo_root()
        assert result is None


# ---------------------------------------------------------------------------
# resolve_broker_addr
# ---------------------------------------------------------------------------

class TestResolveBrokerAddr:
    def test_passthrough(self):
        assert resolve_broker_addr("localhost") == "localhost"
        assert resolve_broker_addr("192.168.1.10") == "192.168.1.10"
        assert resolve_broker_addr("mqtt.example.com") == "mqtt.example.com"

    def test_tailscale_resolves_ip(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "100.64.0.1\n"
        with patch("shutil.which", return_value="/usr/bin/tailscale"), \
             patch("subprocess.run", return_value=mock_result):
            assert resolve_broker_addr("tailscale") == "100.64.0.1"

    def test_tailscale_not_found(self):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="tailscale CLI not found"):
                resolve_broker_addr("tailscale")

    def test_tailscale_cli_fails(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "not connected"
        with patch("shutil.which", return_value="/usr/bin/tailscale"), \
             patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="tailscale ip -4 failed"):
                resolve_broker_addr("tailscale")

    def test_tailscale_empty_output(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("shutil.which", return_value="/usr/bin/tailscale"), \
             patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="no IPv4 address"):
                resolve_broker_addr("tailscale")
