"""Discord Hub: Nachrichten, Forum-Posts und mehr für Discord, über einen Bot oder einen Webhook."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BotApi, DiscordAuthError, DiscordError, DiscordNotFoundError, WebhookApi, parse_webhook_url
from .const import CONF_KIND, CONF_TOKEN, CONF_WEBHOOK_URL, DOMAIN, KIND_BOT
from .listener import Listener
from .runtime import DiscordRuntime, threads_store
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.NOTIFY, Platform.EVENT, Platform.BINARY_SENSOR, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type DiscordHubConfigEntry = ConfigEntry[DiscordRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DiscordHubConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api: BotApi | WebhookApi
    if entry.data[CONF_KIND] == KIND_BOT:
        api = BotApi(session, entry.data[CONF_TOKEN])
    else:
        parsed = parse_webhook_url(entry.data[CONF_WEBHOOK_URL])
        if parsed is None:
            raise ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_webhook")
        api = WebhookApi(session, *parsed)
    try:
        if isinstance(api, BotApi):
            await api.get_me()
        else:
            await api.get_info()
    except DiscordAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed", translation_placeholders={"details": err.message}
        ) from err
    except DiscordNotFoundError as err:  # es gibt nur den Webhook, der gelöscht worden sein kann
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="not_found", translation_placeholders={"details": err.message}
        ) from err
    except DiscordError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"details": err.message},
        ) from err

    runtime = DiscordRuntime(hass, entry, api)
    await runtime.async_load()
    if isinstance(api, BotApi):
        runtime.listener = Listener(runtime)
        runtime.hub_device_id = (
            dr.async_get(hass)
            .async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, entry.entry_id)},
                name=entry.title,
                manufacturer="Discord",
                model="Bot",
                entry_type=dr.DeviceEntryType.SERVICE,
            )
            .id
        )
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if runtime.listener:
        # Befehle bei Discord abgleichen und auf Discord hören, ohne die Einrichtung aufzuhalten
        entry.async_create_background_task(hass, runtime.listener.async_start(), f"{DOMAIN} listener")
    # Kanäle kommen und gehen als Untereinträge, Zugangsdaten wechseln: in beiden Fällen neu laden
    entry.async_on_unload(entry.add_update_listener(_reload_on_change))
    return True


async def _reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: DiscordHubConfigEntry) -> bool:
    if entry.runtime_data.listener:
        await entry.runtime_data.listener.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Beim Löschen auch die gemerkten Tages-Threads entfernen."""
    await threads_store(hass, entry.entry_id).async_remove()
