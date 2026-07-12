"""Branch naming helpers."""

from agent_auto.deliver.ship import create_branch_name, slugify


def test_slugify() -> None:
    assert slugify("Add a password strength indicator!") == "add-a-password-strength-indicator"


def test_branch_name() -> None:
    name = create_branch_name("Fix login bug", "abc1234")
    assert name.startswith("agent/")
    assert name.endswith("-abc1234")
