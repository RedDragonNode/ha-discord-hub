"""Gemeinsame Fixtures: Einträge für Bot und Webhook und ein nachgestelltes Discord."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.discord_hub.const import (
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_GUILD_ID,
    CONF_KIND,
    CONF_NAME,
    CONF_TOKEN,
    CONF_USER_ID,
    CONF_WEBHOOK_URL,
    DOMAIN,
    KIND_BOT,
    KIND_WEBHOOK,
    SUBENTRY_CHANNEL,
    SUBENTRY_USER,
)

API = "https://discord.com/api/v10"
TOKEN = "bot-token-geheim-123"
WEBHOOK_ID = "777"
WEBHOOK_TOKEN = "webhook-token-geheim"
WEBHOOK_URL = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}"
BOT_ID = "42"
TEXT_ID = "100"
FORUM_ID = "200"
USER_ID = "300"

ME = {"id": BOT_ID, "username": "HA Waechter", "global_name": None, "bot": True}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Lässt Home Assistant die Integration aus `custom_components` laden."""


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiederholungen bei Rate-Limits warten in Tests nicht wirklich."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("custom_components.discord_hub.api._sleep", fake_sleep)
    monkeypatch.setattr("custom_components.discord_hub.api.WAITS", waits, raising=False)


def reply(status: int = 200, body: Any = None, headers: dict[str, str] | None = None) -> AiohttpClientMockResponse:
    """Eine Antwort von Discord für `side_effect`."""
    return AiohttpClientMockResponse(
        "post", None, status=status, text=None if body is None else json.dumps(body), headers=headers
    )


def sequence(*responses: AiohttpClientMockResponse):
    """Antworten der Reihe nach, die letzte bleibt."""
    queue = list(responses)

    async def side_effect(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return side_effect


def payload_of(data: Any) -> dict[str, Any]:
    """Der JSON-Teil einer gesendeten Anfrage (auch bei Dateien als Formular)."""
    if isinstance(data, dict):
        return data
    return json.loads(data._fields[0][2])


def bot_entry(**kwargs: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="HA Waechter",
        unique_id=BOT_ID,
        data={CONF_KIND: KIND_BOT, CONF_TOKEN: TOKEN},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_GUILD_ID: "1", CONF_CHANNEL_ID: TEXT_ID, CONF_CHANNEL_TYPE: 0, CONF_NAME: "allgemein"},
                subentry_type=SUBENTRY_CHANNEL,
                title="#allgemein",
                unique_id=TEXT_ID,
            ),
            ConfigSubentryData(
                data={CONF_GUILD_ID: "1", CONF_CHANNEL_ID: FORUM_ID, CONF_CHANNEL_TYPE: 15, CONF_NAME: "fuchs"},
                subentry_type=SUBENTRY_CHANNEL,
                title="fuchs",
                unique_id=FORUM_ID,
            ),
            ConfigSubentryData(
                data={CONF_USER_ID: USER_ID, CONF_NAME: "Stefan"},
                subentry_type=SUBENTRY_USER,
                title="Stefan",
                unique_id=f"dm_{USER_ID}",
            ),
        ],
        **kwargs,
    )


def webhook_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Hook",
        unique_id=WEBHOOK_ID,
        data={CONF_KIND: KIND_WEBHOOK, CONF_WEBHOOK_URL: WEBHOOK_URL},
    )


@pytest.fixture
def discord(aioclient_mock):
    """Ein Discord, das den Bot und den Webhook kennt."""
    aioclient_mock.get(f"{API}/users/@me", json=ME)
    aioclient_mock.get(f"{API}/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}", json={"id": WEBHOOK_ID, "channel_id": "555"})
    return aioclient_mock


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
