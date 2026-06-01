"""Smoke test: CLI dispatch table is intact after module split.

Every command in COMMANDS must be callable. The total count must
match exactly — bump it when commands are added or removed.
Data-driven — no hardcoded command list to maintain.
"""

from rhizome_alkahest.cli import COMMANDS, main


def test_all_commands_are_callable():
    for name, handler in COMMANDS.items():
        assert callable(handler), f"COMMANDS[{name!r}] is not callable: {handler!r}"


def test_command_count_is_tracked():
    """Bump this number when commands are added or removed."""
    assert len(COMMANDS) == 36, (
        f"Command count changed: expected 36, got {len(COMMANDS)}. "
        f"Update this test to match."
    )


def test_main_is_callable():
    assert callable(main)
