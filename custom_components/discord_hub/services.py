"""Dienste von Discord Hub. Sie gehören den `notify`-Entities des Kanals oder Webhooks, den man als Ziel wählt."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.notify import DOMAIN as NOTIFY_DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .const import (
    ATTR_ALLOW_EVERYONE,
    ATTR_ARCHIVED,
    ATTR_AVATAR_URL,
    ATTR_BUTTONS,
    ATTR_DAILY,
    ATTR_EMBEDS,
    ATTR_EMOJI,
    ATTR_EPHEMERAL,
    ATTR_FILES,
    ATTR_INTERACTION_ID,
    ATTR_KEY,
    ATTR_LOCKED,
    ATTR_MESSAGE,
    ATTR_MESSAGE_ID,
    ATTR_NAME,
    ATTR_REPLY_TO,
    ATTR_TAGS,
    ATTR_THREAD_ID,
    ATTR_THREAD_NAME,
    ATTR_UPDATE,
    ATTR_USERNAME,
    DOMAIN,
    SERVICE_ADD_REACTION,
    SERVICE_DELETE_MESSAGE,
    SERVICE_EDIT_MESSAGE,
    SERVICE_FORUM_POST,
    SERVICE_LIST_FORUM_TAGS,
    SERVICE_PIN_MESSAGE,
    SERVICE_RESPOND,
    SERVICE_SEND_MESSAGE,
    SERVICE_UNPIN_MESSAGE,
    SERVICE_UPDATE_THREAD,
)
from .messages import BUTTON_SCHEMA, EMBED_SCHEMA

# Dateien: je Eintrag ein Text (Pfad, Adresse, Kamera-Entity, Medienquelle) oder ein Objekt; ein Eintrag allein genügt
_FILES = vol.All(cv.ensure_list, [vol.Any(cv.string, dict)])
_EMBEDS = vol.All(cv.ensure_list, [EMBED_SCHEMA])
_BUTTONS = vol.All(cv.ensure_list, [BUTTON_SCHEMA])
_ID = cv.string

_BODY = {
    vol.Optional(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_EMBEDS): _EMBEDS,
    vol.Optional(ATTR_FILES): _FILES,
    vol.Optional(ATTR_ALLOW_EVERYONE, default=False): cv.boolean,
    vol.Optional(ATTR_USERNAME): cv.string,
    vol.Optional(ATTR_AVATAR_URL): cv.string,
}

_SCHEMAS: dict[str, dict] = {
    SERVICE_SEND_MESSAGE: {
        **_BODY,
        vol.Optional(ATTR_REPLY_TO): _ID,
        vol.Optional(ATTR_THREAD_ID): _ID,
        vol.Optional(ATTR_BUTTONS): _BUTTONS,
    },
    SERVICE_FORUM_POST: {
        **_BODY,
        vol.Required(ATTR_THREAD_NAME): cv.string,
        vol.Optional(ATTR_TAGS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_DAILY, default=False): cv.boolean,
        vol.Optional(ATTR_KEY, default="default"): cv.string,
    },
    SERVICE_EDIT_MESSAGE: {
        vol.Required(ATTR_MESSAGE_ID): _ID,
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_EMBEDS): vol.All(cv.ensure_list, [EMBED_SCHEMA]),
        vol.Optional(ATTR_BUTTONS): _BUTTONS,
        vol.Optional(ATTR_THREAD_ID): _ID,
    },
    SERVICE_DELETE_MESSAGE: {vol.Required(ATTR_MESSAGE_ID): _ID, vol.Optional(ATTR_THREAD_ID): _ID},
    SERVICE_ADD_REACTION: {
        vol.Required(ATTR_MESSAGE_ID): _ID,
        vol.Required(ATTR_EMOJI): cv.string,
        vol.Optional(ATTR_THREAD_ID): _ID,
    },
    SERVICE_PIN_MESSAGE: {vol.Required(ATTR_MESSAGE_ID): _ID, vol.Optional(ATTR_THREAD_ID): _ID},
    SERVICE_UNPIN_MESSAGE: {vol.Required(ATTR_MESSAGE_ID): _ID, vol.Optional(ATTR_THREAD_ID): _ID},
    SERVICE_UPDATE_THREAD: {
        vol.Required(ATTR_THREAD_ID): _ID,
        vol.Optional(ATTR_ARCHIVED): cv.boolean,
        vol.Optional(ATTR_LOCKED): cv.boolean,
        vol.Optional(ATTR_NAME): cv.string,
    },
    SERVICE_LIST_FORUM_TAGS: {},
}

# Dienste, die etwas zurückgeben (Message-ID, Thread-ID, Tags …)
_RESPONDING = {
    SERVICE_SEND_MESSAGE,
    SERVICE_FORUM_POST,
    SERVICE_EDIT_MESSAGE,
    SERVICE_UPDATE_THREAD,
    SERVICE_LIST_FORUM_TAGS,
}


_RESPOND_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_INTERACTION_ID): _ID,
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_EMBEDS): _EMBEDS,
        vol.Optional(ATTR_BUTTONS): _BUTTONS,
        vol.Optional(ATTR_EPHEMERAL): cv.boolean,
        vol.Optional(ATTR_UPDATE, default=False): cv.boolean,
    }
)


def async_register_services(hass: HomeAssistant) -> None:
    async def respond(call: ServiceCall) -> dict[str, str]:
        """Einen Befehl oder Button beantworten. Die Interaktion gehört einem der Bots, der sie bekommen hat."""
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            listener = entry.runtime_data.listener
            if listener and (interaction := listener.get_interaction(call.data[ATTR_INTERACTION_ID])):
                return await listener.async_respond(
                    interaction,
                    message=call.data.get(ATTR_MESSAGE),
                    embeds=call.data.get(ATTR_EMBEDS),
                    buttons=call.data.get(ATTR_BUTTONS),
                    ephemeral=call.data.get(ATTR_EPHEMERAL),
                    update=call.data[ATTR_UPDATE],
                )
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="unknown_interaction")

    hass.services.async_register(
        DOMAIN, SERVICE_RESPOND, respond, schema=_RESPOND_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    for name, schema in _SCHEMAS.items():
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=NOTIFY_DOMAIN,
            func=f"async_discord_{name}",
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL if name in _RESPONDING else SupportsResponse.NONE,
        )
