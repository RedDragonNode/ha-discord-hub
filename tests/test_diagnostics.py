"""Die Diagnose enthält weder Token noch Webhook-Adresse."""

from __future__ import annotations

import json

from homeassistant.components.diagnostics import REDACTED

from custom_components.discord_hub.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN, WEBHOOK_TOKEN, bot_entry, member_subentry, server_subentry, setup_entry, webhook_entry
from .test_sensors import guild_create, start


async def test_bot_diagnostics(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["entry"]["api_token"] == REDACTED
    assert data["is_bot"] is True
    assert [s["title"] for s in data["subentries"]] == ["#allgemein", "fuchs", "Stefan"]
    assert TOKEN not in json.dumps(data)


async def test_webhook_diagnostics(hass, discord):
    entry = await setup_entry(hass, webhook_entry())
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["entry"]["webhook_url"] == REDACTED
    assert data["is_bot"] is False
    assert WEBHOOK_TOKEN not in json.dumps(data)


async def test_gateway_diagnostics_count_but_do_not_name(hass, discord):
    bot = await start(hass, discord, bot_entry([server_subentry(), member_subentry()]))
    bot.listener._on_status(True)
    await bot.listener._dispatch("GUILD_CREATE", guild_create())
    data = await async_get_config_entry_diagnostics(hass, bot.entry)
    gateway = data["gateway"]
    assert gateway["enabled"] is True
    assert gateway["live"] is True
    assert gateway["servers"] == {"1": {"channels": 2, "in_voice": 1, "presences": 1}}
    assert gateway["stats"]["reconnects"] == 0
    assert "Lobby" not in json.dumps(data)
    assert TOKEN not in json.dumps(data)
