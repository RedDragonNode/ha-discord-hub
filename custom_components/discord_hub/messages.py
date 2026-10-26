"""Nachrichten bauen: Text, Embeds und erlaubte Erwähnungen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, MAX_CONTENT, MAX_EMBEDS

_EMBED_KEYS = ("title", "description", "url", "color", "timestamp", "author", "footer", "thumbnail", "image", "fields")

# Embeds: erlaubte Schlüssel mit freundlichen Kurzformen (Text statt Objekt), `normalize_embed` macht das Objekt daraus
EMBED_SCHEMA = vol.Schema({vol.Optional(key): object for key in _EMBED_KEYS})


def _color(value: Any) -> int:
    """Farbe als Zahl (auch als Text aus einer Vorlage), #RRGGBB, 0xRRGGBB, RRGGBB mit Buchstaben oder [r, g, b]."""
    if isinstance(value, bool):
        raise ValueError("color")
    if isinstance(value, int):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 3:
        red, green, blue = (int(v) for v in value)
        return (red << 16) | (green << 8) | blue
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("#"):
            return int(text[1:], 16)
        if text.lower().startswith("0x"):
            return int(text[2:], 16)
        if text.isdigit():
            return int(text)  # Vorlagen liefern Zahlen als Text, 3066993 ist die Dezimalzahl
        return int(text, 16)
    raise ValueError("color")


def _named(value: Any, key: str, extra: tuple[str, ...]) -> dict[str, Any]:
    """Text oder Objekt (`name` bzw. `text` plus Zusatzfelder)."""
    if isinstance(value, str):
        return {key: value}
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k in (key, *extra) and v not in (None, "")}
    raise ValueError(key)


def normalize_embed(embed: dict[str, Any]) -> dict[str, Any]:
    """Ein Embed aus der Dienst-Eingabe in das Objekt von Discord umwandeln.

    Erlaubt sind Kurzformen: `color` als #RRGGBB, `author` und `footer` als Text, `thumbnail` und `image` als Adresse,
    `timestamp: true` für jetzt.
    """
    try:
        out: dict[str, Any] = {}
        for key in ("title", "description", "url"):
            if embed.get(key) not in (None, ""):
                out[key] = str(embed[key])
        if embed.get("color") not in (None, ""):
            out["color"] = _color(embed["color"])
        timestamp = embed.get("timestamp")
        if timestamp is True:
            out["timestamp"] = datetime.now(UTC).isoformat()
        elif isinstance(timestamp, datetime):
            out["timestamp"] = timestamp.isoformat()
        elif timestamp not in (None, False, ""):
            out["timestamp"] = str(timestamp)
        if embed.get("author"):
            out["author"] = _named(embed["author"], "name", ("url", "icon_url"))
        if embed.get("footer"):
            out["footer"] = _named(embed["footer"], "text", ("icon_url",))
        for key in ("thumbnail", "image"):
            if embed.get(key):
                out[key] = _named(embed[key], "url", ())
        if embed.get("fields"):
            out["fields"] = [
                {
                    "name": str(field["name"]),
                    "value": str(field["value"]),
                    "inline": bool(field.get("inline", True)),
                }
                for field in embed["fields"]
            ]
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_embed", translation_placeholders={"details": str(err)}
        ) from err
    return out


BUTTON_KEYS = ("label", "custom_id", "style", "url", "emoji", "disabled")
BUTTON_SCHEMA = vol.Schema({vol.Optional(key): object for key in BUTTON_KEYS})
BUTTON_STYLES = {"primary": 1, "secondary": 2, "success": 3, "danger": 4, "link": 5}
BUTTONS_PER_ROW = 5
MAX_BUTTONS = 25


def build_components(buttons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schaltflächen als Zeilen mit je bis zu fünf Buttons. Eine leere Liste entfernt alle Schaltflächen."""
    if len(buttons) > MAX_BUTTONS:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="too_many_buttons",
            translation_placeholders={"limit": str(MAX_BUTTONS)},
        )
    built: list[dict[str, Any]] = []
    try:
        for button in buttons:
            style = button.get("style", "primary")
            kind = style if isinstance(style, int) else BUTTON_STYLES[str(style).lower()]
            item: dict[str, Any] = {"type": 2, "style": kind}
            if button.get("label"):
                item["label"] = str(button["label"])[:80]
            if emoji := button.get("emoji"):
                item["emoji"] = {"name": emoji} if isinstance(emoji, str) else dict(emoji)
            if not item.get("label") and not item.get("emoji"):
                raise ValueError("label")
            if kind == BUTTON_STYLES["link"]:
                if not button.get("url"):
                    raise ValueError("url")
                item["url"] = str(button["url"])
            else:
                custom_id = str(button.get("custom_id") or "")
                if not custom_id or len(custom_id) > 100:
                    raise ValueError("custom_id")
                item["custom_id"] = custom_id
            if button.get("disabled"):
                item["disabled"] = True
            built.append(item)
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="invalid_button", translation_placeholders={"details": str(err)}
        ) from err
    return [
        {"type": 1, "components": built[start : start + BUTTONS_PER_ROW]}
        for start in range(0, len(built), BUTTONS_PER_ROW)
    ]


def build_payload(
    message: str | None,
    embeds: list[dict[str, Any]] | None,
    *,
    reply_to: str | None = None,
    allow_everyone: bool = False,
    buttons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Der JSON-Teil einer Nachricht. Erwähnungen von Nutzern und Rollen sind erlaubt, @everyone nur auf Wunsch."""
    payload: dict[str, Any] = {}
    if message:
        if len(message) > MAX_CONTENT:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="message_too_long",
                translation_placeholders={"limit": str(MAX_CONTENT), "length": str(len(message))},
            )
        payload["content"] = message
    if embeds:
        if len(embeds) > MAX_EMBEDS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="too_many_embeds",
                translation_placeholders={"limit": str(MAX_EMBEDS)},
            )
        payload["embeds"] = [normalize_embed(embed) for embed in embeds]
    payload["allowed_mentions"] = {"parse": ["users", "roles", *(["everyone"] if allow_everyone else [])]}
    if buttons is not None:
        payload["components"] = build_components(buttons)
    if reply_to:
        payload["message_reference"] = {"message_id": str(reply_to), "fail_if_not_exists": False}
    return payload
