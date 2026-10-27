"""Gemeinsame Grundlage der Entities, deren Wert aus dem Gateway kommt (Server, Mitglieder, Sprachkanäle)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .listener import Listener

MODEL_SERVER = "Server"
MODEL_MEMBER = "Mitglied"


def subentry_device(listener: Listener, subentry: ConfigSubentry, model: str) -> DeviceInfo:
    """Das Gerät eines Servers oder Mitglieds, unter dem Gerät des Bots."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{listener.entry.entry_id}_{subentry.subentry_id}")},
        name=subentry.title,
        manufacturer="Discord",
        model=model,
        via_device_id=listener.runtime.hub_device_id,
    )


class GatewayEntity(Entity):
    """Verfügbar, solange die Werte des Gateways aktuell sind und der Server gemeldet wurde."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, listener: Listener, subentry: ConfigSubentry, guild_id: str, model: str) -> None:
        self._listener = listener
        self._guild_id = guild_id
        self._attr_device_info = subentry_device(listener, subentry, model)

    @property
    def available(self) -> bool:
        return self._listener.live and self._listener.monitor.synced(self._guild_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self._listener.state_signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()
