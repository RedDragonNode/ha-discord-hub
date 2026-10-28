"""Config-Flow (Bot oder Webhook) und Untereinträge eines Bots (Kanäle, Direktnachrichten)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.exceptions import TemplateError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.template import Template

from .api import (
    BotApi,
    DiscordAuthError,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    WebhookApi,
    parse_webhook_url,
)
from .commands import (
    InvalidCommand,
    clean_ids,
    options_to_text,
    parse_options,
    validate_description,
    validate_name,
)
from .const import (
    CHANNEL_ANNOUNCEMENT,
    CHANNEL_CATEGORY,
    CHANNEL_FORUM,
    CHANNEL_MEDIA,
    CHANNEL_VOICE,
    CONF_CAMERA,
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_COOLDOWN,
    CONF_DAILY,
    CONF_DESCRIPTION,
    CONF_EMBED,
    CONF_ENTITY_ID,
    CONF_EPHEMERAL,
    CONF_EVENT_TYPE,
    CONF_EVERYONE,
    CONF_GUILD_ID,
    CONF_KIND,
    CONF_MESSAGE,
    CONF_NAME,
    CONF_OPTIONS,
    CONF_REPLY,
    CONF_ROLES,
    CONF_SNAPSHOT,
    CONF_STATE_TO,
    CONF_TAGS,
    CONF_TARGET,
    CONF_TEMPLATE,
    CONF_THREAD_NAME,
    CONF_TITLE,
    CONF_TOKEN,
    CONF_USER_ID,
    CONF_USERS,
    CONF_WEBHOOK_URL,
    DOMAIN,
    FORUM_CHANNELS,
    KIND_BOT,
    KIND_WEBHOOK,
    MAX_COOLDOWN,
    OPT_ALLOWED_ROLES,
    OPT_ALLOWED_USERS,
    OPT_LISTEN,
    OPT_RECEIVE_MESSAGES,
    OPT_TRACK_PRESENCE,
    SELECTABLE_CHANNELS,
    SUBENTRY_CHANNEL,
    SUBENTRY_COMMAND,
    SUBENTRY_MEMBER,
    SUBENTRY_NOTICE,
    SUBENTRY_SERVER,
    SUBENTRY_USER,
)
from .notice_runner import camera_of_device
from .notices import DEFAULT_THREAD_NAME, KIND_EVENT, KIND_STATE, TEMPLATES, NoticeTemplate, language_of

_TEXT = selector.TextSelector()
_SECRET = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))

BOT_SCHEMA = vol.Schema({vol.Required(CONF_TOKEN): _SECRET})
WEBHOOK_SCHEMA = vol.Schema({vol.Required(CONF_NAME): _TEXT, vol.Required(CONF_WEBHOOK_URL): _SECRET})
USER_SCHEMA = vol.Schema({vol.Required(CONF_NAME): _TEXT, vol.Required(CONF_USER_ID): _TEXT})
_IDS = selector.TextSelector(selector.TextSelectorConfig(multiple=True))
_BOOL = selector.BooleanSelector()
_LONG_TEXT = selector.TextSelector(selector.TextSelectorConfig(multiline=True))

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(OPT_LISTEN, default=False): _BOOL,
        vol.Optional(OPT_RECEIVE_MESSAGES, default=False): _BOOL,
        vol.Optional(OPT_TRACK_PRESENCE, default=False): _BOOL,
        vol.Optional(OPT_ALLOWED_USERS, default=[]): _IDS,
        vol.Optional(OPT_ALLOWED_ROLES, default=[]): _IDS,
    }
)
COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): _TEXT,
        vol.Required(CONF_DESCRIPTION): _TEXT,
        vol.Optional(CONF_OPTIONS, default=""): _LONG_TEXT,
        vol.Optional(CONF_REPLY, default=""): _TEXT,
        vol.Optional(CONF_EPHEMERAL, default=False): _BOOL,
        vol.Optional(CONF_EVERYONE, default=False): _BOOL,
        vol.Optional(CONF_USERS, default=[]): _IDS,
        vol.Optional(CONF_ROLES, default=[]): _IDS,
    }
)


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
        return {
            SUBENTRY_CHANNEL: ChannelSubentryFlow,
            SUBENTRY_USER: UserSubentryFlow,
            SUBENTRY_COMMAND: CommandSubentryFlow,
            SUBENTRY_SERVER: ServerSubentryFlow,
            SUBENTRY_MEMBER: MemberSubentryFlow,
            SUBENTRY_NOTICE: NoticeSubentryFlow,
        }

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return config_entry.data.get(CONF_KIND) == KIND_BOT

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return DiscordHubOptionsFlow()


class DiscordHubOptionsFlow(OptionsFlow):
    """Ob der Bot auf Discord hört, wen er beobachtet und wer Buttons und Reaktionen auslösen darf."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            users = clean_ids(user_input.get(OPT_ALLOWED_USERS))
            roles = clean_ids(user_input.get(OPT_ALLOWED_ROLES))
            if not all(value.isdigit() for value in (*users, *roles)):
                errors["base"] = "invalid_ids"
            else:
                return self.async_create_entry(
                    data={
                        OPT_LISTEN: bool(user_input.get(OPT_LISTEN)),
                        OPT_RECEIVE_MESSAGES: bool(user_input.get(OPT_RECEIVE_MESSAGES)),
                        OPT_TRACK_PRESENCE: bool(user_input.get(OPT_TRACK_PRESENCE)),
                        OPT_ALLOWED_USERS: users,
                        OPT_ALLOWED_ROLES: roles,
                    }
                )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(OPTIONS_SCHEMA, user_input or self.config_entry.options),
            errors=errors,
        )


