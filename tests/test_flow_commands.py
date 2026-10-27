"""Optionen eines Bots und der Dialog für Slash-Befehle."""

from __future__ import annotations

import re

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.discord_hub.commands import parse_options
from custom_components.discord_hub.const import CONF_GUILD_ID

from .conftest import API, BOT_ID, bot_entry, command_subentry, setup_entry, webhook_entry


def _guilds(*names: str):
    return [{"id": str(i + 1), "name": name} for i, name in enumerate(names)]


# ---------------------------------------------------------------- Optionen
async def test_options_of_a_bot(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    assert entry.supports_options
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "listen": True,
            "receive_messages": False,
            "track_presence": True,
            "allowed_users": ["555", " 555 ", "666", ""],
            "allowed_roles": ["7"],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        "listen": True,
        "receive_messages": False,
        "track_presence": True,
        "allowed_users": ["555", "666"],
        "allowed_roles": ["7"],
    }


async def test_options_with_bad_ids(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"listen": True, "allowed_users": ["stefan"]}
    )
    assert result["errors"] == {"base": "invalid_ids"}


async def test_a_webhook_has_no_options(hass, discord):
    entry = await setup_entry(hass, webhook_entry())
    assert not entry.supports_options


# ---------------------------------------------------------------- Befehle
COMMAND = {
    "name": "status",
    "description": "Zeigt den Status",
    "options": "raum?:text:Welcher Raum [bett|bad]",
    "reply": "",
    "ephemeral": True,
    "everyone": False,
    "users": ["555"],
    "roles": [],
}


def _mock_command_sync(discord):
    """Nach dem Anlegen lädt sich der Eintrag neu und gleicht die Befehle mit Discord ab."""
    discord.post(re.compile(r".*/applications/\d+/guilds/\d+/commands$"), json={"id": "9002"})


async def _start_command(hass, discord, entry):
    _mock_command_sync(discord)
    discord.get(f"{API}/users/@me/guilds", json=_guilds("Fuchsbau"))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "command"
    return result


async def test_add_a_command(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start_command(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], COMMAND | {"name": " /Status "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "/status"
    assert result["data"] == {
        "guild_id": "1",
        "name": "status",
        "description": "Zeigt den Status",
        "options": [
            {
                "name": "raum",
                "type": 3,
                "required": False,
                "description": "Welcher Raum",
                "choices": [{"name": "bett", "value": "bett"}, {"name": "bad", "value": "bad"}],
            }
        ],
        "reply": "",
        "ephemeral": True,
        "everyone": False,
        "users": ["555"],
        "roles": [],
    }


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"name": "Mit Leerzeichen"}, "invalid_name"),
        ({"description": ""}, "invalid_description"),
        ({"options": "kaputt"}, "invalid_options"),
        ({"options": "\n".join(f"o{i}:text:x" for i in range(6))}, "too_many_options"),
        ({"users": ["stefan"]}, "invalid_ids"),
        ({"users": [], "roles": []}, "no_permission"),
    ],
)
async def test_command_validation(hass, discord, changes, error):
    entry = await setup_entry(hass, bot_entry())
    result = await _start_command(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], COMMAND | changes)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_a_command_needs_no_own_permission_with_bot_wide_users(hass, discord):
    entry = await setup_entry(hass, bot_entry(options={"allowed_users": ["888"]}))
    result = await _start_command(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], COMMAND | {"users": []})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_command_for_everyone(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start_command(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], COMMAND | {"users": [], "everyone": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_same_command_twice(hass, discord):
    discord.post(f"{API}/applications/{BOT_ID}/guilds/1/commands", json={"id": "9001"})
    entry = await setup_entry(hass, bot_entry([command_subentry()]))
    result = await _start_command(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], COMMAND)
    assert result["errors"] == {"base": "already_exists"}


async def test_command_with_two_servers(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    _mock_command_sync(discord)
    discord.get(f"{API}/users/@me/guilds", json=_guilds("Fuchsbau", "Hasenbau"))
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_GUILD_ID: "2"})
    assert result["step_id"] == "command"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], COMMAND)
    assert result["data"]["guild_id"] == "2"


async def test_command_when_the_bot_is_on_no_server(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.get(f"{API}/users/@me/guilds", json=[])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"), context={"source": SOURCE_USER}
    )
    assert result["reason"] == "no_guilds"


async def test_reconfigure_a_command(hass, discord):
    discord.post(f"{API}/applications/{BOT_ID}/guilds/1/commands", json={"id": "9001"})
    discord.delete(f"{API}/applications/{BOT_ID}/guilds/1/commands/9001", status=204)  # der alte Name fällt weg
    entry = await setup_entry(hass, bot_entry([command_subentry(options=parse_options("raum:text:Raum"))]))
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "command")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "command"), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id}
    )
    assert result["step_id"] == "reconfigure"
    suggested = {k.schema: k.description["suggested_value"] for k in result["data_schema"].schema if k.description}
    assert suggested["options"] == "raum:text:Raum"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], COMMAND | {"name": "lage", "options": ""}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    updated = entry.subentries[sub.subentry_id]
    assert updated.title == "/lage"
    assert updated.unique_id == "cmd_1_lage"
    assert updated.data["options"] == []
