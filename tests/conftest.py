"""Gemeinsame Fixtures: Einträge für Bot und Webhook und ein nachgestelltes Discord."""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

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
    SUBENTRY_COMMAND,
    SUBENTRY_MEMBER,
    SUBENTRY_NOTICE,
    SUBENTRY_SERVER,
    SUBENTRY_USER,
)
from custom_components.discord_hub.gateway import GatewayStats

API = "https://discord.com/api/v10"
TOKEN = "bot-token-geheim-123"
WEBHOOK_ID = "777"
WEBHOOK_TOKEN = "webhook-token-geheim"
WEBHOOK_URL = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}"
BOT_ID = "42"
TEXT_ID = "100"
FORUM_ID = "200"
USER_ID = "300"
TEXT_SUB = "sub-text"  # die Untereinträge von Kanal, Forum und Direktnachricht, Ziele für Meldungen
FORUM_SUB = "sub-forum"
USER_SUB = "sub-user"

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


class FakeGateway:
    """Ersatz für das Gateway: verbindet nicht, merkt sich nur, wie es gebaut wurde."""

    instances: ClassVar[list[FakeGateway]] = []

    def __init__(self, session, token, intents, on_dispatch, *, on_status=None, on_fatal=None) -> None:
        self.token = token
        self.intents = intents
        self.on_dispatch = on_dispatch
        self.on_status = on_status
        self.on_fatal = on_fatal
        self.connected = False
        self.latency = None
        self.stats = GatewayStats()
        self.closed = False
        FakeGateway.instances.append(self)

    async def run(self) -> None:
        await asyncio.sleep(3600)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _fake_gateway(monkeypatch: pytest.MonkeyPatch) -> type[FakeGateway]:
    """Kein Test baut eine echte Verbindung auf. Die Wartezeit auf `respond` ist lang, solange kein Test sie kürzt."""
    FakeGateway.instances = []
    monkeypatch.setattr("custom_components.discord_hub.listener.GatewayClient", FakeGateway)
    monkeypatch.setattr("custom_components.discord_hub.listener.RESPOND_GRACE_SECONDS", 3600)
    return FakeGateway


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


def bot_entry(extra_subentries: list[ConfigSubentryData] | None = None, **kwargs: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="HA Waechter",
        unique_id=BOT_ID,
        data={CONF_KIND: KIND_BOT, CONF_TOKEN: TOKEN},
        subentries_data=[
            ConfigSubentryData(
                data={CONF_GUILD_ID: "1", CONF_CHANNEL_ID: TEXT_ID, CONF_CHANNEL_TYPE: 0, CONF_NAME: "allgemein"},
                subentry_type=SUBENTRY_CHANNEL,
                subentry_id=TEXT_SUB,
                title="#allgemein",
                unique_id=TEXT_ID,
            ),
            ConfigSubentryData(
                data={CONF_GUILD_ID: "1", CONF_CHANNEL_ID: FORUM_ID, CONF_CHANNEL_TYPE: 15, CONF_NAME: "fuchs"},
                subentry_type=SUBENTRY_CHANNEL,
                subentry_id=FORUM_SUB,
                title="fuchs",
                unique_id=FORUM_ID,
            ),
            ConfigSubentryData(
                data={CONF_USER_ID: USER_ID, CONF_NAME: "Stefan"},
                subentry_type=SUBENTRY_USER,
                subentry_id=USER_SUB,
                title="Stefan",
                unique_id=f"dm_{USER_ID}",
            ),
            *(extra_subentries or []),
        ],
        **kwargs,
    )


def command_subentry(**changes: Any) -> ConfigSubentryData:
    """Der Befehl /status auf Server 1, den Nutzer 555 benutzen darf."""
    data: dict[str, Any] = {
        CONF_GUILD_ID: "1",
        CONF_NAME: "status",
        "description": "Zeigt den Status",
        "options": [],
        "reply": "",
        "ephemeral": False,
        "everyone": False,
        "users": ["555"],
        "roles": [],
        **changes,
    }
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_COMMAND, title=f"/{data[CONF_NAME]}", unique_id=f"cmd_1_{data[CONF_NAME]}"
    )


def server_subentry(guild_id: str = "1", name: str = "Fuchsbau") -> ConfigSubentryData:
    """Der Server „Fuchsbau“, dessen Zahlen und Sprachkanäle beobachtet werden."""
    return ConfigSubentryData(
        data={CONF_GUILD_ID: guild_id, CONF_NAME: name},
        subentry_type=SUBENTRY_SERVER,
        title=name,
        unique_id=f"server_{guild_id}",
    )


def member_subentry(user_id: str = "555", name: str = "Stefan", guild_id: str = "1") -> ConfigSubentryData:
    """Das Mitglied Stefan auf Server 1."""
    return ConfigSubentryData(
        data={CONF_GUILD_ID: guild_id, CONF_USER_ID: user_id, CONF_NAME: name},
        subentry_type=SUBENTRY_MEMBER,
        title=name,
        unique_id=f"member_{guild_id}_{user_id}",
    )


def notice_subentry(template: str = "custom_event", target: str = TEXT_SUB, **changes: Any) -> ConfigSubentryData:
    """Eine Meldung mit den Vorgaben der Vorlage. `changes` überschreibt Felder."""
    data: dict[str, Any] = {
        "template": template,
        "target": target,
        "title": "",
        "message": "",
        "embed": True,
        "snapshot": False,
        "camera": "",
        "cooldown": 0,
        **changes,
    }
    return ConfigSubentryData(
        data=data,
        subentry_type=SUBENTRY_NOTICE,
        subentry_id=f"notice-{template}-{target}",
        title=f"Meldung {template}",
    )


def listening_entry(commands: list[ConfigSubentryData] | None = None, **options: Any) -> MockConfigEntry:
    """Ein Bot, der auf Discord hört, mit den angegebenen Befehlen."""
    return bot_entry(commands, options={"listen": True, **options})


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
