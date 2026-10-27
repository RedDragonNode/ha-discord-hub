"""Dialoge zum Beobachten von Servern und Mitgliedern."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.discord_hub.const import CONF_GUILD_ID

from .conftest import API, bot_entry, member_subentry, server_subentry, setup_entry

COUNTS = {"id": "1", "name": "Fuchsbau", "approximate_member_count": 12, "approximate_presence_count": 5}
MEMBER = {"user": {"id": "555", "username": "stefan", "global_name": "Stefan"}, "nick": None}


def _guilds(*names: str):
    return [{"id": str(i + 1), "name": name} for i, name in enumerate(names)]


async def _start(hass, discord, entry, kind: str, *names: str):
    # nach dem Anlegen lädt sich der Eintrag neu und holt die Zahlen des Servers
    discord.get(f"{API}/guilds/1", json=COUNTS)
    discord.get(f"{API}/users/@me/guilds", json=_guilds(*names))
    return await hass.config_entries.subentries.async_init((entry.entry_id, kind), context={"source": SOURCE_USER})


# ---------------------------------------------------------------- Server
async def test_watch_a_server(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, discord, entry, "server", "Fuchsbau")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Fuchsbau"
    assert result["data"] == {"guild_id": "1", "name": "Fuchsbau"}
    await hass.async_block_till_done()
    assert any(s.unique_id == "server_1" for s in entry.subentries.values())


async def test_watch_one_of_two_servers(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, discord, entry, "server", "Fuchsbau", "Hasenbau")
    assert result["step_id"] == "user"
    discord.get(f"{API}/guilds/2", json=COUNTS | {"id": "2"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_GUILD_ID: "2"})
    assert result["data"]["guild_id"] == "2"
    assert result["title"] == "Hasenbau"


async def test_a_server_twice(hass, discord):
    entry = await setup_entry(hass, bot_entry([server_subentry()]))
    result = await _start(hass, discord, entry, "server", "Fuchsbau")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_watch_a_server_when_the_bot_is_on_none(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, discord, entry, "server")
    assert result["reason"] == "no_guilds"


# ---------------------------------------------------------------- Mitglieder
async def _member_form(hass, discord, entry):
    result = await _start(hass, discord, entry, "member", "Fuchsbau")
    assert result["step_id"] == "member"
    return result


async def test_watch_a_member(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _member_form(hass, discord, entry)
    discord.get(f"{API}/guilds/1/members/555", json=MEMBER)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": " 555 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Stefan"
    assert result["data"] == {"guild_id": "1", "user_id": "555", "name": "Stefan"}


async def test_the_nickname_wins_over_the_global_name(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _member_form(hass, discord, entry)
    discord.get(f"{API}/guilds/1/members/555", json=MEMBER | {"nick": "Stefan vom Bau"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "555"})
    assert result["title"] == "Stefan vom Bau"


async def test_without_the_members_intent_the_user_itself_is_used(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _member_form(hass, discord, entry)
    discord.get(f"{API}/guilds/1/members/555", status=403, json={"code": 50001, "message": "Missing Access"})
    discord.get(f"{API}/users/555", json={"id": "555", "username": "stefan", "global_name": "Stefan"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "555"})
    assert result["title"] == "Stefan"


async def test_member_errors(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _member_form(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "stefan"})
    assert result["errors"] == {"base": "invalid_user"}
    discord.get(f"{API}/guilds/1/members/555", status=404, json={"code": 10007, "message": "Unknown Member"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "555"})
    assert result["errors"] == {"base": "unknown_member"}
    discord.get(f"{API}/guilds/1/members/556", status=502, json={"message": "Bad Gateway"})
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "556"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_a_member_twice(hass, discord):
    entry = await setup_entry(hass, bot_entry([member_subentry()]))
    result = await _member_form(hass, discord, entry)
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"user_id": "555"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
