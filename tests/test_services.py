"""Senden, Forum-Posts mit Tages-Thread und Verwalten, mit einem nachgestellten Discord."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.discord_hub import files
from custom_components.discord_hub.const import DOMAIN
from custom_components.discord_hub.runtime import threads_store

from .conftest import (
    API,
    FORUM_ID,
    TEXT_ID,
    USER_ID,
    WEBHOOK_ID,
    WEBHOOK_TOKEN,
    bot_entry,
    payload_of,
    reply,
    sequence,
    setup_entry,
    webhook_entry,
)

HOOK = f"{API}/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}"
FORUM = {
    "id": FORUM_ID,
    "type": 15,
    "available_tags": [
        {"id": "11", "name": "Fuchs"},
        {"id": "12", "name": "Hase", "emoji_name": "🐰", "moderated": True},
    ],
}


def entity_id(hass: HomeAssistant, entry, part: str) -> str:
    found = er.async_get(hass).async_get_entity_id("notify", DOMAIN, f"{entry.entry_id}_{part}")
    assert found, f"keine Entity für {part}"
    return found


RESPONDING = {"send_message", "forum_post", "edit_message", "update_thread", "list_forum_tags"}


async def call(hass: HomeAssistant, service: str, entity: str, **data: Any) -> Any:
    return await hass.services.async_call(
        DOMAIN, service, data, target={"entity_id": entity}, blocking=True, return_response=service in RESPONDING
    )


async def setup_failing(hass: HomeAssistant, entry) -> Any:
    """Einen Eintrag einrichten, dessen Einrichtung scheitern soll."""
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def sent(mock, method: str, path: str) -> list[tuple[Any, ...]]:
    return [c for c in mock.mock_calls if c[0].upper() == method and c[1].path.endswith(path)]


@pytest.fixture
async def bot(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    return SimpleNamespace(
        entry=entry,
        text=entity_id(hass, entry, TEXT_ID),
        forum=entity_id(hass, entry, FORUM_ID),
        dm=entity_id(hass, entry, f"dm_{USER_ID}"),
    )


# ---------------------------------------------------------------- Einrichten
async def test_bot_setup_creates_devices_and_entities(hass, bot):
    assert bot.entry.state is ConfigEntryState.LOADED
    devices = dr.async_get(hass)
    assert (
        devices.async_get_device_by_identifier((DOMAIN, bot.entry.entry_id), bot.entry.entry_id).name == "HA Waechter"
    )
    names = {d.name: d for d in dr.async_entries_for_config_entry(devices, bot.entry.entry_id)}
    assert set(names) == {"HA Waechter", "#allgemein", "fuchs", "Stefan"}
    assert names["#allgemein"].via_device_id == names["HA Waechter"].id
    assert names["fuchs"].model == "Forum-Kanal"
    assert hass.states.get(bot.text) is not None


async def test_setup_with_a_rejected_token_asks_for_a_new_one(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", status=401, json={"message": "401: Unauthorized"})
    entry = await setup_failing(hass, bot_entry())
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_setup_retries_when_discord_is_down(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", status=400, json={"message": "kaputt"})
    entry = bot_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_webhook_that_was_deleted_asks_for_a_new_address(hass, aioclient_mock):
    aioclient_mock.get(HOOK, status=404, json={"message": "Unknown Webhook"})
    entry = await setup_failing(hass, webhook_entry())
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_removing_the_entry_removes_the_stored_threads(hass, bot):
    await threads_store(hass, bot.entry.entry_id).async_save({"threads": {"x": {}}})
    await hass.config_entries.async_remove(bot.entry.entry_id)
    assert await threads_store(hass, bot.entry.entry_id).async_load() is None


# ---------------------------------------------------------------- Senden
async def test_notify_send_message_with_a_title(hass, bot, discord):
    discord.post(f"{API}/channels/{TEXT_ID}/messages", json={"id": "9", "channel_id": TEXT_ID})
    await hass.services.async_call(
        "notify", "send_message", {"entity_id": bot.text, "message": "Hallo", "title": "Fuchs"}, blocking=True
    )
    [(_, _, data, _)] = sent(discord, "POST", f"/channels/{TEXT_ID}/messages")
    assert data["content"] == "**Fuchs**\nHallo"
    assert hass.states.get(bot.text).state != "unknown"


async def test_send_message_returns_ids(hass, bot, discord):
    discord.post(f"{API}/channels/{TEXT_ID}/messages", json={"id": "9", "channel_id": TEXT_ID})
    response = await call(
        hass,
        "send_message",
        bot.text,
        message="Bewegung",
        embeds={"title": "Fuchs", "color": "#2ECC71"},
        reply_to=123,
    )
    assert response == {bot.text: {"message_id": "9", "channel_id": TEXT_ID}}
    [(_, _, data, headers)] = sent(discord, "POST", f"/channels/{TEXT_ID}/messages")
    assert data["content"] == "Bewegung"
    assert data["embeds"] == [{"title": "Fuchs", "color": 0x2ECC71}]
    assert data["message_reference"]["message_id"] == "123"
    assert data["allowed_mentions"] == {"parse": ["users", "roles"]}
    assert headers["Authorization"].startswith("Bot ")


async def test_send_message_into_a_thread(hass, bot, discord):
    discord.post(f"{API}/channels/777/messages", json={"id": "9", "channel_id": "777"})
    response = await call(hass, "send_message", bot.text, message="im Thread", thread_id="777")
    assert response[bot.text]["channel_id"] == "777"


async def test_send_message_with_a_camera_snapshot(hass, bot, discord):
    discord.post(f"{API}/channels/{TEXT_ID}/messages", json={"id": "9", "channel_id": TEXT_ID})
    image = SimpleNamespace(content=b"jpeg", content_type="image/jpeg")
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)):
        await call(hass, "send_message", bot.text, message="Schnappschuss", files="camera.fuchsrevier")
    [(_, _, form, _)] = sent(discord, "POST", f"/channels/{TEXT_ID}/messages")
    assert payload_of(form)["content"] == "Schnappschuss"
    assert form._fields[1][0]["filename"] == "fuchsrevier.jpg"


async def test_empty_message_is_refused(hass, bot, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "send_message", bot.text)
    assert err.value.translation_key == "empty_message"
    assert discord.call_count == 1  # nur die Prüfung beim Einrichten


async def test_direct_message_opens_the_channel_once(hass, bot, discord):
    discord.post(f"{API}/users/@me/channels", json={"id": "900"})
    discord.post(f"{API}/channels/900/messages", json={"id": "9", "channel_id": "900"})
    await call(hass, "send_message", bot.dm, message="eins")
    await call(hass, "send_message", bot.dm, message="zwei")
    assert len(sent(discord, "POST", "/users/@me/channels")) == 1
    assert len(sent(discord, "POST", "/channels/900/messages")) == 2


async def test_forbidden_is_a_readable_error(hass, bot, discord):
    discord.post(
        f"{API}/channels/{TEXT_ID}/messages", status=403, json={"message": "Missing Permissions", "code": 50013}
    )
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "send_message", bot.text, message="x")
    assert err.value.translation_key == "forbidden"
    assert "Missing Permissions" in str(err.value)


async def test_unauthorized_at_runtime_starts_reauth(hass, bot, discord):
    discord.post(f"{API}/channels/{TEXT_ID}/messages", status=401, json={"message": "401: Unauthorized"})
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, "send_message", bot.text, message="x")
    assert err.value.translation_key == "auth_failed"
    await hass.async_block_till_done()
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_file_too_large_is_explained(hass, bot, discord):
    discord.post(
        f"{API}/channels/{TEXT_ID}/messages", status=413, json={"message": "Request entity too large", "code": 40005}
    )
    image = SimpleNamespace(content=b"jpeg", content_type="image/jpeg")
    with (
        patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)),
        pytest.raises(HomeAssistantError) as err,
    ):
        await call(hass, "send_message", bot.text, files="camera.x")
    assert err.value.translation_key == "file_rejected"


# ---------------------------------------------------------------- Forum
def forum_mocks(discord, *, thread="700", first="701"):
    discord.get(f"{API}/channels/{FORUM_ID}", json=FORUM)
    discord.post(
        f"{API}/channels/{FORUM_ID}/threads",
        json={"id": thread, "type": 11, "message": {"id": first, "channel_id": thread}},
    )
    discord.post(f"{API}/channels/{thread}/messages", json={"id": "702", "channel_id": thread})


async def test_forum_post_resolves_tag_names(hass, bot, discord):
    forum_mocks(discord)
    response = await call(
        hass,
        "forum_post",
        bot.forum,
        thread_name="Bewegung Fuchs - 26.10.2026",
        message="Bewegung erkannt",
        embeds=[{"title": "Bewegung Fuchs", "description": "Um 14:03", "color": 3066993}],
        tags=["fuchs", "12"],
    )
    assert response == {bot.forum: {"thread_id": "700", "message_id": "701", "created": True}}
    [(_, _, data, _)] = sent(discord, "POST", f"/channels/{FORUM_ID}/threads")
    assert data["name"] == "Bewegung Fuchs - 26.10.2026"
    assert data["applied_tags"] == ["11", "12"]
    assert data["message"]["content"] == "Bewegung erkannt"
    assert data["message"]["embeds"][0]["color"] == 3066993


async def test_forum_post_with_ids_does_not_ask_discord_for_tags(hass, bot, discord):
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="x", message="y", tags="11")
    assert not sent(discord, "GET", f"/channels/{FORUM_ID}")


async def test_forum_post_with_an_unknown_tag(hass, bot, discord):
    forum_mocks(discord)
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "forum_post", bot.forum, thread_name="x", message="y", tags=["Igel"])
    assert err.value.translation_key == "unknown_tag"
    assert "Fuchs" in str(err.value)


async def test_forum_post_on_a_text_channel(hass, bot, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "forum_post", bot.text, thread_name="x", message="y")
    assert err.value.translation_key == "not_a_forum"


async def test_forum_post_truncates_the_thread_name(hass, bot, discord):
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="x" * 150, message="y")
    [(_, _, data, _)] = sent(discord, "POST", f"/channels/{FORUM_ID}/threads")
    assert len(data["name"]) == 100


async def test_daily_forum_post_reuses_the_thread_of_the_day(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    first = await call(hass, "forum_post", bot.forum, thread_name="Tag", message="eins", daily=True, key="fuchs")
    second = await call(hass, "forum_post", bot.forum, thread_name="Tag", message="zwei", daily=True, key="fuchs")
    assert first[bot.forum] == {"thread_id": "700", "message_id": "701", "created": True}
    assert second[bot.forum] == {"thread_id": "700", "message_id": "702", "created": False}
    assert len(sent(discord, "POST", f"/channels/{FORUM_ID}/threads")) == 1
    [(_, _, data, _)] = sent(discord, "POST", "/channels/700/messages")
    assert data["content"] == "zwei"


async def test_daily_forum_post_keys_are_separate(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="Tag", message="a", daily=True, key="fuchs")
    await call(hass, "forum_post", bot.forum, thread_name="Tag", message="b", daily=True, key="hase")
    assert len(sent(discord, "POST", f"/channels/{FORUM_ID}/threads")) == 2


async def test_daily_forum_post_starts_a_new_thread_the_next_day(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="Tag 1", message="a", daily=True)
    freezer.tick(timedelta(days=1))
    await call(hass, "forum_post", bot.forum, thread_name="Tag 2", message="b", daily=True)
    assert len(sent(discord, "POST", f"/channels/{FORUM_ID}/threads")) == 2


async def test_daily_forum_post_without_daily_always_creates_a_thread(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="a", message="a")
    await call(hass, "forum_post", bot.forum, thread_name="b", message="b")
    assert len(sent(discord, "POST", f"/channels/{FORUM_ID}/threads")) == 2


async def test_daily_thread_that_was_deleted_is_created_again(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    discord.get(f"{API}/channels/{FORUM_ID}", json=FORUM)
    discord.post(
        f"{API}/channels/{FORUM_ID}/threads",
        side_effect=sequence(
            reply(200, {"id": "700", "message": {"id": "701"}}), reply(200, {"id": "800", "message": {"id": "801"}})
        ),
    )
    discord.post(f"{API}/channels/700/messages", status=404, json={"message": "Unknown Channel", "code": 10003})
    await call(hass, "forum_post", bot.forum, thread_name="Tag", message="a", daily=True)
    again = await call(hass, "forum_post", bot.forum, thread_name="Tag", message="b", daily=True)
    assert again[bot.forum] == {"thread_id": "800", "message_id": "801", "created": True}


async def test_daily_thread_survives_a_reload(hass, bot, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    await call(hass, "forum_post", bot.forum, thread_name="Tag", message="a", daily=True)
    await hass.config_entries.async_reload(bot.entry.entry_id)
    await hass.async_block_till_done()
    again = await call(hass, "forum_post", bot.forum, thread_name="Tag", message="b", daily=True)
    assert again[bot.forum]["created"] is False


async def test_daily_posts_at_the_same_time_make_one_thread(hass, bot, discord, freezer):
    import asyncio

    freezer.move_to("2026-10-26 12:00:00")
    forum_mocks(discord)
    results = await asyncio.gather(
        *(call(hass, "forum_post", bot.forum, thread_name="Tag", message=str(i), daily=True) for i in range(4))
    )
    assert sum(r[bot.forum]["created"] for r in results) == 1
    assert len(sent(discord, "POST", f"/channels/{FORUM_ID}/threads")) == 1


async def test_list_forum_tags(hass, bot, discord):
    discord.get(f"{API}/channels/{FORUM_ID}", json=FORUM)
    response = await call(hass, "list_forum_tags", bot.forum)
    assert response[bot.forum]["tags"] == [
        {"id": "11", "name": "Fuchs", "emoji": None, "moderated": False},
        {"id": "12", "name": "Hase", "emoji": "🐰", "moderated": True},
    ]
    await call(hass, "list_forum_tags", bot.forum)
    assert len(sent(discord, "GET", f"/channels/{FORUM_ID}")) == 1  # beim zweiten Mal aus dem Speicher


async def test_list_forum_tags_of_a_text_channel(hass, bot, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "list_forum_tags", bot.text)
    assert err.value.translation_key == "not_a_forum"


# ---------------------------------------------------------------- Verwalten
async def test_edit_message(hass, bot, discord):
    discord.patch(f"{API}/channels/{TEXT_ID}/messages/55", json={"id": "55"})
    response = await call(hass, "edit_message", bot.text, message_id="55", message="neu")
    assert response == {bot.text: {"message_id": "55"}}
    [(_, _, data, _)] = sent(discord, "PATCH", f"/channels/{TEXT_ID}/messages/55")
    assert data == {"content": "neu"}


async def test_edit_message_in_a_thread_and_remove_embeds(hass, bot, discord):
    discord.patch(f"{API}/channels/777/messages/55", json={"id": "55"})
    await call(hass, "edit_message", bot.text, message_id="55", embeds=[], thread_id="777")
    [(_, _, data, _)] = sent(discord, "PATCH", "/channels/777/messages/55")
    assert data == {"embeds": []}


async def test_edit_message_without_changes(hass, bot, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "edit_message", bot.text, message_id="55")
    assert err.value.translation_key == "nothing_to_change"


async def test_delete_message(hass, bot, discord):
    discord.delete(f"{API}/channels/{TEXT_ID}/messages/55", status=204)
    await call(hass, "delete_message", bot.text, message_id="55")
    assert len(sent(discord, "DELETE", f"/channels/{TEXT_ID}/messages/55")) == 1


async def test_add_reaction_encodes_the_emoji(hass, bot, discord):
    discord.put(f"{API}/channels/{TEXT_ID}/messages/55/reactions/%E2%9C%85/@me", status=204)
    await call(hass, "add_reaction", bot.text, message_id="55", emoji="✅")
    [(_, url, _, _)] = sent(discord, "PUT", "/@me")
    assert url.raw_path.endswith("/reactions/%E2%9C%85/@me")


async def test_pin_and_unpin(hass, bot, discord):
    discord.put(f"{API}/channels/{TEXT_ID}/messages/pins/55", status=204)
    discord.delete(f"{API}/channels/{TEXT_ID}/messages/pins/55", status=204)
    await call(hass, "pin_message", bot.text, message_id="55")
    await call(hass, "unpin_message", bot.text, message_id="55")
    assert len(sent(discord, "PUT", "/pins/55")) == 1
    assert len(sent(discord, "DELETE", "/pins/55")) == 1


async def test_update_thread(hass, bot, discord):
    discord.patch(
        f"{API}/channels/700",
        json={"id": "700", "name": "Neu", "thread_metadata": {"archived": True, "locked": True}},
    )
    response = await call(hass, "update_thread", bot.forum, thread_id="700", archived=True, locked=True, name="Neu")
    assert response[bot.forum] == {"thread_id": "700", "name": "Neu", "archived": True, "locked": True}
    [(_, _, data, _)] = sent(discord, "PATCH", "/channels/700")
    assert data == {"archived": True, "locked": True, "name": "Neu"}


async def test_update_thread_without_changes(hass, bot, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "update_thread", bot.forum, thread_id="700")
    assert err.value.translation_key == "nothing_to_change"


# ---------------------------------------------------------------- Webhook
@pytest.fixture
async def hook(hass, discord):
    entry = await setup_entry(hass, webhook_entry())
    return SimpleNamespace(entry=entry, entity=entity_id(hass, entry, "webhook"))


async def test_webhook_device_and_entity(hass, hook):
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, hook.entry.entry_id), hook.entry.entry_id)
    assert device.name == "Hook"
    assert device.model == "Webhook"


async def test_webhook_send_message(hass, hook, discord):
    discord.post(HOOK, json={"id": "9", "channel_id": "555"})
    response = await call(hass, "send_message", hook.entity, message="Hallo", username="Fuchsbau")
    assert response == {hook.entity: {"message_id": "9", "channel_id": "555"}}
    [(_, url, data, headers)] = sent(discord, "POST", f"/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}")
    assert url.query["wait"] == "true"
    assert data["username"] == "Fuchsbau"
    assert "Authorization" not in headers


async def test_webhook_forum_post(hass, hook, discord, freezer):
    freezer.move_to("2026-10-26 12:00:00")
    discord.post(
        HOOK,
        side_effect=sequence(
            reply(200, {"id": "701", "channel_id": "700"}), reply(200, {"id": "702", "channel_id": "700"})
        ),
    )
    first = await call(hass, "forum_post", hook.entity, thread_name="Tag", message="a", tags="11", daily=True)
    second = await call(hass, "forum_post", hook.entity, thread_name="Tag", message="b", tags="11", daily=True)
    assert first[hook.entity] == {"thread_id": "700", "message_id": "701", "created": True}
    assert second[hook.entity] == {"thread_id": "700", "message_id": "702", "created": False}
    calls = sent(discord, "POST", f"/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}")
    assert calls[0][2]["thread_name"] == "Tag"
    assert calls[0][2]["applied_tags"] == ["11"]
    assert calls[1][1].query["thread_id"] == "700"


async def test_webhook_cannot_use_tag_names(hass, hook, discord):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "forum_post", hook.entity, thread_name="Tag", message="a", tags="Fuchs")
    assert err.value.translation_key == "webhook_tag_ids"


async def test_webhook_edit_and_delete(hass, hook, discord):
    discord.patch(f"{HOOK}/messages/55", json={"id": "55"})
    discord.delete(f"{HOOK}/messages/55", status=204)
    await call(hass, "edit_message", hook.entity, message_id="55", message="neu")
    await call(hass, "delete_message", hook.entity, message_id="55")
    assert len(sent(discord, "PATCH", "/messages/55")) == 1
    assert len(sent(discord, "DELETE", "/messages/55")) == 1


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("add_reaction", {"message_id": "55", "emoji": "✅"}),
        ("pin_message", {"message_id": "55"}),
        ("update_thread", {"thread_id": "7", "archived": True}),
        ("list_forum_tags", {}),
    ],
)
async def test_bot_only_actions_on_a_webhook(hass, hook, service, data):
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, service, hook.entity, **data)
    assert err.value.translation_key == "bot_only"
