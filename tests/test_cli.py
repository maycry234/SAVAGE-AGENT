"""Test CLI parser registration and help output."""

import pytest

from agent.cli import build_parser


EXPECTED_COMMANDS = [
    "generate-key",
    "encrypt-wallet",
    "health",
    "positions",
    "trades",
    "paper-balance",
    "reset-paper",
    "force-close",
    "tail-learning",
]


def test_build_parser_returns_parser():
    parser = build_parser()
    assert parser is not None
    assert parser.prog == "python -m agent.cli"


def test_all_commands_registered():
    parser = build_parser()
    choices = set()
    for action in parser._subparsers._actions:
        if hasattr(action, "choices") and action.choices:
            choices.update(action.choices.keys())
    for cmd in EXPECTED_COMMANDS:
        assert cmd in choices, f"command '{cmd}' not registered"


def test_help_does_not_crash(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "SAVAGE AGENT" in captured.out


@pytest.mark.parametrize("cmd", EXPECTED_COMMANDS)
def test_subcommand_help(cmd, capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([cmd, "--help"])
    assert exc_info.value.code == 0
