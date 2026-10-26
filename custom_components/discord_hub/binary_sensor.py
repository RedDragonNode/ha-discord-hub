"""Ob der Bot gerade mit Discord verbunden ist (nur wenn er auf Discord hört)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DiscordHubConfigEntry
from .const import CONF_KIND, DOMAIN, KIND_BOT
from .listener import Listener


async def async_setup_entry(
    hass: HomeAssistant, entry: DiscordHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.data[CONF_KIND] == KIND_BOT and entry.runtime_data.listener.enabled:
        async_add_entities([DiscordConnected(entry.runtime_data.listener)])


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

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self._listener.signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()
