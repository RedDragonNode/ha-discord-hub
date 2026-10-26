"""Auf Discord hören: Befehle, Buttons, Reaktionen und Nachrichten werden zu Ereignissen in Home Assistant.

Befehle und Buttons beantwortet die Integration sofort (Discord wartet nur drei Sekunden), die eigentliche Antwort
schickt die Automation später mit `discord_hub.respond`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import (
    BotApi,
    DiscordAuthError,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    WebhookApi,
)
from .commands import CommandConfig, clean_ids, commands_of
from .const import (
    CONF_TOKEN,
    DOMAIN,
    EVENT_BUTTON,
    EVENT_COMMAND,
    EVENT_MESSAGE,
    EVENT_REACTION,
    INTERACTION_SECONDS,
    OPT_ALLOWED_ROLES,
    OPT_ALLOWED_USERS,
    OPT_LISTEN,
    OPT_RECEIVE_MESSAGES,
    RESPOND_GRACE_SECONDS,
)
from .gateway import (
    INTENT_DIRECT_MESSAGE_REACTIONS,
    INTENT_DIRECT_MESSAGES,
    INTENT_GUILD_MESSAGE_REACTIONS,
    INTENT_GUILD_MESSAGES,
    INTENT_GUILDS,
    INTENT_MESSAGE_CONTENT,
    REASON_AUTH,
    REASON_INTENTS,
    GatewayClient,
)
from .messages import build_payload

if TYPE_CHECKING:
    from .event import DiscordCommandEvent
    from .runtime import DiscordRuntime

_LOGGER = logging.getLogger(__name__)

# Arten der Antwort auf eine Interaktion
CALLBACK_MESSAGE = 4
CALLBACK_DEFERRED_MESSAGE = 5
CALLBACK_DEFERRED_UPDATE = 6
FLAG_EPHEMERAL = 64  # nur für den Nutzer sichtbar

INTERACTION_COMMAND = 2
INTERACTION_COMPONENT = 3

TEXTS = {
    "de": {
        "unknown": "Diesen Befehl kenne ich nicht.",
        "denied": "Das darfst du nicht.",
        "done": "Erledigt.",
    },
    "en": {
        "unknown": "I do not know this command.",
        "denied": "You are not allowed to do this.",
        "done": "Done.",
    },
}


@dataclass
class Interaction:
    """Eine Interaktion, die noch beantwortet werden kann."""

    id: str
    token: str
    kind: str  # "command" oder "component"
    ephemeral: bool
    created: float
    pending_original: bool  # die „denkt nach“-Nachricht eines Befehls ist noch nicht mit der Antwort gefüllt
    answered: bool = False  # die Automation hat geantwortet
    fallback: asyncio.Task[None] | None = None


def _who(data: dict[str, Any]) -> tuple[str, str, list[str]]:
    """(Nutzer-ID, Name, Rollen) des Nutzers einer Interaktion oder Reaktion."""
    member = data.get("member") or {}
    user = member.get("user") or data.get("user") or {}
    name = member.get("nick") or user.get("global_name") or user.get("username") or ""
    user_id = user.get("id") or data.get("user_id") or ""
    return str(user_id), str(name), [str(role) for role in member.get("roles") or []]


class Listener:
    """Die Verbindung eines Bots zu Discord und alles, was sie auslöst."""

    def __init__(self, runtime: DiscordRuntime) -> None:
        self.runtime = runtime
        self.hass = runtime.hass
        self.entry = runtime.entry
        self.bot_id = str(self.entry.unique_id)
        self.event_entities: dict[str, DiscordCommandEvent] = {}
        self.gateway: GatewayClient | None = None
        self._interactions: dict[str, Interaction] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self.signal = f"{DOMAIN}_{self.entry.entry_id}_status"

    # ------------------------------------------------------------------ Einstellungen
    @property
    def commands(self) -> dict[str, CommandConfig]:
        return commands_of(self.entry)

    @property
    def enabled(self) -> bool:
        """Der Bot hört auf Discord, wenn es eingestellt ist oder er Befehle hat."""
        return bool(self.entry.options.get(OPT_LISTEN) or self.commands)

    @property
    def connected(self) -> bool:
        return bool(self.gateway and self.gateway.connected)

    @property
    def latency(self) -> float | None:
        return self.gateway.latency if self.gateway else None

    @property
    def intents(self) -> int:
        value = INTENT_GUILDS | INTENT_GUILD_MESSAGE_REACTIONS | INTENT_DIRECT_MESSAGE_REACTIONS
        if self.entry.options.get(OPT_RECEIVE_MESSAGES):
            value |= INTENT_GUILD_MESSAGES | INTENT_DIRECT_MESSAGES | INTENT_MESSAGE_CONTENT
        return value

    @property
    def _language(self) -> str:
        return "de" if str(self.hass.config.language).startswith("de") else "en"

    def _text(self, key: str) -> str:
        return TEXTS[self._language][key]

    def _allowed(self, command: CommandConfig | None, user_id: str, roles: list[str]) -> bool:
        """Darf dieser Nutzer? Befehle sind ohne Eintrag gesperrt, Buttons und Reaktionen ohne Liste offen."""
        users = (command.users if command else frozenset()) or frozenset(
            clean_ids(self.entry.options.get(OPT_ALLOWED_USERS))
        )
        allowed_roles = (command.roles if command else frozenset()) or frozenset(
            clean_ids(self.entry.options.get(OPT_ALLOWED_ROLES))
        )
        if command and command.everyone:
            return True
        if not users and not allowed_roles:
            return command is None
        return user_id in users or bool(allowed_roles & set(roles))

    # ------------------------------------------------------------------ Start und Ende
    async def async_start(self) -> None:
        """Befehle auf Discord abgleichen und, wenn eingestellt, die Verbindung aufbauen."""
        await self.async_sync_commands()
        if self.enabled:
            self.gateway = GatewayClient(
                self.runtime.session,
                self.entry.data[CONF_TOKEN],
                self.intents,
                self._dispatch,
                on_status=self._on_status,
                on_fatal=self._on_fatal,
            )
            self.entry.async_create_background_task(
                self.hass, self.gateway.run(), f"{DOMAIN} gateway {self.entry.title}"
            )

    async def async_stop(self) -> None:
        if self.gateway:
            await self.gateway.close()
        for task in list(self._tasks):
            task.cancel()
        for interaction in self._interactions.values():
            if interaction.fallback:
                interaction.fallback.cancel()
        self._interactions.clear()

    @callback
    def _on_status(self, connected: bool) -> None:
        if connected:
            ir.async_delete_issue(self.hass, DOMAIN, f"intents_{self.entry.entry_id}")
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _on_fatal(self, reason: str) -> None:
        if reason == REASON_AUTH:
            self.entry.async_start_reauth(self.hass)
        elif reason == REASON_INTENTS:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"intents_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="intents_missing",
                translation_placeholders={"bot": self.entry.title},
            )
        async_dispatcher_send(self.hass, self.signal)

    # ------------------------------------------------------------------ Befehle bei Discord anlegen
    async def async_sync_commands(self) -> None:
        """Die Befehle der Untereinträge auf den Servern anlegen und gestrichene entfernen.

        Es werden nur Befehle angefasst, die diese Integration selbst angelegt hat (ihre IDs sind gemerkt),
        andere Befehle desselben Bots bleiben unberührt.
        """
        api = self.runtime.api
        if not isinstance(api, BotApi):
            return
        wanted: dict[str, dict[str, CommandConfig]] = {}
        for command in self.commands.values():
            wanted.setdefault(command.guild_id, {})[command.name] = command
        registered = self.runtime.registered_commands
        forbidden = False
        for guild_id, commands in wanted.items():
            for name, command in commands.items():
                try:
                    created = await api.upsert_guild_command(self.bot_id, guild_id, command.definition)
                except DiscordAuthError:
                    self.entry.async_start_reauth(self.hass)
                    return
                except DiscordForbiddenError:
                    forbidden = True
                except DiscordError as err:
                    _LOGGER.warning("Der Befehl /%s ließ sich nicht bei Discord anlegen: %s", name, err.message)
                else:
                    registered.setdefault(guild_id, {})[name] = str(created["id"])
        for guild_id, items in list(registered.items()):
            for name, command_id in list(items.items()):
                if name in wanted.get(guild_id, {}):
                    continue
                try:
                    await api.delete_guild_command(self.bot_id, guild_id, command_id)
                except DiscordNotFoundError:
                    pass
                except DiscordError as err:
                    _LOGGER.warning("Der Befehl /%s ließ sich nicht bei Discord entfernen: %s", name, err.message)
                    continue
                items.pop(name, None)
            if not items:
                registered.pop(guild_id, None)
        await self.runtime.async_save()
        issue_id = f"commands_{self.entry.entry_id}"
        if forbidden:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="commands_not_allowed",
                translation_placeholders={"bot": self.entry.title},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # ------------------------------------------------------------------ Ereignisse von Discord
    async def _dispatch(self, name: str, data: dict[str, Any]) -> None:
        if name == "INTERACTION_CREATE":
            self._forget_old_interactions()
            if data.get("type") == INTERACTION_COMMAND:
                await self._on_command(data)
            elif data.get("type") == INTERACTION_COMPONENT:
                await self._on_component(data)
        elif name in ("MESSAGE_REACTION_ADD", "MESSAGE_REACTION_REMOVE"):
            self._on_reaction(data, "add" if name.endswith("ADD") else "remove")
        elif name == "MESSAGE_CREATE" and self.entry.options.get(OPT_RECEIVE_MESSAGES):
            self._on_message(data)

    def _base(self, data: dict[str, Any]) -> dict[str, Any]:
        user_id, user_name, roles = _who(data)
        return {
            "entry_id": self.entry.entry_id,
            "bot_id": self.bot_id,
            "user_id": user_id,
            "user_name": user_name,
            "roles": roles,
            "guild_id": str(data.get("guild_id") or ""),
            "channel_id": str(data.get("channel_id") or ""),
        }

    async def _acknowledge(self, data: dict[str, Any], payload: dict[str, Any]) -> bool:
        """Discord binnen drei Sekunden antworten. False, wenn das nicht ging."""
        try:
            await self.runtime.api.interaction_callback(str(data["id"]), str(data["token"]), payload)  # type: ignore[union-attr]
        except DiscordError as err:
            _LOGGER.warning("Die Interaktion ließ sich nicht beantworten: %s", err.message)
            return False
        return True

    async def _refuse(self, data: dict[str, Any], key: str) -> None:
        await self._acknowledge(
            data, {"type": CALLBACK_MESSAGE, "data": {"content": self._text(key), "flags": FLAG_EPHEMERAL}}
        )

    async def _on_command(self, data: dict[str, Any]) -> None:
        info = data.get("data") or {}
        guild_id = str(data.get("guild_id") or "")
        command = next(
            (c for c in self.commands.values() if c.name == info.get("name") and c.guild_id == guild_id), None
        )
        if command is None:
            await self._refuse(data, "unknown")
            return
        user_id, _, roles = _who(data)
        if not self._allowed(command, user_id, roles):
            _LOGGER.info("Der Befehl /%s wurde für den Nutzer %s abgelehnt", command.name, user_id)
            await self._refuse(data, "denied")
            return
        flags = FLAG_EPHEMERAL if command.ephemeral else 0
        if command.reply:
            payload: dict[str, Any] = {"type": CALLBACK_MESSAGE, "data": {"content": command.reply, "flags": flags}}
        else:
            payload = {"type": CALLBACK_DEFERRED_MESSAGE, "data": {"flags": flags}}
        if not await self._acknowledge(data, payload):
            return
        interaction = Interaction(
            str(data["id"]), str(data["token"]), "command", command.ephemeral, time.monotonic(), not command.reply
        )
        self._interactions[interaction.id] = interaction
        if interaction.pending_original:
            interaction.fallback = self._spawn(self._fallback(interaction))
        event = {
            **self._base(data),
            "interaction_id": interaction.id,
            "command": command.name,
            "options": {option["name"]: option.get("value") for option in info.get("options") or []},
        }
        self.hass.bus.async_fire(EVENT_COMMAND, event)
        if entity := self.event_entities.get(command.subentry_id):
            entity.async_use(event)

    async def _on_component(self, data: dict[str, Any]) -> None:
        info = data.get("data") or {}
        user_id, _, roles = _who(data)
        if not self._allowed(None, user_id, roles):
            await self._refuse(data, "denied")
            return
        if not await self._acknowledge(data, {"type": CALLBACK_DEFERRED_UPDATE}):
            return
        interaction = Interaction(
            str(data["id"]), str(data["token"]), "component", False, time.monotonic(), pending_original=False
        )
        self._interactions[interaction.id] = interaction
        self.hass.bus.async_fire(
            EVENT_BUTTON,
            {
                **self._base(data),
                "interaction_id": interaction.id,
                "custom_id": str(info.get("custom_id") or ""),
                "values": list(info.get("values") or []),
                "message_id": str((data.get("message") or {}).get("id") or ""),
            },
        )

    @callback
    def _on_reaction(self, data: dict[str, Any], action: str) -> None:
        user_id, _, roles = _who(data)
        if user_id == self.bot_id or not self._allowed(None, user_id, roles):
            return
        emoji = data.get("emoji") or {}
        self.hass.bus.async_fire(
            EVENT_REACTION,
            {
                **self._base(data),
                "action": action,
                "emoji": emoji.get("name"),
                "emoji_id": str(emoji["id"]) if emoji.get("id") else None,
                "message_id": str(data.get("message_id") or ""),
            },
        )

    @callback
    def _on_message(self, data: dict[str, Any]) -> None:
        author = data.get("author") or {}
        if author.get("bot") or str(author.get("id")) == self.bot_id:
            return
        user_id, _, roles = _who({**data, "user": author})
        if not self._allowed(None, user_id, roles):
            return
        self.hass.bus.async_fire(
            EVENT_MESSAGE,
            {
                **self._base({**data, "user": author}),
                "message_id": str(data.get("id") or ""),
                "content": data.get("content") or "",
                "reply_to": str((data.get("message_reference") or {}).get("message_id") or "") or None,
            },
        )

    # ------------------------------------------------------------------ Antworten
    def _spawn(self, coro: Any) -> asyncio.Task[None]:
        task = self.hass.async_create_background_task(coro, f"{DOMAIN} interaction")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _forget_old_interactions(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._interactions.items() if now - v.created > INTERACTION_SECONDS]:
            self._interactions.pop(key, None)

    def get_interaction(self, interaction_id: str) -> Interaction | None:
        self._forget_old_interactions()
        return self._interactions.get(str(interaction_id))

    async def _fallback(self, interaction: Interaction) -> None:
        """Kommt keine Antwort der Automation, wird der Befehl mit „Erledigt“ abgeschlossen."""
        await asyncio.sleep(RESPOND_GRACE_SECONDS)
        if interaction.answered:
            return
        try:
            await WebhookApi(self.runtime.session, self.bot_id, interaction.token).edit_message(
                "@original", {"content": self._text("done")}
            )
        except DiscordError as err:
            _LOGGER.debug("Der Befehl ließ sich nicht abschließen: %s", err.message)

    async def async_respond(
        self,
        interaction: Interaction,
        *,
        message: str | None,
        embeds: list[dict[str, Any]] | None,
        buttons: list[dict[str, Any]] | None,
        ephemeral: bool | None,
        update: bool,
    ) -> dict[str, str]:
        """Eine Interaktion beantworten: Die erste Antwort auf einen Befehl füllt die „denkt nach“-Nachricht, weitere
        sind neue Nachrichten. Bei einem Button ändert `update` die Nachricht mit dem Button."""
        payload = build_payload(message, embeds, buttons=buttons)
        payload.pop("message_reference", None)
        hook = WebhookApi(self.runtime.session, self.bot_id, interaction.token)
        edit_original = interaction.pending_original or (interaction.kind == "component" and update)
        if interaction.fallback:
            interaction.fallback.cancel()
        with self.runtime.translated():
            if edit_original:
                sent = await hook.edit_message("@original", payload)
                interaction.pending_original = False
            else:
                if ephemeral if ephemeral is not None else interaction.ephemeral:
                    payload["flags"] = FLAG_EPHEMERAL
                sent = await hook.execute(payload)
        interaction.answered = True
        return {"message_id": str(sent.get("id") or "")}
