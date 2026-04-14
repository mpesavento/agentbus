import json
from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from agentbus.cli import main


def test_send_invokes_bus(tmp_path):
    runner = CliRunner()
    with patch("agentbus.cli.AgentBus") as MockBus:
        instance = MockBus.return_value
        instance.send = AsyncMock()
        result = runner.invoke(main, [
            "send",
            "--agent-id", "sparrow",
            "--to", "wren",
            "--subject", "hello",
            "--body", "world",
        ])
    assert result.exit_code == 0, result.output
    instance.send.assert_called_once()
    call_kwargs = instance.send.call_args.kwargs
    assert call_kwargs["to"] == "wren"
    assert call_kwargs["subject"] == "hello"
    assert call_kwargs["body"] == "world"


def test_send_missing_required_options():
    runner = CliRunner()
    result = runner.invoke(main, ["send", "--agent-id", "sparrow"])
    assert result.exit_code != 0
    assert "Missing option" in result.output


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "agentbus" in result.output


def test_send_help():
    runner = CliRunner()
    result = runner.invoke(main, ["send", "--help"])
    assert result.exit_code == 0
    assert "--to" in result.output
    assert "--subject" in result.output
    assert "--body" in result.output
