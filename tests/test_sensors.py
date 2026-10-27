"""Sensoren für Server und beobachtete Mitglieder: Zahlen von Discord, Zustand aus dem Gateway."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.discord_hub.const import DOMAIN, OFFLINE_GRACE_SECONDS
from custom_components.discord_hub.gateway import (
    INTENT_GUILD_PRESENCES,
    INTENT_GUILD_VOICE_STATES,
)

from .conftest import API, FakeGateway, bot_entry, listening_entry, member_subentry, server_subentry, setup_entry

COUNTS = {"id": "1", "name": "Fuchsbau", "approximate_member_count": 12, "approximate_presence_count": 5}


def guild_create(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "1",
        "name": "Fuchsbau",
        "channels": [{"id": "10", "name": "Lobby", "type": 2}, {"id": "11", "name": "Spiele", "type": 2}],
        "voice_states": [{"user_id": "555", "channel_id": "10"}],
        "presences": [
            {
                "user": {"id": "555"},
                "status": "idle",
                "activities": [{"name": "Valorant", "type": 0, "details": "Ranked"}],
                "client_status": {"desktop": "idle"},
            }
        ],
    }
    return data | changes


async def start(hass: HomeAssistant, discord, entry, counts: dict[str, Any] | None = COUNTS) -> SimpleNamespace:
    """Eintrag einrichten, warten bis das Gateway gebaut ist und die Verbindung als „steht“ melden."""
    if counts is not None:
        discord.get(f"{API}/guilds/1", json=counts)
    await setup_entry(hass, entry)
    for _ in range(100):
        if FakeGateway.instances or not entry.runtime_data.listener.enabled:
            break
        await asyncio.sleep(0)
    await hass.async_block_till_done()
    listener = entry.runtime_data.listener
    registry = er.async_get(hass)

    def entity(domain: str, key: str) -> str | None:
        return registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")

    return SimpleNamespace(entry=entry, listener=listener, entity=entity)


async def connect(hass: HomeAssistant, bot: SimpleNamespace, **changes: Any) -> None:
    """Das Gateway meldet sich an und schickt den Zustand des Servers."""
    bot.listener._on_status(True)
    await bot.listener._dispatch("GUILD_CREATE", guild_create(**changes))
    await hass.async_block_till_done()


async def test_server_counts_come_from_discord(hass, discord):
    bot = await start(hass, discord, bot_entry([server_subentry()]))
    members = hass.states.get(bot.entity("sensor", "server_1_members"))
    online = hass.states.get(bot.entity("sensor", "server_1_online"))
    assert members.state == "12"
    assert online.state == "5"
    assert members.attributes["state_class"] == "measurement"


async def test_server_counts_are_unavailable_when_discord_refuses(hass, discord):
    discord.get(f"{API}/guilds/1", status=403, json={"code": 50001, "message": "Missing Access"})
    bot = await start(hass, discord, bot_entry([server_subentry()]), counts=None)
    # der Eintrag lädt auch dann, nur die Zahlen fehlen
    assert bot.entry.state is ConfigEntryState.LOADED
    assert hass.states.get(bot.entity("sensor", "server_1_members")).state == STATE_UNAVAILABLE
    assert hass.states.get(bot.entity("sensor", "server_1_voice")) is not None


async def test_a_watched_server_turns_listening_on_with_the_voice_intent(hass, discord):
    await start(hass, discord, bot_entry([server_subentry()]))
    [gateway] = FakeGateway.instances
    assert gateway.intents & INTENT_GUILD_VOICE_STATES
    assert not gateway.intents & INTENT_GUILD_PRESENCES


@pytest.mark.parametrize(
    ("subentry", "options", "asks"),
    [
        (member_subentry, {}, False),  # ohne die Option bleibt der privilegierte Intent aus
        (server_subentry, {"track_presence": True}, False),  # ohne Mitglied gibt es nichts zu verfolgen
        (member_subentry, {"track_presence": True}, True),
    ],
)
async def test_the_presence_intent_needs_the_option_and_a_member(hass, discord, subentry, options, asks):
    await start(hass, discord, listening_entry([subentry()], **options))
    assert bool(FakeGateway.instances[0].intents & INTENT_GUILD_PRESENCES) is asks


async def test_voice_users_follow_the_gateway(hass, discord):
    bot = await start(hass, discord, bot_entry([server_subentry(), member_subentry()]))
    voice = bot.entity("sensor", "server_1_voice")
    assert hass.states.get(voice).state == STATE_UNAVAILABLE  # noch keine Verbindung
    await connect(hass, bot)
    state = hass.states.get(voice)
    assert state.state == "1"
    assert state.attributes["channels"] == {"Lobby": ["Stefan"]}  # der Name kommt vom beobachteten Mitglied
    joined = {"guild_id": "1", "user_id": "777", "channel_id": "11", "member": {"nick": "Fuchs", "user": {"id": "777"}}}
    await bot.listener._dispatch("VOICE_STATE_UPDATE", joined)
    await hass.async_block_till_done()
    state = hass.states.get(voice)
    assert state.state == "2"
    assert state.attributes["channels"] == {"Lobby": ["Stefan"], "Spiele": ["Fuchs"]}
    await bot.listener._dispatch("VOICE_STATE_UPDATE", joined | {"channel_id": None})
    await hass.async_block_till_done()
    assert hass.states.get(voice).state == "1"


async def test_a_member_in_a_voice_channel(hass, discord):
    bot = await start(hass, discord, bot_entry([member_subentry()]))
    in_voice = bot.entity("binary_sensor", "member_1_555_voice")
    assert hass.states.get(in_voice).state == STATE_UNAVAILABLE
    await connect(hass, bot)
    state = hass.states.get(in_voice)
    assert state.state == STATE_ON
    assert state.attributes["channel"] == "Lobby"
    assert state.attributes["channel_id"] == "10"
    await bot.listener._dispatch("VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "555", "channel_id": "11"})
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).attributes["channel"] == "Spiele"
    await bot.listener._dispatch("VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "555", "channel_id": None})
    await hass.async_block_till_done()
    state = hass.states.get(in_voice)
    assert state.state == STATE_OFF
    assert "channel" not in state.attributes


async def test_status_and_activity_of_a_member(hass, discord):
    bot = await start(hass, discord, listening_entry([member_subentry()], track_presence=True))
    status = bot.entity("sensor", "member_1_555_status")
    activity = bot.entity("sensor", "member_1_555_activity")
    await connect(hass, bot)
    assert hass.states.get(status).state == "idle"
    assert hass.states.get(status).attributes["platforms"] == ["desktop"]
    assert hass.states.get(activity).state == "Valorant"
    assert hass.states.get(activity).attributes["type"] == "playing"
    assert hass.states.get(activity).attributes["details"] == "Ranked"
    offline = {"guild_id": "1", "user": {"id": "555"}, "status": "offline", "activities": []}
    await bot.listener._dispatch("PRESENCE_UPDATE", offline)
    await hass.async_block_till_done()
    assert hass.states.get(status).state == "offline"
    assert hass.states.get(activity).state == STATE_UNKNOWN


async def test_status_sensors_exist_only_with_the_option(hass, discord):
    bot = await start(hass, discord, listening_entry([member_subentry()]))
    assert bot.entity("sensor", "member_1_555_status") is None
    assert bot.entity("sensor", "member_1_555_activity") is None
    assert bot.entity("binary_sensor", "member_1_555_voice")  # den Sprachkanal sieht man auch ohne den Intent


async def test_sensors_wait_for_a_short_connection_loss(hass, discord):
    bot = await start(hass, discord, bot_entry([member_subentry()]))
    in_voice = bot.entity("binary_sensor", "member_1_555_voice")
    await connect(hass, bot)
    bot.listener._on_status(False)  # Discord verlangt regelmäßig eine neue Verbindung
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).state == STATE_ON
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=OFFLINE_GRACE_SECONDS + 1))
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).state == STATE_UNAVAILABLE
    bot.listener._on_status(True)
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).state == STATE_ON


async def test_a_connection_that_returns_in_time_never_shows_as_unavailable(hass, discord):
    bot = await start(hass, discord, bot_entry([member_subentry()]))
    in_voice = bot.entity("binary_sensor", "member_1_555_voice")
    await connect(hass, bot)
    bot.listener._on_status(False)
    bot.listener._on_status(True)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=OFFLINE_GRACE_SECONDS + 1))
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).state == STATE_ON


async def test_a_fatal_error_makes_the_sensors_unavailable_at_once(hass, discord):
    bot = await start(hass, discord, bot_entry([member_subentry()]))
    in_voice = bot.entity("binary_sensor", "member_1_555_voice")
    await connect(hass, bot)
    bot.listener._on_fatal("intents")
    await hass.async_block_till_done()
    assert hass.states.get(in_voice).state == STATE_UNAVAILABLE


async def test_events_of_other_servers_are_ignored(hass, discord):
    bot = await start(hass, discord, bot_entry([server_subentry()]))
    await bot.listener._dispatch("VOICE_STATE_UPDATE", {"guild_id": "9", "user_id": "5", "channel_id": "10"})
    await connect(hass, bot)
    assert hass.states.get(bot.entity("sensor", "server_1_voice")).state == "1"


async def test_events_are_not_kept_when_nothing_is_watched(hass, discord):
    entry = await setup_entry(hass, listening_entry())
    await asyncio.sleep(0)
    listener = entry.runtime_data.listener
    await listener._dispatch("GUILD_CREATE", guild_create())
    assert listener.monitor.guilds == {}


async def test_the_connected_sensor_shows_how_the_connection_was_rebuilt(hass, discord):
    bot = await start(hass, discord, bot_entry([server_subentry()]))
    gateway = FakeGateway.instances[0]
    gateway.stats.sessions = 1
    gateway.stats.resumes = 3
    gateway.stats.reconnects = 4
    gateway.stats.last_reason = "reconnect_requested"
    gateway.stats.last_connected = dt_util.utcnow()
    bot.listener._on_status(True)
    await hass.async_block_till_done()
    attributes = hass.states.get(bot.entity("binary_sensor", "connected")).attributes
    assert attributes["sessions"] == 1
    assert attributes["resumes"] == 3
    assert attributes["reconnects"] == 4
    assert attributes["last_reason"] == "reconnect_requested"
    assert attributes["last_connected"] == gateway.stats.last_connected.isoformat()
    assert attributes["last_disconnected"] is None
