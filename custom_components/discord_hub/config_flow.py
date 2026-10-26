"""Config-Flow (Bot oder Webhook) und Untereinträge eines Bots (Kanäle, Direktnachrichten)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BotApi,
    DiscordAuthError,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    WebhookApi,
    parse_webhook_url,
)
from .const import (
    CHANNEL_ANNOUNCEMENT,
    CHANNEL_CATEGORY,
    CHANNEL_FORUM,
    CHANNEL_MEDIA,
    CHANNEL_VOICE,
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_GUILD_ID,
    CONF_KIND,
    CONF_NAME,
    CONF_TOKEN,
    CONF_USER_ID,
    CONF_WEBHOOK_URL,
    DOMAIN,
    KIND_BOT,
    KIND_WEBHOOK,
    SELECTABLE_CHANNELS,
    SUBENTRY_CHANNEL,
    SUBENTRY_USER,
)

_TEXT = selector.TextSelector()
_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))

BOT_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): _SECRET})
WEBHOOK_SCHEMA = vol.Schema({vol.Required(CONF_NAME): _TEXT, vol.Required(CONF_WEBHOOK_URL): _SECRET})
USER_SCHEMA = vol.Schema({vol.Required(CONF_NAME): _TEXT, vol.Required(CONF_USER_ID): _TEXT})


def _bot_title(me: Mapping[str, Any]) -> str:
    return str(me.get("global_name") or me["username"])


class DiscordHubConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einen Bot (Token) oder einen Webhook (Adresse) hinzufügen."""

    VERSION = 1

    # ------------------------------------------------------------------ Neu
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=[KIND_BOT, KIND_WEBHOOK])

    async def async_step_bot(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                me = await BotApi(async_get_clientsession(self.hass), token).get_me()
            except DiscordAuthError:
                errors["base"] = "invalid_auth"
            except DiscordError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(str(me["id"]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=_bot_title(me), data={CONF_KIND: KIND_BOT, CONF_TOKEN: token})
        return self.async_show_form(step_id="bot", data_schema=BOT_SCHEMA, errors=errors)

    async def async_step_webhook(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_WEBHOOK_URL].strip()
            parsed = parse_webhook_url(url)
            if parsed is None:
                errors["base"] = "invalid_webhook"
            else:
                error = await self._check_webhook(parsed)
                if error:
                    errors["base"] = error
                else:
                    await self.async_set_unique_id(parsed[0])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input[CONF_NAME].strip(),
                        data={CONF_KIND: KIND_WEBHOOK, CONF_WEBHOOK_URL: _canonical_webhook(parsed)},
                    )
        return self.async_show_form(
            step_id="webhook",
            data_schema=self.add_suggested_values_to_schema(WEBHOOK_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def _check_webhook(self, parsed: tuple[str, str]) -> str | None:
        """Fehlerschlüssel, wenn der Webhook nicht antwortet, sonst None."""
        try:
            await WebhookApi(async_get_clientsession(self.hass), *parsed).get_info()
        except (DiscordAuthError, DiscordNotFoundError):
            return "invalid_webhook"
        except DiscordError:
            return "cannot_connect"
        return None

    # ------------------------------------------------------------------ Zugangsdaten erneuern
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._credentials_step("reauth_confirm", self._get_reauth_entry(), user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._credentials_step("reconfigure", self._get_reconfigure_entry(), user_input)

    async def _credentials_step(
        self, step_id: str, entry: ConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Neuer Token oder neue Webhook-Adresse. Sie muss zum selben Bot beziehungsweise Webhook gehören."""
        is_bot = entry.data[CONF_KIND] == KIND_BOT
        field = CONF_TOKEN if is_bot else CONF_WEBHOOK_URL
        errors: dict[str, str] = {}
        if user_input is not None:
            value = user_input[field].strip()
            if is_bot:
                try:
                    me = await BotApi(async_get_clientsession(self.hass), value).get_me()
                except DiscordAuthError:
                    errors["base"] = "invalid_auth"
                except DiscordError:
                    errors["base"] = "cannot_connect"
                else:
                    if str(me["id"]) != entry.unique_id:
                        return self.async_abort(reason="wrong_account")
                    return self.async_update_and_abort(entry, data_updates={CONF_TOKEN: value})
            else:
                parsed = parse_webhook_url(value)
                if parsed is None:
                    errors["base"] = "invalid_webhook"
                elif error := await self._check_webhook(parsed):
                    errors["base"] = error
                elif parsed[0] != entry.unique_id:
                    return self.async_abort(reason="wrong_account")
                else:
                    return self.async_update_and_abort(
                        entry, data_updates={CONF_WEBHOOK_URL: _canonical_webhook(parsed)}
                    )
        return self.async_show_form(
            step_id=step_id, data_schema=vol.Schema({vol.Required(field): _SECRET}), errors=errors
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        if config_entry.data.get(CONF_KIND) != KIND_BOT:
            return {}
        return {SUBENTRY_CHANNEL: ChannelSubentryFlow, SUBENTRY_USER: UserSubentryFlow}


def _canonical_webhook(parsed: tuple[str, str]) -> str:
    return f"https://discord.com/api/webhooks/{parsed[0]}/{parsed[1]}"


# ---------------------------------------------------------------------- Kanäle
class _BotSubentryFlow(ConfigSubentryFlow):
    def _api(self) -> BotApi:
        return BotApi(async_get_clientsession(self.hass), self._get_entry().data[CONF_TOKEN])


def _channel_label(channel: Mapping[str, Any]) -> str:
    """Anzeige in der Auswahl: # Text, 📢 Ankündigungen, 🔊 Sprache, Name (Forum) und Name (Media)."""
    name = channel["name"]
    return {
        CHANNEL_ANNOUNCEMENT: f"📢 {name}",
        CHANNEL_VOICE: f"🔊 {name}",
        CHANNEL_FORUM: f"{name} (Forum)",
        CHANNEL_MEDIA: f"{name} (Media)",
    }.get(channel["type"], f"#{name}")


class ChannelSubentryFlow(_BotSubentryFlow):
    """Einen Kanal des Servers hinzufügen (Text, Ankündigungen, Sprache, Forum, Media)."""

    _guild: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        try:
            guilds = await self._api().get_guilds()
        except DiscordAuthError:
            return self.async_abort(reason="invalid_auth")
        except DiscordError:
            return self.async_abort(reason="cannot_connect")
        if not guilds:
            return self.async_abort(reason="no_guilds")
        if len(guilds) == 1:
            self._guild = guilds[0]
            return await self.async_step_channel()
        if user_input is not None:
            self._guild = next(g for g in guilds if str(g["id"]) == user_input[CONF_GUILD_ID])
            return await self.async_step_channel()
        options = [selector.SelectOptionDict(value=str(g["id"]), label=g["name"]) for g in guilds]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GUILD_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
        )

    async def async_step_channel(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        assert self._guild is not None
        guild_id = str(self._guild["id"])
        try:
            channels = await self._api().get_guild_channels(guild_id)
        except DiscordForbiddenError:
            return self.async_abort(reason="forbidden")
        except DiscordError:
            return self.async_abort(reason="cannot_connect")
        taken = {s.unique_id for s in self._get_entry().subentries.values()}
        categories = {str(c["id"]): c for c in channels if c["type"] == CHANNEL_CATEGORY}
        free = [c for c in channels if c["type"] in SELECTABLE_CHANNELS and str(c["id"]) not in taken]
        if not free:
            return self.async_abort(reason="no_channels")
        if user_input is not None:
            channel = next(c for c in free if str(c["id"]) == user_input[CONF_CHANNEL_ID])
            title = _channel_label(channel).removesuffix(" (Forum)").removesuffix(" (Media)")
            return self.async_create_entry(
                title=title,
                data={
                    CONF_GUILD_ID: guild_id,
                    CONF_CHANNEL_ID: str(channel["id"]),
                    CONF_CHANNEL_TYPE: channel["type"],
                    CONF_NAME: channel["name"],
                },
                unique_id=str(channel["id"]),
            )

        def sort_key(channel: Mapping[str, Any]) -> tuple[int, int]:
            parent = categories.get(str(channel.get("parent_id")))
            return (parent["position"] if parent else -1, channel.get("position", 0))

        options = []
        for channel in sorted(free, key=sort_key):
            parent = categories.get(str(channel.get("parent_id")))
            label = _channel_label(channel)
            options.append(
                selector.SelectOptionDict(
                    value=str(channel["id"]), label=f"{parent['name']} › {label}" if parent else label
                )
            )
        return self.async_show_form(
            step_id="channel",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CHANNEL_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            description_placeholders={"guild": self._guild["name"]},
        )


class UserSubentryFlow(_BotSubentryFlow):
    """Direktnachrichten an einen Nutzer (seine Nutzer-ID steht im Entwicklermodus unter „ID kopieren“)."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_id = user_input[CONF_USER_ID].strip()
            unique_id = f"dm_{user_id}"
            if not user_id.isdigit():
                errors["base"] = "invalid_user"
            elif any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
                return self.async_abort(reason="already_configured")
            else:
                try:
                    await self._api().create_dm(user_id)
                except DiscordAuthError:
                    return self.async_abort(reason="invalid_auth")
                except DiscordNotFoundError:
                    errors["base"] = "invalid_user"
                except DiscordError:
                    errors["base"] = "cannot_connect"
                else:
                    name = user_input[CONF_NAME].strip()
                    return self.async_create_entry(
                        title=name, data={CONF_USER_ID: user_id, CONF_NAME: name}, unique_id=unique_id
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input or {}),
            errors=errors,
        )
