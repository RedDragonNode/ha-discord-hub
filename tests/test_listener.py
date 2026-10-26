"""Auf Discord hören: Befehle, Buttons, Reaktionen, Nachrichten und die Antworten darauf."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.discord_hub import listener as listener_module
from custom_components.discord_hub.const import (
    DOMAIN,
    EVENT_BUTTON,
    EVENT_COMMAND,
    EVENT_MESSAGE,
    EVENT_REACTION,
)
from custom_components.discord_hub.gateway import (
    INTENT_DIRECT_MESSAGE_REACTIONS,
    INTENT_GUILD_MESSAGE_REACTIONS,
    INTENT_GUILDS,
    INTENT_MESSAGE_CONTENT,
)
from custom_components.discord_hub.runtime import threads_store

from .conftest import (
    API,
    BOT_ID,
    FakeGateway,
    bot_entry,
    command_subentry,
    listening_entry,
    setup_entry,
)

HOOK = f"{API}/webhooks/{BOT_ID}/tok-900"
USER = "555"


async def start(hass: HomeAssistant, entry) -> Any:
    """Eintrag einrichten und warten, bis der Listener fertig gestartet ist (Befehle abgeglichen, Gateway gebaut)."""
    await setup_entry(hass, entry)
    for _ in range(100):
        if FakeGateway.instances or not entry.runtime_data.listener.enabled:
            break
        await asyncio.sleep(0)
    await hass.async_block_till_done()
    return entry.runtime_data.listener


def mock_commands(discord, command_id="9001"):
    discord.post(f"{API}/applications/{BOT_ID}/guilds/1/commands", json={"id": command_id})


def mock_callback(discord, iid="900", token="tok-900"):
    discord.post(f"{API}/interactions/{iid}/{token}/callback", status=204)


def interaction(kind=2, user=USER, roles=(), iid="900", token="tok-900", **data) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": iid,
        "token": token,
        "type": kind,
        "guild_id": "1",
        "channel_id": "100",
        "member": {"user": {"id": user, "username": "stefan", "global_name": "Stefan"}, "roles": list(roles)},
        "data": data,
    }
    return payload


def command_call(name="status", options=None, **kwargs) -> dict[str, Any]:
    return interaction(2, name=name, options=options or [], **kwargs)


def button_click(custom_id="erledigt", **kwargs) -> dict[str, Any]:
    payload = interaction(3, custom_id=custom_id, component_type=2, **kwargs)
    payload["message"] = {"id": "4711"}
    return payload


def body_of(mock, method: str, suffix: str) -> Any:
    calls = [c for c in mock.mock_calls if c[0].upper() == method and c[1].path.endswith(suffix)]
    assert calls, f"kein {method} auf {suffix}"
    return calls[-1][2]


@pytest.fixture
async def bot(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    entry = listening_entry([command_subentry()])
    listener = await start(hass, entry)
    return SimpleNamespace(entry=entry, listener=listener, discord=discord)


# ---------------------------------------------------------------- Einrichten
async def test_commands_are_created_on_discord(hass, bot):
    body = body_of(bot.discord, "POST", "/guilds/1/commands")
    assert body == {"name": "status", "type": 1, "description": "Zeigt den Status"}
    assert bot.entry.runtime_data.registered_commands == {"1": {"status": "9001"}}
    stored = await threads_store(hass, bot.entry.entry_id).async_load()
    assert stored["commands"] == {"1": {"status": "9001"}}


async def test_the_listener_builds_a_gateway_with_the_default_intents(hass, bot):
    [gateway] = FakeGateway.instances
    assert gateway.token == "bot-token-geheim-123"
    assert gateway.intents == INTENT_GUILDS | INTENT_GUILD_MESSAGE_REACTIONS | INTENT_DIRECT_MESSAGE_REACTIONS


async def test_receiving_messages_asks_for_the_message_content_intent(hass, discord):
    entry = listening_entry(receive_messages=True)
    await start(hass, entry)
    assert FakeGateway.instances[0].intents & INTENT_MESSAGE_CONTENT


async def test_a_bot_without_listening_and_commands_does_not_connect(hass, discord):
    await start(hass, bot_entry())
    assert FakeGateway.instances == []


async def test_commands_alone_turn_listening_on(hass, discord):
    mock_commands(discord)
    await start(hass, bot_entry([command_subentry()]))
    assert len(FakeGateway.instances) == 1


async def test_entities_for_a_listening_bot(hass, bot):
    registry = er.async_get(hass)
    connected = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{bot.entry.entry_id}_connected")
    assert connected
    assert hass.states.get(connected).state == "off"
    event = registry.async_get_entity_id("event", DOMAIN, f"{bot.entry.entry_id}_cmd_1_status")
    assert event
    assert hass.states.get(event).attributes["event_types"] == ["used"]


async def test_connected_follows_the_gateway(hass, bot):
    registry = er.async_get(hass)
    connected = registry.async_get_entity_id("binary_sensor", DOMAIN, f"{bot.entry.entry_id}_connected")
    gateway = FakeGateway.instances[0]
    gateway.connected = True
    bot.listener._on_status(True)
    await hass.async_block_till_done()
    assert hass.states.get(connected).state == "on"


async def test_unloading_stops_the_gateway(hass, bot):
    await hass.config_entries.async_unload(bot.entry.entry_id)
    assert FakeGateway.instances[0].closed


async def test_no_entities_without_listening(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_connected") is None


# ---------------------------------------------------------------- Befehle
async def test_allowed_command_is_acknowledged_and_fires_the_events(hass, bot):
    events = async_capture_events(hass, EVENT_COMMAND)
    await bot.listener._dispatch(
        "INTERACTION_CREATE", command_call(options=[{"name": "raum", "type": 3, "value": "bett"}])
    )
    await hass.async_block_till_done()
    assert body_of(bot.discord, "POST", "/interactions/900/tok-900/callback") == {
        "type": 5,
        "data": {"flags": 0},
    }
    [event] = events
    assert event.data == {
        "entry_id": bot.entry.entry_id,
        "bot_id": BOT_ID,
        "user_id": USER,
        "user_name": "Stefan",
        "roles": [],
        "guild_id": "1",
        "channel_id": "100",
        "interaction_id": "900",
        "command": "status",
        "options": {"raum": "bett"},
    }
    registry = er.async_get(hass)
    entity = registry.async_get_entity_id("event", DOMAIN, f"{bot.entry.entry_id}_cmd_1_status")
    state = hass.states.get(entity)
    assert state.attributes["event_type"] == "used"
    assert state.attributes["command"] == "status"
    assert state.attributes["options"] == {"raum": "bett"}


async def test_command_with_an_immediate_reply(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(reply="Ist unterwegs", ephemeral=True)]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call())
    await hass.async_block_till_done()
    assert body_of(discord, "POST", "/callback") == {"type": 4, "data": {"content": "Ist unterwegs", "flags": 64}}
    assert len(events) == 1


async def test_ephemeral_command_defers_privately(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(ephemeral=True)]))
    await listener._dispatch("INTERACTION_CREATE", command_call())
    assert body_of(discord, "POST", "/callback") == {"type": 5, "data": {"flags": 64}}


async def test_command_for_a_user_who_is_not_allowed(hass, bot):
    events = async_capture_events(hass, EVENT_COMMAND)
    await bot.listener._dispatch("INTERACTION_CREATE", command_call(user="999"))
    await hass.async_block_till_done()
    assert body_of(bot.discord, "POST", "/callback") == {
        "type": 4,
        "data": {"content": "You are not allowed to do this.", "flags": 64},
    }
    assert events == []


async def test_command_allowed_by_role(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(users=[], roles=["777"])]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call(user="999", roles=["1", "777"]))
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["roles"] == ["1", "777"]


async def test_command_for_everyone(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(users=[], everyone=True)]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call(user="999"))
    await hass.async_block_till_done()
    assert len(events) == 1


async def test_command_without_any_permission_is_denied(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(users=[])]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call(user=USER))
    await hass.async_block_till_done()
    assert events == []


async def test_command_uses_the_bot_wide_allowed_users(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    mock_callback(discord, "901", "tok-901")
    listener = await start(hass, listening_entry([command_subentry(users=[])], allowed_users=["888"]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call(user=USER))
    await listener._dispatch("INTERACTION_CREATE", command_call(user="888", iid="901", token="tok-901"))
    await hass.async_block_till_done()
    assert [e.data["user_id"] for e in events] == ["888"]


async def test_unknown_command(hass, bot):
    events = async_capture_events(hass, EVENT_COMMAND)
    await bot.listener._dispatch("INTERACTION_CREATE", command_call(name="gibtsnicht"))
    assert body_of(bot.discord, "POST", "/callback")["data"]["content"] == "I do not know this command."
    assert events == []


async def test_no_event_when_the_acknowledgement_fails(hass, discord):
    mock_commands(discord)
    discord.post(f"{API}/interactions/900/tok-900/callback", status=404, json={"message": "Unknown interaction"})
    listener = await start(hass, listening_entry([command_subentry()]))
    events = async_capture_events(hass, EVENT_COMMAND)
    await listener._dispatch("INTERACTION_CREATE", command_call())
    await hass.async_block_till_done()
    assert events == []


async def test_german_texts_with_a_german_installation(hass, bot):
    hass.config.language = "de"
    await bot.listener._dispatch("INTERACTION_CREATE", command_call(user="999"))
    assert body_of(bot.discord, "POST", "/callback")["data"]["content"] == "Das darfst du nicht."


# ---------------------------------------------------------------- respond
async def respond(hass, **data):
    return await hass.services.async_call(DOMAIN, "respond", data, blocking=True, return_response=True)


async def test_first_response_fills_the_deferred_message_and_later_ones_follow_up(hass, bot):
    await bot.listener._dispatch("INTERACTION_CREATE", command_call())
    bot.discord.patch(f"{HOOK}/messages/@original", json={"id": "31"})
    bot.discord.post(HOOK, json={"id": "32"})
    first = await respond(hass, interaction_id="900", message="Alles gut", embeds={"title": "Status"})
    second = await respond(hass, interaction_id="900", message="Noch etwas")
    assert first == {"message_id": "31"}
    assert second == {"message_id": "32"}
    patch = body_of(bot.discord, "PATCH", "/messages/@original")
    assert patch["content"] == "Alles gut"
    assert patch["embeds"] == [{"title": "Status"}]
    assert "message_reference" not in patch
    follow_up = body_of(bot.discord, "POST", f"/webhooks/{BOT_ID}/tok-900")
    assert follow_up["content"] == "Noch etwas"
    assert "flags" not in follow_up


async def test_follow_ups_of_a_private_command_stay_private(hass, discord):
    mock_commands(discord)
    mock_callback(discord)
    listener = await start(hass, listening_entry([command_subentry(reply="ok", ephemeral=True)]))
    await listener._dispatch("INTERACTION_CREATE", command_call())
    discord.post(HOOK, json={"id": "32"})
    await respond(hass, interaction_id="900", message="nur für dich")
    assert body_of(discord, "POST", f"/webhooks/{BOT_ID}/tok-900")["flags"] == 64


async def test_unanswered_command_is_closed_with_done(hass, bot, monkeypatch):
    monkeypatch.setattr(listener_module, "RESPOND_GRACE_SECONDS", 0)
    bot.discord.patch(f"{HOOK}/messages/@original", json={"id": "31"})
    await bot.listener._dispatch("INTERACTION_CREATE", command_call())
    for _ in range(20):
        await asyncio.sleep(0.01)
        if any(c[0].upper() == "PATCH" for c in bot.discord.mock_calls):
            break
    assert body_of(bot.discord, "PATCH", "/messages/@original") == {"content": "Done."}
    # eine späte Antwort ersetzt das „Done“
    await respond(hass, interaction_id="900", message="Jetzt wirklich")
    assert body_of(bot.discord, "PATCH", "/messages/@original")["content"] == "Jetzt wirklich"
    assert not [
        c for c in bot.discord.mock_calls if c[0].upper() == "POST" and c[1].path.endswith(f"/{BOT_ID}/tok-900")
    ]


async def test_answered_command_is_not_closed_again(hass, bot):
    bot.discord.patch(f"{HOOK}/messages/@original", json={"id": "31"})
    await bot.listener._dispatch("INTERACTION_CREATE", command_call())
    await respond(hass, interaction_id="900", message="Schon da")
    interaction = bot.listener.get_interaction("900")
    assert interaction.answered
    await asyncio.sleep(0)  # die abgebrochene Wartezeit läuft aus
    assert interaction.fallback.cancelled()


async def test_respond_to_an_unknown_interaction(hass, bot):
    with pytest.raises(ServiceValidationError) as err:
        await respond(hass, interaction_id="404", message="x")
    assert err.value.translation_key == "unknown_interaction"


async def test_old_interactions_are_forgotten(hass, bot, monkeypatch):
    await bot.listener._dispatch("INTERACTION_CREATE", command_call())
    assert bot.listener.get_interaction("900")
    monkeypatch.setattr(listener_module, "INTERACTION_SECONDS", -1)
    assert bot.listener.get_interaction("900") is None


async def test_respond_errors_are_translated(hass, bot):
    await bot.listener._dispatch("INTERACTION_CREATE", command_call())
    bot.discord.patch(f"{HOOK}/messages/@original", status=404, json={"message": "Unknown Webhook"})
    with pytest.raises(HomeAssistantError) as err:
        await respond(hass, interaction_id="900", message="x")
    assert err.value.translation_key == "not_found"


# ---------------------------------------------------------------- Buttons
async def test_button_click_is_acknowledged_and_fires_an_event(hass, bot):
    events = async_capture_events(hass, EVENT_BUTTON)
    await bot.listener._dispatch("INTERACTION_CREATE", button_click())
    await hass.async_block_till_done()
    assert body_of(bot.discord, "POST", "/callback") == {"type": 6}
    [event] = events
    assert event.data["custom_id"] == "erledigt"
    assert event.data["message_id"] == "4711"
    assert event.data["user_id"] == USER
    assert event.data["interaction_id"] == "900"


async def test_button_response_can_change_the_message_or_follow_up(hass, bot):
    await bot.listener._dispatch("INTERACTION_CREATE", button_click())
    bot.discord.patch(f"{HOOK}/messages/@original", json={"id": "4711"})
    bot.discord.post(HOOK, json={"id": "32"})
    await respond(hass, interaction_id="900", message="✅ erledigt", buttons=[], update=True)
    patch = body_of(bot.discord, "PATCH", "/messages/@original")
    assert patch["content"] == "✅ erledigt"
    assert patch["components"] == []
    await respond(hass, interaction_id="900", message="Danke", ephemeral=True)
    assert body_of(bot.discord, "POST", f"/webhooks/{BOT_ID}/tok-900")["flags"] == 64


async def test_button_from_a_user_who_is_not_allowed(hass, discord):
    mock_callback(discord)
    listener = await start(hass, listening_entry(allowed_users=["888"]))
    events = async_capture_events(hass, EVENT_BUTTON)
    await listener._dispatch("INTERACTION_CREATE", button_click(user="999"))
    await hass.async_block_till_done()
    assert events == []
    assert body_of(discord, "POST", "/callback")["data"]["flags"] == 64


async def test_buttons_are_open_to_everyone_without_a_list(hass, discord):
    mock_callback(discord)
    listener = await start(hass, listening_entry())
    events = async_capture_events(hass, EVENT_BUTTON)
    await listener._dispatch("INTERACTION_CREATE", button_click(user="999"))
    await hass.async_block_till_done()
    assert len(events) == 1


# ---------------------------------------------------------------- Reaktionen und Nachrichten
def reaction(name="✅", user=USER, emoji_id=None, **extra) -> dict[str, Any]:
    return {
        "user_id": user,
        "channel_id": "100",
        "guild_id": "1",
        "message_id": "4711",
        "emoji": {"name": name, "id": emoji_id},
        "member": {"roles": ["7"], "user": {"id": user, "username": "stefan"}},
        **extra,
    }


async def test_reactions_fire_events(hass, discord):
    listener = await start(hass, listening_entry())
    events = async_capture_events(hass, EVENT_REACTION)
    await listener._dispatch("MESSAGE_REACTION_ADD", reaction())
    await listener._dispatch("MESSAGE_REACTION_REMOVE", reaction(name="party", emoji_id="123"))
    await hass.async_block_till_done()
    assert [(e.data["action"], e.data["emoji"], e.data["emoji_id"]) for e in events] == [
        ("add", "✅", None),
        ("remove", "party", "123"),
    ]
    assert events[0].data["message_id"] == "4711"
    assert events[0].data["roles"] == ["7"]


async def test_own_and_unwanted_reactions_are_ignored(hass, discord):
    listener = await start(hass, listening_entry(allowed_users=[USER]))
    events = async_capture_events(hass, EVENT_REACTION)
    await listener._dispatch("MESSAGE_REACTION_ADD", reaction(user=BOT_ID))
    await listener._dispatch("MESSAGE_REACTION_ADD", reaction(user="999"))
    await listener._dispatch("MESSAGE_REACTION_ADD", reaction(user=USER))
    await hass.async_block_till_done()
    assert [e.data["user_id"] for e in events] == [USER]


def message(content="hallo", author_id=USER, bot=False) -> dict[str, Any]:
    return {
        "id": "5000",
        "channel_id": "100",
        "guild_id": "1",
        "content": content,
        "author": {"id": author_id, "username": "stefan", "bot": bot},
        "member": {"roles": ["7"]},
        "message_reference": {"message_id": "4999"},
    }


async def test_messages_only_when_asked_for(hass, discord):
    listener = await start(hass, listening_entry())
    events = async_capture_events(hass, EVENT_MESSAGE)
    await listener._dispatch("MESSAGE_CREATE", message())
    await hass.async_block_till_done()
    assert events == []


async def test_messages_fire_events_but_not_from_bots(hass, discord):
    listener = await start(hass, listening_entry(receive_messages=True))
    events = async_capture_events(hass, EVENT_MESSAGE)
    await listener._dispatch("MESSAGE_CREATE", message("Licht an"))
    await listener._dispatch("MESSAGE_CREATE", message("von einem Bot", bot=True))
    await listener._dispatch("MESSAGE_CREATE", message("von mir", author_id=BOT_ID))
    await hass.async_block_till_done()
    [event] = events
    assert event.data["content"] == "Licht an"
    assert event.data["user_id"] == USER
    assert event.data["reply_to"] == "4999"
    assert event.data["message_id"] == "5000"


# ---------------------------------------------------------------- Abgleich mit Discord
async def test_removed_commands_are_deleted_on_discord(hass, discord):
    mock_commands(discord)
    entry = listening_entry([command_subentry()])
    entry.add_to_hass(hass)
    await threads_store(hass, entry.entry_id).async_save({"commands": {"1": {"alt": "777", "status": "9001"}}})
    discord.delete(f"{API}/applications/{BOT_ID}/guilds/1/commands/777", status=204)
    await start(hass, entry)
    deleted = next(c for c in discord.mock_calls if c[0].upper() == "DELETE")
    assert deleted[1].path.endswith("/commands/777")
    assert entry.runtime_data.registered_commands == {"1": {"status": "9001"}}


async def test_without_commands_everything_registered_is_removed(hass, discord):
    entry = listening_entry()
    entry.add_to_hass(hass)
    await threads_store(hass, entry.entry_id).async_save({"commands": {"1": {"alt": "777"}}})
    discord.delete(f"{API}/applications/{BOT_ID}/guilds/1/commands/777", status=404, json={"message": "Unknown"})
    await start(hass, entry)
    assert entry.runtime_data.registered_commands == {}


async def test_missing_scope_creates_a_repair_issue_and_success_removes_it(hass, discord):
    discord.post(
        f"{API}/applications/{BOT_ID}/guilds/1/commands",
        status=403,
        json={"message": "Missing Access", "code": 50001},
    )
    entry = listening_entry([command_subentry()])
    listener = await start(hass, entry)
    issue_id = f"commands_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    discord.clear_requests()
    mock_commands(discord)
    await listener.async_sync_commands()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_fatal_intents_create_an_issue_and_connecting_removes_it(hass, discord):
    entry = listening_entry(receive_messages=True)
    listener = await start(hass, entry)
    listener._on_fatal("intents")
    issue_id = f"intents_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    listener._on_status(True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_fatal_auth_error_asks_for_a_new_token(hass, discord):
    listener = await start(hass, listening_entry())
    listener._on_fatal("auth")
    await hass.async_block_till_done()
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())
