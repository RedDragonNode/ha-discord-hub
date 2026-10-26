"""Beide READMEs nennen alle Dienste, und ihre Gliederung bleibt gleich."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = list(yaml.safe_load((ROOT / "custom_components" / "discord_hub" / "services.yaml").read_text("utf-8")))


@pytest.mark.parametrize("name", ["README.md", "README.en.md"])
def test_every_service_is_in_the_readme(name: str) -> None:
    text = (ROOT / name).read_text(encoding="utf-8")
    for service in SERVICES:
        assert f"`{service}`" in text or f"`discord_hub.{service}`" in text, f"{name}: {service}"


def test_both_readmes_have_the_same_structure() -> None:
    def headings(name: str) -> list[str]:
        return re.findall(r"^(#{1,3}) ", (ROOT / name).read_text(encoding="utf-8"), flags=re.MULTILINE)

    assert headings("README.md") == headings("README.en.md")


def test_the_readme_links_to_the_other_language() -> None:
    assert "README.en.md" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "README.md" in (ROOT / "README.en.md").read_text(encoding="utf-8")
