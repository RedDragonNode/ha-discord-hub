"""Die Diagnose enthält weder Token noch Webhook-Adresse."""

from __future__ import annotations

import json

from homeassistant.components.diagnostics import REDACTED

from custom_components.discord_hub.diagnostics import async_get_config_entry_diagnostics

from .conftest import TOKEN, WEBHOOK_TOKEN, bot_entry, setup_entry, webhook_entry


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