def _canonical_webhook(parsed: tuple[str, str]) -> str:
    return f"https://discord.com/api/webhooks/{parsed[0]}/{parsed[1]}"


# ---------------------------------------------------------------------- Kanäle
class _BotSubentryFlow(ConfigSubentryFlow):
    def _api(self) -> BotApi:
        return BotApi(async_get_clientsession(self.hass), self._get_entry().data[CONF_TOKEN])


class _GuildSubentryFlow(_BotSubentryFlow):
    """Erster Schritt: der Server. Er entfällt, wenn der Bot nur auf einem ist."""

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
            return await self._guild_chosen()
        if user_input is not None:
            self._guild = next(g for g in guilds if str(g["id"]) == user_input[CONF_GUILD_ID])
            return await self._guild_chosen()
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

    async def _guild_chosen(self) -> SubentryFlowResult:
        raise NotImplementedError


def _channel_label(channel: Mapping[str, Any]) -> str:
    """Anzeige in der Auswahl: # Text, 📢 Ankündigungen, 🔊 Sprache, Name (Forum) und Name (Media)."""
    name = channel["name"]
    return {
        CHANNEL_ANNOUNCEMENT: f"📢 {name}",
        CHANNEL_VOICE: f"🔊 {name}",
        CHANNEL_FORUM: f"{name} (Forum)",
        CHANNEL_MEDIA: f"{name} (Media)",
    }.get(channel["type"], f"#{name}")


class ChannelSubentryFlow(_GuildSubentryFlow):
    """Einen Kanal des Servers hinzufügen (Text, Ankündigungen, Sprache, Forum, Media)."""

    async def _guild_chosen(self) -> SubentryFlowResult:
        return await self.async_step_channel()

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


