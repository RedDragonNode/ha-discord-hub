"""Übersetzungen: gleiche Schlüssel in beiden Sprachen, nur bekannte Platzhalter, alle Dienste beschrieben."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "discord_hub"
TRANSLATIONS = COMPONENT / "translations"
# Das Frontend liest jede geschweifte Klammer als Platzhalter und meldet einen Fehler, wenn der Wert fehlt.
ALLOWED_PLACEHOLDERS = {"bot", "details", "guild", "known", "length", "limit", "name", "path", "spec", "uri", "url"}


def _flatten(node: object, prefix: str = "") -> dict[str, str]:
    if isinstance(node, dict):
        out: dict[str, str] = {}
        for key, value in node.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else key))
        return out
    return {prefix: str(node)}


@pytest.fixture(scope="module")
def texts() -> dict[str, dict[str, str]]:
    return {
        lang: _flatten(json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))) for lang in ("de", "en")
    }


def test_both_languages_have_the_same_keys(texts: dict[str, dict[str, str]]) -> None:
    assert set(texts["de"]) == set(texts["en"])


@pytest.mark.parametrize("lang", ["de", "en"])
def test_only_known_placeholders(texts: dict[str, dict[str, str]], lang: str) -> None:
    for key, text in texts[lang].items():
        assert set(re.findall(r"\{([^{}]*)\}", text)) <= ALLOWED_PLACEHOLDERS, f"{lang}: {key}"
        assert text.count("{") == text.count("}"), f"{lang}: {key}"


def test_placeholders_match_between_languages(texts: dict[str, dict[str, str]]) -> None:
    for key, de_text in texts["de"].items():
        assert set(re.findall(r"\{(\w+)\}", de_text)) == set(re.findall(r"\{(\w+)\}", texts["en"][key])), key


@pytest.mark.parametrize("lang", ["de", "en"])
def test_no_text_is_empty(texts: dict[str, dict[str, str]], lang: str) -> None:
    assert all(text.strip() for text in texts[lang].values())


@pytest.mark.parametrize("lang", ["de", "en"])
def test_every_service_and_field_is_described(texts: dict[str, dict[str, str]], lang: str) -> None:
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    for name, definition in services.items():
        assert f"services.{name}.name" in texts[lang], name
        assert f"services.{name}.description" in texts[lang], name
        for field in (definition or {}).get("fields", {}):
            assert f"services.{name}.fields.{field}.name" in texts[lang], f"{name}.{field}"
            assert f"services.{name}.fields.{field}.description" in texts[lang], f"{name}.{field}"


def test_every_error_key_used_in_the_code_has_a_text(texts: dict[str, dict[str, str]]) -> None:
    used: set[str] = set()
    for source in COMPONENT.glob("*.py"):
        code = source.read_text(encoding="utf-8")
        used |= set(re.findall(r'translation_key="(\w+)"', code))
        used |= set(re.findall(r'_(?:invalid|error)\(\s*"(\w+)"', code))
        used |= set(re.findall(r'_ha_error\(\s*"(\w+)"', code))
    assert used, "keine Schlüssel gefunden, die Suche ist kaputt"
    for key in used:
        assert f"exceptions.{key}.message" in texts["en"] or f"issues.{key}.title" in texts["en"], key


@pytest.mark.parametrize("lang", ["de", "en"])
def test_no_urls_in_texts(texts: dict[str, dict[str, str]], lang: str) -> None:
    """Hassfest lehnt Adressen in Übersetzungen ab."""
    for key, text in texts[lang].items():
        assert "http" not in text, f"{lang}: {key}"


def test_every_entity_is_named_in_both_languages(texts: dict[str, dict[str, str]]) -> None:
    """Jeder `translation_key` einer Entity hat einen Namen, die dynamischen der Server-Sensoren eingeschlossen."""
    used: dict[str, set[str]] = {}
    for source in ("sensor", "binary_sensor"):
        code = (COMPONENT / f"{source}.py").read_text(encoding="utf-8")
        used[source] = set(re.findall(r'_attr_translation_key = "(\w+)"', code))
    used["sensor"] |= {"server_members", "server_online"}  # sensor.py baut sie aus f"server_{key}"
    assert used["sensor"] >= {"voice_users", "member_status", "member_activity"}
    for lang, entries in texts.items():
        for domain, keys in used.items():
            for key in keys:
                assert f"entity.{domain}.{key}.name" in entries, f"{lang}: {domain}.{key}"
        for state in ("online", "idle", "dnd", "offline"):
            assert f"entity.sensor.member_status.state.{state}" in entries, f"{lang}: {state}"
