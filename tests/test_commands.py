"""Befehle: Optionen aus Text, Namen und Definition für Discord."""

from __future__ import annotations

import pytest

from custom_components.discord_hub.commands import (
    InvalidCommand,
    command_from_data,
    options_to_text,
    parse_options,
    validate_description,
    validate_name,
)


def test_parse_options():
    options = parse_options(
        "temperatur:zahl:Zieltemperatur\n"
        "raum?:text:Welcher Raum [bett|schaukel|bad]\n"
        "an?:schalter:Einschalten\n"
        "wer?:nutzer:Für wen\n"
        "wo?:kanal:In welchem Kanal\n"
    )
    assert options[0] == {"name": "temperatur", "type": 10, "required": True, "description": "Zieltemperatur"}
    assert options[1]["required"] is False
    assert options[1]["description"] == "Welcher Raum"
    assert options[1]["choices"] == [
        {"name": "bett", "value": "bett"},
        {"name": "schaukel", "value": "schaukel"},
        {"name": "bad", "value": "bad"},
    ]
    assert [o["type"] for o in options] == [10, 3, 5, 6, 7]


def test_parse_options_accepts_english_type_names_and_numeric_choices():
    options = parse_options("count:integer:Anzahl [1|2|3]")
    assert options[0]["type"] == 4
    assert options[0]["choices"] == [{"name": "1", "value": 1}, {"name": "2", "value": 2}, {"name": "3", "value": 3}]


def test_empty_options():
    assert parse_options("") == []
    assert parse_options("  \n\n ") == []


@pytest.mark.parametrize(
    "text",
    [
        "keine-doppelpunkte",
        "a:unbekannt:Typ gibt es nicht",
        "a:text:Eins\na:text:Doppelt",
        "a?:text:Freiwillig zuerst\nb:text:Danach erforderlich",
        "a:schalter:Auswahl [ja|nein]",
        "a:ganzzahl:Keine Zahl [eins|zwei]",
    ],
)
def test_invalid_options(text):
    with pytest.raises(InvalidCommand) as err:
        parse_options(text)
    assert str(err.value) == "invalid_options"


def test_too_many_options():
    with pytest.raises(InvalidCommand) as err:
        parse_options("\n".join(f"o{i}:text:Option" for i in range(6)))
    assert str(err.value) == "too_many_options"


def test_options_roundtrip():
    text = "temperatur:zahl:Zieltemperatur\nraum?:text:Welcher Raum [bett|bad]"
    assert options_to_text(parse_options(text)) == text


def test_names_and_descriptions():
    assert validate_name("  /Status ") == "status"
    assert validate_name("licht_an-2") == "licht_an-2"
    for bad in ("", "mit leerzeichen", "ä", "x" * 33):
        with pytest.raises(InvalidCommand):
            validate_name(bad)
    assert validate_description(" Zeigt den Status ") == "Zeigt den Status"
    for bad in ("", "x" * 101):
        with pytest.raises(InvalidCommand):
            validate_description(bad)


def test_definition_for_discord():
    command = command_from_data(
        "sub1",
        {
            "guild_id": 1,
            "name": "status",
            "description": "Zeigt den Status",
            "options": parse_options("raum:text:Raum"),
            "users": ["555", " 555 ", ""],
            "roles": [777],
        },
    )
    assert command.guild_id == "1"
    assert command.users == frozenset({"555"})
    assert command.roles == frozenset({"777"})
    assert command.definition == {
        "name": "status",
        "type": 1,
        "description": "Zeigt den Status",
        "options": [{"name": "raum", "type": 3, "required": True, "description": "Raum"}],
    }
