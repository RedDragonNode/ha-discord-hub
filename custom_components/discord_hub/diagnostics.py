"""Diagnose-Download (ohne Token und Webhook-Adresse)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DiscordHubConfigEntry
from .const import CONF_TOKEN, CONF_WEBHOOK_URL

TO_REDACT = {CONF_TOKEN, CONF_WEBHOOK_URL}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: DiscordHubConfigEntry) -> dict[str, Any]:
    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "is_bot": runtime.is_bot,
        "subentries": [
            {"type": s.subentry_type, "title": s.title, "data": dict(s.data)} for s in entry.subentries.values()
        ],
        "daily_threads": runtime.daily_thread_count,
    }
