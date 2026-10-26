"""Der REST-Client: Wiederholungen, Fehlerzuordnung und geheime Werte."""

from __future__ import annotations

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.discord_hub import api as discord_api
from custom_components.discord_hub.api import (
    Attachment,
    BotApi,
    DiscordAuthError,
    DiscordConnectionError,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    DiscordRateLimitError,
    DiscordTooLargeError,
    WebhookApi,
    parse_webhook_url,
)

from .conftest import API, TOKEN, WEBHOOK_ID, WEBHOOK_TOKEN, WEBHOOK_URL, payload_of, reply, sequence


def test_parse_webhook_url():
    assert parse_webhook_url(WEBHOOK_URL) == (WEBHOOK_ID, WEBHOOK_TOKEN)
    assert parse_webhook_url(f"https://discordapp.com/api/v10/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}?x=1") == (
        WEBHOOK_ID,
        WEBHOOK_TOKEN,
    )
    assert parse_webhook_url("https://example.com/api/webhooks/1/abc") is None
    assert parse_webhook_url("kein link") is None


async def test_bot_sends_token_and_user_agent(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", json={"id": "1"})
    await BotApi(async_get_clientsession(hass), TOKEN).get_me()
    headers = aioclient_mock.mock_calls[0][3]
    assert headers["Authorization"] == f"Bot {TOKEN}"
    assert headers["User-Agent"].startswith("DiscordBot (")


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, {"message": "401: Unauthorized"}, DiscordAuthError),
        (403, {"message": "Missing Access", "code": 50001}, DiscordForbiddenError),
        (404, {"message": "Unknown Channel"}, DiscordNotFoundError),
        (413, {"message": "too big"}, DiscordTooLargeError),
        (400, {"message": "Request entity too large", "code": 40005}, DiscordTooLargeError),
        (400, {"message": "Invalid Form Body", "code": 50035}, DiscordError),
    ],
)
async def test_errors_are_mapped(hass, aioclient_mock, status, body, error):
    aioclient_mock.get(f"{API}/channels/1", status=status, json=body)
    with pytest.raises(error) as err:
        await BotApi(async_get_clientsession(hass), TOKEN).get_channel("1")
    assert type(err.value) is error
    assert err.value.message == body["message"]


async def test_rate_limit_is_retried(hass, aioclient_mock):
    aioclient_mock.post(
        f"{API}/channels/1/messages",
        side_effect=sequence(
            reply(429, {"message": "slow down", "retry_after": 0.5}), reply(200, {"id": "9", "channel_id": "1"})
        ),
    )
    sent = await BotApi(async_get_clientsession(hass), TOKEN).create_message("1", {"content": "hi"})
    assert sent["id"] == "9"
    assert aioclient_mock.call_count == 2
    assert discord_api.WAITS == [0.5]


async def test_rate_limit_that_lasts_too_long_is_an_error(hass, aioclient_mock):
    aioclient_mock.post(f"{API}/channels/1/messages", status=429, json={"message": "slow down", "retry_after": 600})
    with pytest.raises(DiscordRateLimitError):
        await BotApi(async_get_clientsession(hass), TOKEN).create_message("1", {"content": "hi"})
    assert aioclient_mock.call_count == 1


async def test_rate_limit_gives_up_after_several_attempts(hass, aioclient_mock):
    aioclient_mock.post(f"{API}/channels/1/messages", status=429, json={"message": "slow", "retry_after": 1})
    with pytest.raises(DiscordRateLimitError):
        await BotApi(async_get_clientsession(hass), TOKEN).create_message("1", {"content": "hi"})
    assert aioclient_mock.call_count == discord_api.MAX_ATTEMPTS


async def test_server_error_is_retried_for_get_but_not_for_post(hass, aioclient_mock):
    aioclient_mock.get(
        f"{API}/channels/1", side_effect=sequence(reply(502, {"message": "bad gateway"}), reply(200, {"id": "1"}))
    )
    assert (await BotApi(async_get_clientsession(hass), TOKEN).get_channel("1"))["id"] == "1"
    assert aioclient_mock.call_count == 2

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API}/channels/1/messages", status=502, json={"message": "bad gateway"})
    with pytest.raises(DiscordError):
        await BotApi(async_get_clientsession(hass), TOKEN).create_message("1", {"content": "hi"})
    assert aioclient_mock.call_count == 1  # eine Nachricht könnte trotzdem angekommen sein


async def test_connection_error_hides_the_secret(hass, aioclient_mock):
    from aiohttp import ClientError

    aioclient_mock.get(f"{API}/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}", exc=ClientError(f"boom {WEBHOOK_TOKEN} boom"))
    with pytest.raises(DiscordConnectionError) as err:
        await WebhookApi(async_get_clientsession(hass), WEBHOOK_ID, WEBHOOK_TOKEN).get_info()
    assert WEBHOOK_TOKEN not in str(err.value)
    assert "***" in str(err.value)


async def test_files_are_sent_as_a_form(hass, aioclient_mock):
    aioclient_mock.post(f"{API}/channels/1/messages", json={"id": "9"})
    await BotApi(async_get_clientsession(hass), TOKEN).create_message(
        "1", {"content": "mit Bild"}, [Attachment("a.jpg", b"123", "image/jpeg")]
    )
    data = aioclient_mock.mock_calls[0][2]
    assert payload_of(data) == {"content": "mit Bild"}
    assert [field[0]["name"] for field in data._fields] == ["payload_json", "files[0]"]


async def test_webhook_executes_with_wait_and_thread(hass, aioclient_mock):
    aioclient_mock.post(f"{API}/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}", json={"id": "5", "channel_id": "77"})
    hook = WebhookApi(async_get_clientsession(hass), WEBHOOK_ID, WEBHOOK_TOKEN)
    await hook.execute({"content": "x"}, thread_id="77")
    url = aioclient_mock.mock_calls[0][1]
    assert url.query["wait"] == "true"
    assert url.query["thread_id"] == "77"


async def test_pin_falls_back_to_the_old_endpoint(hass, aioclient_mock):
    aioclient_mock.put(f"{API}/channels/1/messages/pins/2", status=404, json={"message": "Not Found"})
    aioclient_mock.put(f"{API}/channels/1/pins/2", status=204)
    await BotApi(async_get_clientsession(hass), TOKEN).pin_message("1", "2", True)
    assert aioclient_mock.call_count == 2
