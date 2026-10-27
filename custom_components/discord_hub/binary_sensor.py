"""Ob der Bot mit Discord verbunden ist und ob ein beobachtetes Mitglied in einem Sprachkanal sitzt."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DiscordHubConfigEntry
from .const import CONF_GUILD_ID, CONF_KIND, CONF_USER_ID, DOMAIN, KIND_BOT, SUBENTRY_MEMBER
from .entity import MODEL_MEMBER, GatewayEntity
from .listener import Listener


async def async_setup_entry(
    hass: HomeAssistant, entry: DiscordHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.data[CONF_KIND] != KIND_BOT:
        return
    listener: Listener = entry.runtime_data.listener
    if listener.enabled:
        async_add_entities([DiscordConnected(listener)])
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_MEMBER:
            async_add_entities([DiscordMemberInVoice(listener, subentry)], config_subentry_id=subentry.subentry_id)


class DiscordConnected(BinarySensorEntity):
    """„Verbunden“: Das Gateway von Discord ist offen, Befehle und Buttons kommen an."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, listener: Listener) -> None:
        self._listener = listener
        self._attr_unique_id = f"{listener.entry.entry_id}_connected"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, listener.entry.entry_id)})

    @property
    def is_on(self) -> bool:
        return self._listener.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Wie oft die Verbindung neu aufgebaut wurde und warum zuletzt (Discord verlangt das regelmäßig)."""
        gateway = self._listener.gateway
        if gateway is None:
            return {}
        stats = gateway.stats
        return {
            "sessions": stats.sessions,
            "resumes": stats.resumes,
            "reconnects": stats.reconnects,
            "last_reason": stats.last_reason,
            "last_connected": stats.last_connected.isoformat() if stats.last_connected else None,
            "last_disconnected": stats.last_disconnected.isoformat() if stats.last_disconnected else None,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self._listener.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()


class DiscordMemberInVoice(GatewayEntity, BinarySensorEntity):
    """Ob ein beobachtetes Mitglied in einem Sprachkanal ist, und in welchem."""

    _attr_translation_key = "member_in_voice"
    _attr_icon = "mdi:microphone"

    def __init__(self, listener: Listener, subentry: ConfigSubentry) -> None:
        guild_id = str(subentry.data[CONF_GUILD_ID])
        super().__init__(listener, subentry, guild_id, MODEL_MEMBER)
        self._user_id = str(subentry.data[CONF_USER_ID])
        self._attr_unique_id = f"{listener.entry.entry_id}_member_{guild_id}_{self._user_id}_voice"

    @property
    def is_on(self) -> bool:
        return self._listener.monitor.voice_of(self._guild_id, self._user_id) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        found = self._listener.monitor.voice_of(self._guild_id, self._user_id)
        if found is None:
            return {}
        voice, channel = found
        return {"channel": channel, "channel_id": voice.channel_id}
