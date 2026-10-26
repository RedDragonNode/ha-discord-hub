"""Nachrichten und Embeds bauen."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.exceptions import ServiceValidationError

from custom_components.discord_hub.messages import EMBED_SCHEMA, build_payload, normalize_embed


def test_embed_short_forms():
    embed = normalize_embed(
        {
            "title": "Bewegung",
            "description": "Um 14:03",
            "color": "#2ECC71",
            "author": "Fuchs",
            "footer": {"text": "Haus", "icon_url": "https://x/y.png"},
            "thumbnail": "https://x/t.png",
            "image": {"url": "https://x/i.png"},
            "fields": [{"name": "Temperatur", "value": 21.5}, {"name": "Luft", "value": "40 %", "inline": False}],
            "timestamp": True,
        }
    )
    assert embed["color"] == 0x2ECC71
    assert embed["author"] == {"name": "Fuchs"}
    assert embed["footer"] == {"text": "Haus", "icon_url": "https://x/y.png"}
    assert embed["thumbnail"] == {"url": "https://x/t.png"}
    assert embed["image"] == {"url": "https://x/i.png"}
    assert embed["fields"] == [
        {"name": "Temperatur", "value": "21.5", "inline": True},
        {"name": "Luft", "value": "40 %", "inline": False},
    ]
    assert "T" in embed["timestamp"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (3066993, 3066993),
        ("3066993", 3066993),  # aus einer Vorlage kommt die Zahl als Text
        ("#2ECC71", 0x2ECC71),
        ("2ECC71", 0x2ECC71),
        ("0x2ECC71", 0x2ECC71),
        ([255, 0, 16], 0xFF0010),
    ],
)
def test_embed_colors(value, expected):
    assert normalize_embed({"color": value})["color"] == expected


@pytest.mark.parametrize("embed", [{"color": "rot"}, {"fields": [{"name": "nur Name"}]}, {"color": True}])
def test_invalid_embed_is_a_clear_error(embed):
    with pytest.raises(ServiceValidationError) as err:
        normalize_embed(embed)
    assert err.value.translation_key == "invalid_embed"


def test_embed_schema_rejects_unknown_keys():
    with pytest.raises(vol.Invalid):
        EMBED_SCHEMA({"titel": "falsch"})


def test_payload_mentions_users_and_roles_but_not_everyone():
    assert build_payload("hi", None)["allowed_mentions"] == {"parse": ["users", "roles"]}
    assert build_payload("hi", None, allow_everyone=True)["allowed_mentions"]["parse"] == ["users", "roles", "everyone"]


def test_payload_reply():
    payload = build_payload("hi", None, reply_to="55")
    assert payload["message_reference"] == {"message_id": "55", "fail_if_not_exists": False}


def test_payload_limits():
    with pytest.raises(ServiceValidationError) as err:
        build_payload("x" * 2001, None)
    assert err.value.translation_key == "message_too_long"
    with pytest.raises(ServiceValidationError) as err:
        build_payload("x", [{"title": "a"}] * 11)
    assert err.value.translation_key == "too_many_embeds"


# ---------------------------------------------------------------- Schaltflächen
def test_buttons_become_rows_of_five():
    from custom_components.discord_hub.messages import build_components

    rows = build_components([{"label": f"B{i}", "custom_id": f"b{i}"} for i in range(7)])
    assert [len(row["components"]) for row in rows] == [5, 2]
    assert rows[0]["type"] == 1
    assert rows[0]["components"][0] == {"type": 2, "style": 1, "label": "B0", "custom_id": "b0"}


def test_button_styles_emoji_link_and_disabled():
    from custom_components.discord_hub.messages import build_components

    [row] = build_components(
        [
            {"label": "Ja", "custom_id": "ja", "style": "success"},
            {"label": "Nein", "custom_id": "nein", "style": "DANGER", "disabled": True},
            {"emoji": "✅", "custom_id": "ok", "style": 2},
            {"label": "Mehr", "style": "link", "url": "https://example.com/x"},
        ]
    )
    yes, no, ok, link = row["components"]
    assert yes["style"] == 3
    assert no["style"] == 4
    assert no["disabled"] is True
    assert ok["emoji"] == {"name": "✅"}
    assert link["style"] == 5
    assert link["url"] == "https://example.com/x"
    assert "custom_id" not in link


def test_no_buttons_removes_them():
    from custom_components.discord_hub.messages import build_components

    assert build_components([]) == []
    assert build_payload("x", None, buttons=[])["components"] == []
    assert "components" not in build_payload("x", None)


@pytest.mark.parametrize(
    "button",
    [
        {"custom_id": "a"},  # weder Text noch Emoji
        {"label": "A"},  # keine custom_id
        {"label": "A", "custom_id": "x" * 101},
        {"label": "A", "style": "link"},  # keine Adresse
        {"label": "A", "custom_id": "a", "style": "bunt"},
    ],
)
def test_invalid_buttons(button):
    from custom_components.discord_hub.messages import build_components

    with pytest.raises(ServiceValidationError) as err:
        build_components([button])
    assert err.value.translation_key == "invalid_button"


def test_too_many_buttons():
    from custom_components.discord_hub.messages import build_components

    with pytest.raises(ServiceValidationError) as err:
        build_components([{"label": "A", "custom_id": f"a{i}"} for i in range(26)])
    assert err.value.translation_key == "too_many_buttons"
