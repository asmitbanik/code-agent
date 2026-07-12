"""Classify complexity tiers."""

from agent_auto.classify import analyze_task, classify_task, heuristic_plan


def test_readme_task_is_docs() -> None:
    c = classify_task(
        "Rewrite the README.md to be more interesting and user-friendly. Only README.md."
    )
    assert c.kind == "docs"
    assert c.skip_browser is True
    plan = heuristic_plan("rewrite readme", c)
    assert plan.subtasks


def test_auth_task_is_complex() -> None:
    req = analyze_task("Add JWT refresh tokens and a password reset migration")
    assert req.complexity == "complex"
    assert req.needs_auth is True


def test_typo_is_simple() -> None:
    req = analyze_task("Fix a typo in the config comment")
    assert req.complexity == "simple"


def test_feature_is_standard() -> None:
    req = analyze_task("Implement a new API endpoint for listing products")
    assert req.complexity == "standard"
