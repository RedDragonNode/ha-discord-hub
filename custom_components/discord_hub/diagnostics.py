"""Diagnose-Download (ohne Token und Webhook-Adresse)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DiscordHubConfigEntry
from .const import CONF_TOKEN, CONF_WEBHOOK_URL
from .listener import Listener

TO_REDACT = {CONF_TOKEN, CONF_WEBHOOK_URL}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: DiscordHubConfigEntry) -> dict[str, Any]:
    runtime = entry.runtime_data
    listener = runtime.listener
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "is_bot": runtime.is_bot,
        "subentries": [
            {"type": s.subentry_type, "title": s.title, "data": dict(s.data)} for s in entry.subentries.values()
        ],
        "daily_threads": runtime.daily_thread_count,
        "gateway": _gateway(listener) if listener else None,
    }


def _gateway(listener: Listener) -> dict[str, Any]:
    """Verbindung und Zählwerte des Zustands, den das Gateway liefert (keine Namen, nur Anzahlen)."""
    stats = listener.gateway.stats if listener.gateway else None
    return {
        "enabled": listener.enabled,
        "connected": listener.connected,
        "live": listener.live,
        "stats": {
            key: (value.isoformat() if isinstance(value, datetime) else value) for key, value in vars(stats).items()
        }
        if stats
        else None,
        "servers": {
            guild_id: {
                "channels": len(guild.channels),
                "in_voice": len(guild.voice),
                "presences": len(guild.presences),
            }
            for guild_id, guild in listener.monitor.guilds.items()
        },
    }
