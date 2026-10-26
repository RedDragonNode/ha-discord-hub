"""Eine `event`-Entity je Slash-Befehl: Sie löst aus, wenn jemand den Befehl benutzt."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .commands import CommandConfig
from .const import CONF_KIND, DOMAIN, KIND_BOT

if TYPE_CHECKING:
    from . import DiscordHubConfigEntry
    from .listener import Listener

EVENT_USED = "used"


async def async_setup_entry(
    hass: HomeAssistant, entry: DiscordHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.data[CONF_KIND] != KIND_BOT:
        return
    runtime = entry.runtime_data
    listener = runtime.listener
    for subentry_id, command in listener.commands.items():
        async_add_entities(
            [DiscordCommandEvent(listener, command, runtime.hub_device_id)], config_subentry_id=subentry_id
        )


class DiscordCommandEvent(EventEntity):
    """Der Befehl `/name` auf einem Server. Optionen und Nutzer stehen in den Attributen des Ereignisses."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_event_types: ClassVar[list[str]] = [EVENT_USED]

    def __init__(self, listener: Listener, command: CommandConfig, hub_device_id: str | None) -> None:
        self._listener = listener
        self._subentry_id = command.subentry_id
        entry_id = listener.entry.entry_id
        self._attr_unique_id = f"{entry_id}_cmd_{command.guild_id}_{command.name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{command.subentry_id}")},
            name=f"/{command.name}",
            manufacturer="Discord",
            model="Befehl",
            via_device_id=hub_device_id,
        )

    async def async_added_to_hass(self) -> None:
        self._listener.event_entities[self._subentry_id] = self

    async def async_will_remove_from_hass(self) -> None:
        self._listener.event_entities.pop(self._subentry_id, None)

    @callback
    def async_use(self, data: dict[str, Any]) -> None:
        """Der Befehl wurde benutzt."""
        self._trigger_event(EVENT_USED, data)
        self.async_write_ha_state()