class CommandSubentryFlow(_GuildSubentryFlow):
    """Einen Slash-Befehl anlegen (oder bearbeiten): Name, Optionen, Antwort und wer ihn benutzen darf."""

    async def _guild_chosen(self) -> SubentryFlowResult:
        return await self.async_step_command()

    async def async_step_command(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        assert self._guild is not None
        guild_id = str(self._guild["id"])
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = self._validate(guild_id, user_input, current_id=None)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"/{data[CONF_NAME]}", data=data, unique_id=f"cmd_{guild_id}_{data[CONF_NAME]}"
                )
        return self.async_show_form(
            step_id="command",
            data_schema=self.add_suggested_values_to_schema(COMMAND_SCHEMA, user_input or {}),
            errors=errors,
            description_placeholders={"guild": self._guild["name"]},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        guild_id = str(subentry.data[CONF_GUILD_ID])
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = self._validate(guild_id, user_input, current_id=subentry.subentry_id)
            if error:
                errors["base"] = error
            else:
                return self.async_update_and_abort(
                    self._get_entry(),
                    subentry,
                    title=f"/{data[CONF_NAME]}",
                    data=data,
                    unique_id=f"cmd_{guild_id}_{data[CONF_NAME]}",
                )
        current = {**subentry.data, CONF_OPTIONS: options_to_text(subentry.data.get(CONF_OPTIONS) or [])}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(COMMAND_SCHEMA, user_input or current),
            errors=errors,
        )

    def _validate(
        self, guild_id: str, user_input: dict[str, Any], *, current_id: str | None
    ) -> tuple[dict[str, Any], str | None]:
        """(Daten des Befehls, Fehlerschlüssel). Bei einem Fehler sind die Daten leer."""
        try:
            name = validate_name(user_input[CONF_NAME])
            description = validate_description(user_input[CONF_DESCRIPTION])
            options = parse_options(user_input.get(CONF_OPTIONS) or "")
        except InvalidCommand as err:
            return {}, str(err)
        users = clean_ids(user_input.get(CONF_USERS))
        roles = clean_ids(user_input.get(CONF_ROLES))
        if not all(value.isdigit() for value in (*users, *roles)):
            return {}, "invalid_ids"
        entry = self._get_entry()
        taken = any(
            s.unique_id == f"cmd_{guild_id}_{name}" and s.subentry_id != current_id for s in entry.subentries.values()
        )
        if taken:
            return {}, "already_exists"
        everyone = bool(user_input.get(CONF_EVERYONE))
        inherited = entry.options.get(OPT_ALLOWED_USERS) or entry.options.get(OPT_ALLOWED_ROLES)
        if not (everyone or users or roles or inherited):
            return {}, "no_permission"
        return {
            CONF_GUILD_ID: guild_id,
            CONF_NAME: name,
            CONF_DESCRIPTION: description,
            CONF_OPTIONS: options,
            CONF_REPLY: (user_input.get(CONF_REPLY) or "").strip()[:2000],
            CONF_EPHEMERAL: bool(user_input.get(CONF_EPHEMERAL)),
            CONF_EVERYONE: everyone,
            CONF_USERS: users,
            CONF_ROLES: roles,
        }, None


# ---------------------------------------------------------------------- Server und Mitglieder beobachten
class ServerSubentryFlow(_GuildSubentryFlow):
    """Einen Server beobachten: Mitglieder, Mitglieder online und wer in Sprachkanälen ist."""

    async def _guild_chosen(self) -> SubentryFlowResult:
        assert self._guild is not None
        guild_id = str(self._guild["id"])
        unique_id = f"server_{guild_id}"
        if any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
            return self.async_abort(reason="already_configured")
        return self.async_create_entry(
            title=self._guild["name"],
            data={CONF_GUILD_ID: guild_id, CONF_NAME: self._guild["name"]},
            unique_id=unique_id,
        )


class MemberSubentryFlow(_GuildSubentryFlow):
    """Ein Mitglied beobachten: sein Status, seine Aktivität und ob es in einem Sprachkanal ist."""

    async def _guild_chosen(self) -> SubentryFlowResult:
        return await self.async_step_member()

    async def async_step_member(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        assert self._guild is not None
        guild_id = str(self._guild["id"])
        errors: dict[str, str] = {}
        if user_input is not None:
            user_id = user_input[CONF_USER_ID].strip()
            unique_id = f"member_{guild_id}_{user_id}"
            if not user_id.isdigit():
                errors["base"] = "invalid_user"
            elif any(s.unique_id == unique_id for s in self._get_entry().subentries.values()):
                return self.async_abort(reason="already_configured")
            else:
                try:
                    name = await self._member_name(guild_id, user_id)
                except DiscordAuthError:
                    return self.async_abort(reason="invalid_auth")
                except DiscordNotFoundError:
                    errors["base"] = "unknown_member"
                except DiscordError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=name,
                        data={CONF_GUILD_ID: guild_id, CONF_USER_ID: user_id, CONF_NAME: name},
                        unique_id=unique_id,
                    )
        return self.async_show_form(
            step_id="member",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_USER_ID): _TEXT}), user_input or {}
            ),
            errors=errors,
            description_placeholders={"guild": self._guild["name"]},
        )

    async def _member_name(self, guild_id: str, user_id: str) -> str:
        """Der Anzeigename des Mitglieds auf dem Server. Er prüft zugleich, dass es dort ist."""
        try:
            member = await self._api().get_member(guild_id, user_id)
        except DiscordForbiddenError:
            # ohne den Server-Members-Intent verweigert Discord die Abfrage; der Nutzer selbst ist erreichbar
            user = await self._api().get_user(user_id)
            return str(user.get("global_name") or user["username"])
        user = member.get("user") or {}
        return str(member.get("nick") or user.get("global_name") or user.get("username") or user_id)


