"""Slash-Befehle: Beschreibung der Optionen, Definition für Discord und Berechtigung."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DESCRIPTION,
    CONF_EPHEMERAL,
    CONF_EVERYONE,
    CONF_GUILD_ID,
    CONF_NAME,
    CONF_OPTIONS,
    CONF_REPLY,
    CONF_ROLES,
    CONF_USERS,
    SUBENTRY_COMMAND,
)

NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")
MAX_OPTIONS = 5
MAX_CHOICES = 25

# Typen der Optionen: Schlüsselwort (deutsch und englisch) -> Typ bei Discord
OPTION_TYPES = {
    "text": 3,
    "string": 3,
    "ganzzahl": 4,
    "integer": 4,
    "zahl": 10,
    "number": 10,
    "schalter": 5,
    "boolean": 5,
    "nutzer": 6,
    "user": 6,
    "kanal": 7,
    "channel": 7,
}

# `name?:typ:Beschreibung [a|b|c]`, das Fragezeichen macht die Option freiwillig, die eckigen Klammern sind die Auswahl
_OPTION_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_-]{1,32})(?P<optional>\?)?\s*:\s*(?P<type>\w+)\s*:\s*(?P<rest>.+)$")
_CHOICES = re.compile(r"^(?P<description>.*?)\s*\[(?P<choices>[^\]]+)\]\s*$")


class InvalidCommand(ValueError):
    """Eine Angabe zum Befehl ist ungültig. Der Text ist der Fehlerschlüssel der Übersetzung."""


@dataclass(frozen=True)
class CommandConfig:
    """Ein Befehl aus einem Untereintrag."""

    subentry_id: str
    guild_id: str
    name: str
    description: str
    options: tuple[dict[str, Any], ...] = ()
    reply: str = ""
    ephemeral: bool = False
    everyone: bool = False
    users: frozenset[str] = field(default_factory=frozenset)
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def definition(self) -> dict[str, Any]:
        """Der Befehl, wie ihn Discord anlegt."""
        out: dict[str, Any] = {"name": self.name, "type": 1, "description": self.description}
        if self.options:
            out["options"] = [dict(option) for option in self.options]
        return out


def clean_ids(values: Iterable[Any] | None) -> list[str]:
    """Nutzer- und Rollen-IDs als Text, ohne Leere und Doppelte."""
    seen: dict[str, None] = {}
    for value in values or []:
        text = str(value).strip()
        if text:
            seen.setdefault(text, None)
    return list(seen)


def parse_options(text: str) -> list[dict[str, Any]]:
    """Die Optionen eines Befehls aus dem Text: eine je Zeile `name:typ:Beschreibung`.

    Hinter dem Namen macht `?` eine Option freiwillig, in eckigen Klammern am Ende der Beschreibung steht eine Auswahl
    (`modus:text:Betriebsart [auto|an|aus]`, nur bei Text und Zahlen). Freiwillige Optionen müssen hinter den
    erforderlichen stehen.
    """
    options: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _OPTION_LINE.match(line)
        if not match:
            raise InvalidCommand("invalid_options")
        name = match["name"].lower()
        kind = OPTION_TYPES.get(match["type"].lower())
        if kind is None or any(o["name"] == name for o in options):
            raise InvalidCommand("invalid_options")
        description = match["rest"].strip()
        option: dict[str, Any] = {"name": name, "type": kind, "required": not match["optional"]}
        choices = _CHOICES.match(description)
        if choices:
            description = choices["description"] or name
            values = [v.strip() for v in choices["choices"].split("|") if v.strip()]
            if kind not in (3, 4, 10) or not values or len(values) > MAX_CHOICES:
                raise InvalidCommand("invalid_options")
            try:
                converted: list[Any] = values if kind == 3 else [(int if kind == 4 else float)(v) for v in values]
            except ValueError as err:
                raise InvalidCommand("invalid_options") from err
            option["choices"] = [{"name": str(v), "value": v} for v in converted]
        option["description"] = description[:100]
        options.append(option)
    if len(options) > MAX_OPTIONS:
        raise InvalidCommand("too_many_options")
    seen_optional = False
    for option in options:
        if not option["required"]:
            seen_optional = True
        elif seen_optional:
            raise InvalidCommand("invalid_options")
    return options


def options_to_text(options: Iterable[Mapping[str, Any]]) -> str:
    """Die Umkehrung von `parse_options`, damit das Formular beim Bearbeiten den Text zeigt."""
    names = {3: "text", 4: "ganzzahl", 10: "zahl", 5: "schalter", 6: "nutzer", 7: "kanal"}
    lines = []
    for option in options:
        description = option["description"]
        if option.get("choices"):
            description = f"{description} [{'|'.join(str(c['value']) for c in option['choices'])}]"
        optional = "" if option.get("required", True) else "?"
        lines.append(f"{option['name']}{optional}:{names[option['type']]}:{description}")
    return "\n".join(lines)


def validate_name(name: str) -> str:
    """Name des Befehls: klein geschrieben, Buchstaben, Ziffern, `-` und `_`, bis 32 Zeichen."""
    cleaned = name.strip().lstrip("/").lower()
    if not NAME_PATTERN.match(cleaned):
        raise InvalidCommand("invalid_name")
    return cleaned


def validate_description(description: str) -> str:
    cleaned = description.strip()
    if not 1 <= len(cleaned) <= 100:
        raise InvalidCommand("invalid_description")
    return cleaned


def command_from_data(subentry_id: str, data: Mapping[str, Any]) -> CommandConfig:
    return CommandConfig(
        subentry_id=subentry_id,
        guild_id=str(data[CONF_GUILD_ID]),
        name=data[CONF_NAME],
        description=data[CONF_DESCRIPTION],
        options=tuple(data.get(CONF_OPTIONS) or ()),
        reply=str(data.get(CONF_REPLY) or ""),
        ephemeral=bool(data.get(CONF_EPHEMERAL)),
        everyone=bool(data.get(CONF_EVERYONE)),
        users=frozenset(clean_ids(data.get(CONF_USERS))),
        roles=frozenset(clean_ids(data.get(CONF_ROLES))),
    )


def commands_of(entry: ConfigEntry) -> dict[str, CommandConfig]:
    """Alle Befehle eines Eintrags, nach ID des Untereintrags."""
    return {
        sub.subentry_id: command_from_data(sub.subentry_id, sub.data)
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_COMMAND
    }
