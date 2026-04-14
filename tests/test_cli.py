from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from agentbus.cli import main


def test_send_inline_body(tmp_path):
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


def test_send_body_file(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# Report\nsome content")
    runner = CliRunner()
    with patch("agentbus.cli.AgentBus") as MockBus:
        instance = MockBus.return_value
        instance.send = AsyncMock()
        result = runner.invoke(main, [
            "send",
            "--agent-id", "sparrow",
            "--to", "wren",
            "--subject", "report",
            "--body-file", str(report),
        ])
    assert result.exit_code == 0, result.output
    call_kwargs = instance.send.call_args.kwargs
    assert call_kwargs["body"] == "# Report\nsome content"


def test_send_body_file_stdin():
    runner = CliRunner()
    with patch("agentbus.cli.AgentBus") as MockBus:
        instance = MockBus.return_value
        instance.send = AsyncMock()
        result = runner.invoke(main, [
            "send",
            "--agent-id", "sparrow",
            "--to", "wren",
            "--subject", "piped",
            "--body-file", "-",
        ], input="piped content")
    assert result.exit_code == 0, result.output
    call_kwargs = instance.send.call_args.kwargs
    assert call_kwargs["body"] == "piped content"


def test_send_body_and_body_file_mutually_exclusive(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("content")
    runner = CliRunner()
    result = runner.invoke(main, [
        "send",
        "--agent-id", "sparrow",
        "--to", "wren",
        "--subject", "hello",
        "--body", "inline",
        "--body-file", str(report),
    ])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_send_body_required():
    runner = CliRunner()
    result = runner.invoke(main, [
        "send",
        "--agent-id", "sparrow",
        "--to", "wren",
        "--subject", "hello",
    ])
    assert result.exit_code != 0
    assert "required" in result.output


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
    assert "--body-file" in result.output
