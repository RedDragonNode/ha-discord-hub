"""Die `notify`-Entity eines Kanals, einer Direktnachricht oder eines Webhooks und ihre Dienste."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_KIND,
    CONF_USER_ID,
    DOMAIN,
    FORUM_CHANNELS,
    KIND_BOT,
    SUBENTRY_CHANNEL,
    SUBENTRY_USER,
)

if TYPE_CHECKING:
    from . import DiscordHubConfigEntry
    from .runtime import DiscordRuntime

MODEL_CHANNEL = "Kanal"
MODEL_FORUM = "Forum-Kanal"
MODEL_DM = "Direktnachricht"
MODEL_WEBHOOK = "Webhook"


async def async_setup_entry(
    hass: HomeAssistant, entry: DiscordHubConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    if entry.data[CONF_KIND] != KIND_BOT:
        async_add_entities([DiscordNotify(runtime, f"{entry.entry_id}_webhook", _webhook_device(entry))])
        return
    for subentry in entry.subentries.values():
        if entity := _subentry_entity(runtime, entry, subentry):
            async_add_entities([entity], config_subentry_id=subentry.subentry_id)


def _webhook_device(entry: DiscordHubConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Discord",
        model=MODEL_WEBHOOK,
        entry_type=DeviceEntryType.SERVICE,
    )


def _subentry_entity(
    runtime: DiscordRuntime, entry: DiscordHubConfigEntry, subentry: ConfigSubentry
) -> DiscordNotify | None:
    if subentry.subentry_type == SUBENTRY_CHANNEL:
        channel_type = int(subentry.data.get(CONF_CHANNEL_TYPE, 0))
        model = MODEL_FORUM if channel_type in FORUM_CHANNELS else MODEL_CHANNEL
        return DiscordNotify(
            runtime,
            f"{entry.entry_id}_{subentry.data[CONF_CHANNEL_ID]}",
            _bot_device(entry, subentry, runtime, model),
            channel_id=str(subentry.data[CONF_CHANNEL_ID]),
            channel_type=channel_type,
        )
    if subentry.subentry_type == SUBENTRY_USER:
        return DiscordNotify(
            runtime,
            f"{entry.entry_id}_dm_{subentry.data[CONF_USER_ID]}",
            _bot_device(entry, subentry, runtime, MODEL_DM),
            user_id=str(subentry.data[CONF_USER_ID]),
        )
    return None


def _bot_device(
    entry: DiscordHubConfigEntry, subentry: ConfigSubentry, runtime: DiscordRuntime, model: str
) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{subentry.subentry_id}")},
        name=subentry.title,
        manufacturer="Discord",
        model=model,
        via_device_id=runtime.hub_device_id,
    )


class DiscordNotify(NotifyEntity):
    """Ein Ziel in Discord. Mit `notify.send_message` schickt sie Text, die Dienste von Discord Hub können mehr."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(
        self,
        runtime: DiscordRuntime,
        unique_id: str,
        device_info: DeviceInfo,
        *,
        channel_id: str | None = None,
        channel_type: int | None = None,
        user_id: str | None = None,
    ) -> None:
        self.runtime = runtime
        self._channel_id = channel_id
        self._channel_type = channel_type
        self._user_id = user_id
        self._attr_unique_id = unique_id
        self._attr_device_info = device_info

    async def _target(self) -> str | None:
        """Kanal, in den geschrieben wird. Bei einem Webhook gibt es keinen (er gehört zu seinem Kanal)."""
        if self._user_id:
            return await self.runtime.dm_channel(self._user_id)
        return self._channel_id

    def _require_forum(self) -> None:
        if self.runtime.is_bot and self._channel_type not in FORUM_CHANNELS:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_a_forum")

    # --------------------------------------------------------------- notify.send_message
    async def async_send_message(self, message: str, title: str | None = None) -> None:
        await self.async_discord_send_message(message=f"**{title}**\n{message}" if title else message)

    # --------------------------------------------------------------- Dienste von Discord Hub
    async def async_discord_send_message(self, **kwargs: Any) -> dict[str, str]:
        result = await self.runtime.send_message(await self._target(), **kwargs)
        self._async_record_notification()
        return result

    async def async_discord_forum_post(self, **kwargs: Any) -> dict[str, Any]:
        self._require_forum()
        result = await self.runtime.forum_post(await self._target(), **kwargs)
        self._async_record_notification()
        return result

    async def async_discord_edit_message(self, message_id: str, **kwargs: Any) -> dict[str, str]:
        return await self.runtime.edit_message(await self._target(), message_id, **kwargs)

    async def async_discord_delete_message(self, message_id: str, **kwargs: Any) -> None:
        await self.runtime.delete_message(await self._target(), message_id, **kwargs)

    async def async_discord_add_reaction(self, message_id: str, emoji: str, **kwargs: Any) -> None:
        await self.runtime.add_reaction(await self._target(), message_id, emoji, **kwargs)

    async def async_discord_pin_message(self, message_id: str, **kwargs: Any) -> None:
        await self.runtime.pin_message(await self._target(), message_id, True, **kwargs)

    async def async_discord_unpin_message(self, message_id: str, **kwargs: Any) -> None:
        await self.runtime.pin_message(await self._target(), message_id, False, **kwargs)

    async def async_discord_update_thread(self, thread_id: str, **kwargs: Any) -> dict[str, Any]:
        return await self.runtime.update_thread(thread_id, **kwargs)

    async def async_discord_list_forum_tags(self) -> dict[str, Any]:
        self._require_forum()
        if not self._channel_id:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="bot_only")
        return {"tags": await self.runtime.forum_tags(self._channel_id)}
