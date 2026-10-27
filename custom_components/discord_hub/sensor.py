"""Sensoren für Server (Mitglieder, Online, Sprachkanäle) und beobachtete Mitglieder (Status, Aktivität)."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from . import DiscordHubConfigEntry
from .api import BotApi, DiscordAuthError, DiscordError
from .const import (
    CONF_GUILD_ID,
    CONF_KIND,
    CONF_USER_ID,
    COUNTS_REFRESH_SECONDS,
    DOMAIN,
    KIND_BOT,
    SUBENTRY_MEMBER,
    SUBENTRY_SERVER,
)
from .entity import MODEL_MEMBER, MODEL_SERVER, GatewayEntity, subentry_device
from .listener import Listener
from .monitor import STATUSES, describe_activity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: DiscordHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    if entry.data[CONF_KIND] != KIND_BOT:
        return
    runtime = entry.runtime_data
    listener: Listener = runtime.listener
    for subentry in entry.subentries.values():
        guild_id = str(subentry.data.get(CONF_GUILD_ID, ""))
        if subentry.subentry_type == SUBENTRY_SERVER:
            coordinator = GuildCountsCoordinator(hass, entry, runtime.api, guild_id)
            await (
                coordinator.async_refresh()
            )  # schlägt es fehl, sind die Zahlen „nicht verfügbar“, der Eintrag lädt trotzdem
            async_add_entities(
                [
                    GuildCount(
                        coordinator, listener, subentry, "members", "approximate_member_count", "mdi:account-group"
                    ),
                    GuildCount(
                        coordinator, listener, subentry, "online", "approximate_presence_count", "mdi:account-check"
                    ),
                    VoiceUsers(listener, subentry, guild_id),
                ],
                config_subentry_id=subentry.subentry_id,
            )
        elif subentry.subentry_type == SUBENTRY_MEMBER and listener.track_presence:
            user_id = str(subentry.data[CONF_USER_ID])
            async_add_entities(
                [
                    MemberStatus(listener, subentry, guild_id, user_id),
                    MemberActivity(listener, subentry, guild_id, user_id),
                ],
                config_subentry_id=subentry.subentry_id,
            )


class GuildCountsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fragt die ungefähren Zahlen eines Servers bei Discord ab. Das geht ohne privilegierte Intents."""

    def __init__(self, hass: HomeAssistant, entry: DiscordHubConfigEntry, api: BotApi, guild_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {guild_id}",
            update_interval=timedelta(seconds=COUNTS_REFRESH_SECONDS),
        )
        self._api = api
        self._guild_id = guild_id

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._api.get_guild_counts(self._guild_id)
        except DiscordAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"details": err.message},
            ) from err
        except DiscordError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"details": err.message},
            ) from err


class GuildCount(CoordinatorEntity[GuildCountsCoordinator], SensorEntity):
    """Mitglieder oder Mitglieder online eines Servers (Discord liefert ungefähre Zahlen)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: GuildCountsCoordinator,
        listener: Listener,
        subentry: ConfigSubentry,
        key: str,
        field: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._field = field
        self._attr_translation_key = f"server_{key}"
        self._attr_icon = icon
        self._attr_unique_id = f"{listener.entry.entry_id}_server_{subentry.data[CONF_GUILD_ID]}_{key}"
        self._attr_device_info = subentry_device(listener, subentry, MODEL_SERVER)

    @property
    def native_value(self) -> int | None:
        value = (self.coordinator.data or {}).get(self._field)
        return int(value) if value is not None else None


class VoiceUsers(GatewayEntity, SensorEntity):
    """Wie viele Nutzer in Sprachkanälen sind. Die Attribute zeigen, wer in welchem Kanal ist."""

    _attr_translation_key = "voice_users"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:microphone"

    def __init__(self, listener: Listener, subentry: ConfigSubentry, guild_id: str) -> None:
        super().__init__(listener, subentry, guild_id, MODEL_SERVER)
        self._attr_unique_id = f"{listener.entry.entry_id}_server_{guild_id}_voice"

    @property
    def native_value(self) -> int:
        return self._listener.monitor.voice_count(self._guild_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"channels": self._listener.monitor.voice_channels(self._guild_id, self._listener.member_names)}


class MemberStatus(GatewayEntity, SensorEntity):
    """Der Status eines Mitglieds: online, abwesend, bitte nicht stören oder offline."""

    _attr_translation_key = "member_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    def __init__(self, listener: Listener, subentry: ConfigSubentry, guild_id: str, user_id: str) -> None:
        super().__init__(listener, subentry, guild_id, MODEL_MEMBER)
        self._user_id = user_id
        self._attr_unique_id = f"{listener.entry.entry_id}_member_{guild_id}_{user_id}_status"

    @property
    def native_value(self) -> str:
        return self._listener.monitor.presence_of(self._guild_id, self._user_id).status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        platforms = self._listener.monitor.presence_of(self._guild_id, self._user_id).platforms
        return {"platforms": platforms} if platforms else {}


class MemberActivity(GatewayEntity, SensorEntity):
    """Was ein Mitglied gerade tut: das Spiel, die Musik oder sein eigener Status-Text."""

    _attr_translation_key = "member_activity"
    _attr_icon = "mdi:controller"

    def __init__(self, listener: Listener, subentry: ConfigSubentry, guild_id: str, user_id: str) -> None:
        super().__init__(listener, subentry, guild_id, MODEL_MEMBER)
        self._user_id = user_id
        self._attr_unique_id = f"{listener.entry.entry_id}_member_{guild_id}_{user_id}_activity"

    def _described(self) -> tuple[str | None, dict[str, Any]]:
        return describe_activity(self._listener.monitor.presence_of(self._guild_id, self._user_id))

    @property
    def native_value(self) -> str | None:
        return self._described()[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._described()[1]
