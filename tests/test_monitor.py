"""Der Zustandsspeicher: Server, Sprachkanäle und Status aus den Ereignissen des Gateways."""

from __future__ import annotations

from typing import Any

from custom_components.discord_hub.monitor import Monitor, Presence, describe_activity


def guild_create(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "1",
        "name": "Fuchsbau",
        "channels": [{"id": "10", "name": "Lobby", "type": 2}, {"id": "11", "name": "Spiele", "type": 2}],
        "voice_states": [{"user_id": "555", "channel_id": "10"}, {"user_id": "666", "channel_id": None}],
        "presences": [
            {
                "user": {"id": "555"},
                "status": "online",
                "activities": [{"name": "Valorant", "type": 0}],
                "client_status": {"desktop": "online", "mobile": "online"},
            }
        ],
    }
    return data | changes


def monitor_with_guild() -> Monitor:
    monitor = Monitor()
    assert monitor.handle("GUILD_CREATE", guild_create())
    return monitor


def test_a_new_guild_brings_the_whole_state():
    monitor = monitor_with_guild()
    assert monitor.synced("1")
    assert not monitor.synced("2")
    assert monitor.voice_count("1") == 1  # wer in keinem Kanal ist, zählt nicht
    voice, channel = monitor.voice_of("1", "555")
    assert (voice.channel_id, channel) == ("10", "Lobby")
    assert monitor.voice_of("1", "666") is None
    presence = monitor.presence_of("1", "555")
    assert presence.status == "online"
    assert presence.platforms == ["desktop", "mobile"]


def test_a_second_guild_create_replaces_the_state():
    monitor = monitor_with_guild()
    monitor.handle("GUILD_CREATE", guild_create(voice_states=[], presences=[]))
    assert monitor.voice_count("1") == 0
    assert monitor.presence_of("1", "555").status == "offline"


def test_voice_join_move_and_leave():
    monitor = monitor_with_guild()
    member = {"nick": "Fuchs", "user": {"id": "777", "username": "fuchs77"}}
    assert monitor.handle(
        "VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "777", "channel_id": "11", "member": member}
    )
    assert monitor.voice_count("1") == 2
    assert monitor.voice_channels("1", {}) == {"Lobby": ["555"], "Spiele": ["Fuchs"]}
    # beim Wechsel schickt Discord auch ohne Mitglied einen Eintrag: der Name bleibt
    monitor.handle("VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "777", "channel_id": "10"})
    assert monitor.voice_channels("1", {}) == {"Lobby": ["555", "Fuchs"]}
    monitor.handle("VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "777", "channel_id": None})
    assert monitor.voice_count("1") == 1


def test_voice_names_fall_back_to_known_names_and_ids():
    monitor = monitor_with_guild()
    assert monitor.voice_channels("1", {"555": "Stefan"}) == {"Lobby": ["Stefan"]}
    assert monitor.voice_channels("1", {}) == {"Lobby": ["555"]}
    assert monitor.voice_channels("9", {}) == {}


def test_presence_updates_and_unknown_values():
    monitor = monitor_with_guild()
    assert monitor.presence_of("1", "999").status == "offline"  # wer nicht gemeldet ist, ist offline
    monitor.handle("PRESENCE_UPDATE", {"guild_id": "1", "user": {"id": "999"}, "status": "dnd", "activities": []})
    assert monitor.presence_of("1", "999").status == "dnd"
    monitor.handle("PRESENCE_UPDATE", {"guild_id": "1", "user": {"id": "999"}, "status": "invisible"})
    assert monitor.presence_of("1", "999").status == "offline"
    assert monitor.presence_of("9", "999") == Presence()


def test_channels_and_guild_changes():
    monitor = monitor_with_guild()
    monitor.handle("CHANNEL_UPDATE", {"guild_id": "1", "id": "10", "name": "Wohnzimmer"})
    assert monitor.voice_of("1", "555")[1] == "Wohnzimmer"
    monitor.handle("CHANNEL_DELETE", {"guild_id": "1", "id": "10"})
    assert monitor.voice_of("1", "555")[1] == "10"  # ohne Namen bleibt die ID
    monitor.handle("GUILD_UPDATE", {"id": "1", "name": "Bau"})
    assert monitor.guilds["1"].name == "Bau"


def test_events_of_unknown_guilds_are_ignored_and_deleting_forgets():
    monitor = Monitor()
    assert not monitor.handle("VOICE_STATE_UPDATE", {"guild_id": "1", "user_id": "5", "channel_id": "10"})
    assert not monitor.handle("CHANNEL_CREATE", {"id": "77", "type": 1})  # eine Direktnachricht hat keinen Server
    monitor = monitor_with_guild()
    assert monitor.handle("GUILD_DELETE", {"id": "1"})
    assert not monitor.synced("1")
    assert not monitor.handle("GUILD_DELETE", {"id": "1"})


def test_describe_a_game():
    presence = Presence(
        status="online",
        activities=[
            {"name": "Eigener Status", "type": 4, "state": "bin kurz weg"},
            {"name": "Valorant", "type": 0, "details": "Ranked", "state": "In Lobby"},
        ],
    )
    state, attributes = describe_activity(presence)
    assert state == "Valorant"
    assert attributes == {
        "type": "playing",
        "details": "Ranked",
        "state": "In Lobby",
        "activities": ["Eigener Status", "Valorant"],
    }


def test_describe_a_custom_status_and_nothing():
    state, attributes = describe_activity(Presence(activities=[{"name": "Custom Status", "type": 4, "state": "Pause"}]))
    assert state == "Pause"
    assert attributes["type"] == "custom"
    assert "state" not in attributes
    assert describe_activity(Presence()) == (None, {})