# ---------------------------------------------------------------------- Meldungen
class NoticeSubentryFlow(_BotSubentryFlow):
    """Eine Meldung anlegen (oder bearbeiten): Vorlage, Quelle, Ziel, Text, Schnappschuss und Mindestabstand."""

    _template: NoticeTemplate | None = None
    _data: dict[str, Any]
    _reconfigured: ConfigSubentry | None = None

    # ------------------------------------------------------------------ Hilfen
    def _targets(self) -> dict[str, ConfigSubentry]:
        """Die Kanäle und Direktnachrichten des Bots, an die eine Meldung gehen kann."""
        return {
            s.subentry_id: s
            for s in self._get_entry().subentries.values()
            if s.subentry_type in (SUBENTRY_CHANNEL, SUBENTRY_USER)
        }

    def _is_forum(self, target_id: str) -> bool:
        target = self._targets()[target_id]
        return target.subentry_type == SUBENTRY_CHANNEL and int(target.data.get(CONF_CHANNEL_TYPE, 0)) in FORUM_CHANNELS

    def _check_template(self, text: str) -> bool:
        """Ist der Text eine gültige Vorlage von Home Assistant?"""
        try:
            Template(text, self.hass).ensure_valid()
        except TemplateError:
            return False
        return True

    @staticmethod
    def _own_text(text: str, defaults: dict[str, str]) -> str:
        """Der Text, wie er gespeichert wird: Entspricht er einem Vorgabetext, bleibt er leer und folgt der Sprache."""
        text = text.strip()
        return "" if text in defaults.values() else text

    def _suggested(self, template: NoticeTemplate) -> dict[str, Any]:
        language = language_of(self.hass)
        if self._reconfigured is None:
            return {
                CONF_TITLE: template.title[language],
                CONF_MESSAGE: template.message[language],
                CONF_EMBED: True,
                CONF_SNAPSHOT: template.snapshot,
                CONF_COOLDOWN: template.cooldown,
            }
        data = dict(self._reconfigured.data)
        data[CONF_TITLE] = data.get(CONF_TITLE) or template.title[language]
        data[CONF_MESSAGE] = data.get(CONF_MESSAGE) or template.message[language]
        if not data.get(CONF_CAMERA):
            data.pop(CONF_CAMERA, None)  # eine leere Kamera als Vorschlag lehnt die Auswahl beim Abschicken ab
        return data

    # ------------------------------------------------------------------ Schritte
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._targets():
            return self.async_abort(reason="no_targets")
        if user_input is not None:
            self._template = TEMPLATES[user_input[CONF_TEMPLATE]]
            self._data = {CONF_TEMPLATE: self._template.key}
            return await self.async_step_notice()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEMPLATE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(TEMPLATES),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="notice_template",
                        )
                    )
                }
            ),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        self._reconfigured = self._get_reconfigure_subentry()
        self._template = TEMPLATES.get(str(self._reconfigured.data.get(CONF_TEMPLATE)))
        if self._template is None:
            return self.async_abort(reason="unknown_template")
        self._data = dict(self._reconfigured.data)
        return await self.async_step_notice()

    async def async_step_notice(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        template = self._template
        assert template is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = self._validate(template, user_input)
            if error:
                errors["base"] = error
            else:
                self._data = data
                if self._is_forum(data[CONF_TARGET]):
                    return await self.async_step_forum()
                return self._finish()
        return self.async_show_form(
            step_id="notice",
            data_schema=self.add_suggested_values_to_schema(
                self._notice_schema(template), user_input or self._suggested(template)
            ),
            errors=errors,
            description_placeholders={"template": template.label[language_of(self.hass)]},
        )

    async def async_step_forum(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        language = language_of(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            name = (user_input.get(CONF_THREAD_NAME) or "").strip()
            if name and not self._check_template(name):
                errors["base"] = "invalid_template"
            else:
                self._data |= {
                    CONF_THREAD_NAME: self._own_text(name, DEFAULT_THREAD_NAME),
                    CONF_TAGS: clean_ids(user_input.get(CONF_TAGS)),
                    CONF_DAILY: bool(user_input.get(CONF_DAILY)),
                }
                return self._finish()
        current = dict(self._reconfigured.data) if self._reconfigured else {}
        suggested = user_input or {
            CONF_THREAD_NAME: current.get(CONF_THREAD_NAME) or DEFAULT_THREAD_NAME[language],
            CONF_TAGS: current.get(CONF_TAGS, []),
            CONF_DAILY: current.get(CONF_DAILY, True),
        }
        schema = vol.Schema(
            {
                vol.Optional(CONF_THREAD_NAME, default=""): _TEXT,
                vol.Optional(CONF_TAGS, default=[]): _IDS,
                vol.Optional(CONF_DAILY, default=True): _BOOL,
            }
        )
        return self.async_show_form(
            step_id="forum",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    # ------------------------------------------------------------------ Formular und Prüfung
    def _notice_schema(self, template: NoticeTemplate) -> vol.Schema:
        targets = [selector.SelectOptionDict(value=sid, label=s.title) for sid, s in self._targets().items()]
        fields: dict[Any, Any] = {
            vol.Required(CONF_TARGET): selector.SelectSelector(
                selector.SelectSelectorConfig(options=targets, mode=selector.SelectSelectorMode.DROPDOWN)
            )
        }
        if template.kind == KIND_STATE:
            entity_filter = {
                key: value
                for key, value in (
                    ("domain", template.entity_domain),
                    ("integration", template.integration),
                    ("device_class", template.device_class),
                )
                if value
            }
            fields[vol.Required(CONF_ENTITY_ID)] = selector.EntitySelector(
                selector.EntitySelectorConfig(**entity_filter)  # type: ignore[arg-type]
            )
            if template.key == "custom_state":
                fields[vol.Optional(CONF_STATE_TO, default="")] = _TEXT
        elif template.event_type is None:
            fields[vol.Required(CONF_EVENT_TYPE)] = _TEXT
        fields |= {
            vol.Optional(CONF_TITLE, default=""): _TEXT,
            vol.Optional(CONF_MESSAGE, default=""): _LONG_TEXT,
            vol.Optional(CONF_EMBED, default=True): _BOOL,
            vol.Optional(CONF_SNAPSHOT, default=template.snapshot): _BOOL,
            vol.Optional(CONF_CAMERA): selector.EntitySelector(selector.EntitySelectorConfig(domain="camera")),
            vol.Optional(CONF_COOLDOWN, default=template.cooldown): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=MAX_COOLDOWN,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
        }
        return vol.Schema(fields)

    def _validate(self, template: NoticeTemplate, user_input: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        """(Daten der Meldung, Fehlerschlüssel). Bei einem Fehler sind die Daten leer."""
        if user_input[CONF_TARGET] not in self._targets():
            return {}, "unknown_target"
        event_type = (user_input.get(CONF_EVENT_TYPE) or "").strip()
        if template.kind == KIND_EVENT and template.event_type is None and not event_type:
            return {}, "invalid_event_type"
        texts = {key: (user_input.get(key) or "").strip() for key in (CONF_TITLE, CONF_MESSAGE)}
        if not all(self._check_template(text) for text in texts.values() if text):
            return {}, "invalid_template"
        entity_id = user_input.get(CONF_ENTITY_ID) or ""
        camera = user_input.get(CONF_CAMERA) or ""
        snapshot = bool(user_input.get(CONF_SNAPSHOT))
        if snapshot and not camera and not (template.kind == KIND_STATE and camera_of_device(self.hass, entity_id)):
            return {}, "camera_needed"
        data: dict[str, Any] = {
            CONF_TEMPLATE: template.key,
            CONF_TARGET: user_input[CONF_TARGET],
            CONF_TITLE: self._own_text(texts[CONF_TITLE], template.title),
            CONF_MESSAGE: self._own_text(texts[CONF_MESSAGE], template.message),
            CONF_EMBED: bool(user_input.get(CONF_EMBED)),
            CONF_SNAPSHOT: snapshot,
            CONF_CAMERA: camera,
            CONF_COOLDOWN: min(max(int(user_input.get(CONF_COOLDOWN) or 0), 0), MAX_COOLDOWN),
        }
        if template.kind == KIND_STATE:
            data[CONF_ENTITY_ID] = entity_id
            if template.key == "custom_state":
                data[CONF_STATE_TO] = (user_input.get(CONF_STATE_TO) or "").strip()
        elif template.event_type is None:
            data[CONF_EVENT_TYPE] = event_type
        return data, None

    def _finish(self) -> SubentryFlowResult:
        template = self._template
        assert template is not None
        target = self._targets()[self._data[CONF_TARGET]]
        title = f"{template.label[language_of(self.hass)]} › {target.title}"
        if self._reconfigured is not None:
            return self.async_update_and_abort(self._get_entry(), self._reconfigured, title=title, data=self._data)
        return self.async_create_entry(title=title, data=self._data)
