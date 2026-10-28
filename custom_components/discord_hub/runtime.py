"""Die Arbeit je Eintrag: Nachrichten senden, Forum-Posts mit Tages-Thread, Nachrichten und Threads verwalten.

Alle Aufrufe eines Eintrags laufen nacheinander (eine Sperre je Bot oder Webhook). Das ersetzt die Warteschlange
`mode: queued` in Skripten und verhindert, dass zwei gleichzeitige Meldungen zwei Tages-Threads anlegen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, NoReturn

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import (
    Attachment,
    BotApi,
    DiscordAuthError,
    DiscordConnectionError,
    DiscordError,
    DiscordForbiddenError,
    DiscordNotFoundError,
    DiscordRateLimitError,
    DiscordTooLargeError,
    WebhookApi,
)
from .const import (
    DAILY_KEEP_DAYS,
    DOMAIN,
    FORUM_CHANNELS,
    MAX_THREAD_NAME,
    TAG_CACHE_SECONDS,
)
from .files import async_load_attachments
from .messages import build_payload

_LOGGER = logging.getLogger(__name__)


def _invalid(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=key, translation_placeholders=placeholders or None
    )


def threads_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Speicher der gemerkten Tages-Threads eines Eintrags."""
    return Store(hass, 1, f"{DOMAIN}.{entry_id}")


@dataclass
class DiscordRuntime:
    """Zustand und Aufrufe eines Eintrags (Bot oder Webhook)."""

    hass: HomeAssistant
    entry: ConfigEntry
    api: BotApi | WebhookApi
    hub_device_id: str | None = None
    listener: Any = None  # der Listener des Bots (listener.py), für Webhooks None
    notices: Any = None  # die Meldungen des Bots (notice_runner.py), für Webhooks None
    registered_commands: dict[str, dict[str, str]] = field(default_factory=dict)  # Server -> {Befehl: ID bei Discord}
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _store: Store[dict[str, Any]] = field(init=False)
    _threads: dict[str, dict[str, str]] = field(default_factory=dict)
    _tag_cache: dict[str, tuple[float, list[dict[str, Any]]]] = field(default_factory=dict)
    _dm_channels: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._store = threads_store(self.hass, self.entry.entry_id)

    @property
    def is_bot(self) -> bool:
        return isinstance(self.api, BotApi)

    @property
    def session(self) -> aiohttp.ClientSession:
        return async_get_clientsession(self.hass)

    @property
    def daily_thread_count(self) -> int:
        """Wie viele Tages-Threads gerade gemerkt sind (für die Diagnose)."""
        return len(self._threads)

    # ------------------------------------------------------------------ Speicher
    async def async_load(self) -> None:
        """Gemerkte Tages-Threads laden. Alte (über `DAILY_KEEP_DAYS` Tage) fallen heraus."""
        stored = await self._store.async_load() or {}
        oldest = (dt_util.now().date() - timedelta(days=DAILY_KEEP_DAYS)).isoformat()
        self._threads = {
            key: rec
            for key, rec in (stored.get("threads") or {}).items()
            if isinstance(rec, dict) and rec.get("date", "") >= oldest and rec.get("thread_id")
        }
        self.registered_commands = {
            str(guild): {str(name): str(command_id) for name, command_id in commands.items()}
            for guild, commands in (stored.get("commands") or {}).items()
        }

    async def async_save(self) -> None:
        await self._store.async_save({"threads": self._threads, "commands": self.registered_commands})

    # ------------------------------------------------------------------ Fehler
    @contextlib.contextmanager
    def translated(self) -> Iterator[None]:
        """Fehler von Discord in verständliche Fehler von Home Assistant umwandeln."""
        try:
            yield
        except DiscordAuthError as err:
            self.entry.async_start_reauth(self.hass)
            raise self._ha_error("auth_failed", err) from err
        except DiscordForbiddenError as err:
            raise self._ha_error("forbidden", err) from err
        except DiscordNotFoundError as err:
            raise self._ha_error("not_found", err) from err
        except DiscordTooLargeError as err:
            raise self._ha_error("file_rejected", err) from err
        except DiscordRateLimitError as err:
            raise self._ha_error("rate_limited", err) from err
        except DiscordConnectionError as err:
            raise self._ha_error("cannot_connect", err) from err
        except DiscordError as err:
            raise self._ha_error("api_error", err) from err

    @staticmethod
    def _ha_error(key: str, err: DiscordError) -> HomeAssistantError:
        return HomeAssistantError(
            translation_domain=DOMAIN, translation_key=key, translation_placeholders={"details": err.message}
        )

    def _require_listening(self) -> None:
        """Schaltflächen funktionieren nur, wenn ein Bot sie auch hört."""
        if not self.is_bot:
            raise _invalid("bot_only")
        if self.listener is None or not self.listener.enabled:
            raise _invalid("buttons_need_listening")

    def _bot(self) -> BotApi:
        if not isinstance(self.api, BotApi):
            raise _invalid("bot_only")
        return self.api

    # ------------------------------------------------------------------ Hilfen
    async def dm_channel(self, user_id: str) -> str:
        """Kanal der Direktnachricht an einen Nutzer (wird einmal angelegt und gemerkt)."""
        if user_id not in self._dm_channels:
            with self.translated():
                channel = await self._bot().create_dm(user_id)
            self._dm_channels[user_id] = str(channel["id"])
        return self._dm_channels[user_id]

    async def _forum_tag_ids(self, channel_id: str, tags: list[str] | None) -> list[str]:
        """Namen oder IDs der Tags in IDs umsetzen. Reine Zahlen gelten als ID, alles andere als Name des Tags."""
        if not tags:
            return []
        names = [str(tag).strip() for tag in tags if str(tag).strip()]
        if not self.is_bot:
            if not all(name.isdigit() for name in names):
                raise _invalid("webhook_tag_ids")
            return names
        if all(name.isdigit() for name in names):
            return names
        available = await self.forum_tags(channel_id)
        by_name = {tag["name"].casefold(): tag["id"] for tag in available}
        ids = []
        for name in names:
            if name.isdigit():
                ids.append(name)
            elif name.casefold() in by_name:
                ids.append(by_name[name.casefold()])
            else:
                raise _invalid("unknown_tag", name=name, known=", ".join(tag["name"] for tag in available) or "-")
        return ids

    async def forum_tags(self, channel_id: str) -> list[dict[str, Any]]:
        """Die Tags eines Forum-Kanals: [{id, name, emoji, moderated}]. Wird kurz zwischengespeichert."""
        cached = self._tag_cache.get(channel_id)
        if cached and time.monotonic() - cached[0] < TAG_CACHE_SECONDS:
            return cached[1]
        with self.translated():
            channel = await self._bot().get_channel(channel_id)
        if channel.get("type") not in FORUM_CHANNELS:
            raise _invalid("not_a_forum")
        tags = [
            {
                "id": str(tag["id"]),
                "name": tag["name"],
                "emoji": tag.get("emoji_name"),
                "moderated": bool(tag.get("moderated")),
            }
            for tag in channel.get("available_tags") or []
        ]
        self._tag_cache[channel_id] = (time.monotonic(), tags)
        return tags

    @staticmethod
    def _webhook_extras(payload: dict[str, Any], username: str | None, avatar_url: str | None) -> None:
        if username:
            payload["username"] = username
        if avatar_url:
            payload["avatar_url"] = avatar_url

    async def _prepare(
        self,
        message: str | None,
        embeds: list[dict[str, Any]] | None,
        files: list[Any] | None,
        *,
        reply_to: str | None = None,
        allow_everyone: bool = False,
        buttons: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[Attachment]]:
        if buttons:
            self._require_listening()
        payload = build_payload(message, embeds, reply_to=reply_to, allow_everyone=allow_everyone, buttons=buttons)
        attachments = await async_load_attachments(self.hass, files)
        if not payload.get("content") and not payload.get("embeds") and not attachments:
            raise _invalid("empty_message")
        return payload, attachments

    # ------------------------------------------------------------------ Senden
    async def send_message(
        self,
        channel_id: str | None,
        *,
        message: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
        files: list[Any] | None = None,
        reply_to: str | None = None,
        thread_id: str | None = None,
        allow_everyone: bool = False,
        username: str | None = None,
        avatar_url: str | None = None,
        buttons: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        """Eine Nachricht in den Kanal oder in einen seiner Threads schicken."""
        payload, attachments = await self._prepare(
            message, embeds, files, reply_to=reply_to, allow_everyone=allow_everyone, buttons=buttons
        )
        async with self._lock:
            with self.translated():
                if isinstance(self.api, BotApi):
                    sent = await self.api.create_message(str(thread_id or channel_id), payload, attachments)
                else:
                    self._webhook_extras(payload, username, avatar_url)
                    sent = await self.api.execute(payload, attachments, thread_id=thread_id)
        return {"message_id": str(sent["id"]), "channel_id": str(sent.get("channel_id") or thread_id or channel_id)}

    async def forum_post(
        self,
        channel_id: str | None,
        *,
        thread_name: str,
        message: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
        files: list[Any] | None = None,
        tags: list[str] | None = None,
        daily: bool = False,
        key: str = "default",
        allow_everyone: bool = False,
        username: str | None = None,
        avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """Einen neuen Thread im Forum anlegen. Mit `daily` zählt je Schlüssel und Tag nur der erste Aufruf als neuer
        Thread, die weiteren schreiben in diesen Thread (fehlt er inzwischen, entsteht ein neuer)."""
        if self.is_bot:
            if not channel_id:
                raise _invalid("not_a_forum")
            tag_ids = await self._forum_tag_ids(channel_id, tags)
        else:
            tag_ids = await self._forum_tag_ids("", tags)
        payload, attachments = await self._prepare(message, embeds, files, allow_everyone=allow_everyone)
        name = thread_name.strip()[:MAX_THREAD_NAME] or "Beitrag"
        store_key = f"{channel_id or 'webhook'}:{key}"
        today = dt_util.now().date().isoformat()
        async with self._lock:
            record = self._threads.get(store_key) if daily else None
            if record and record.get("date") == today:
                try:
                    sent = await self._send_to_thread(record["thread_id"], payload, attachments, username, avatar_url)
                except DiscordNotFoundError:
                    _LOGGER.debug("Der gemerkte Thread von %s ist weg, es wird ein neuer angelegt", store_key)
                    self._threads.pop(store_key, None)
                except DiscordError as err:
                    self._reraise(err)
                else:
                    return {"thread_id": record["thread_id"], "message_id": str(sent["id"]), "created": False}
            with self.translated():
                thread_id, message_id = await self._create_thread(
                    channel_id, name, tag_ids, payload, attachments, username, avatar_url
                )
            if daily:
                self._threads[store_key] = {"thread_id": thread_id, "date": today}
                await self.async_save()
        return {"thread_id": thread_id, "message_id": message_id, "created": True}

    async def _send_to_thread(
        self,
        thread_id: str,
        payload: dict[str, Any],
        attachments: list[Attachment],
        username: str | None,
        avatar_url: str | None,
    ) -> dict[str, Any]:
        """In einen vorhandenen Thread schreiben. Die Fehler von Discord bleiben unübersetzt (404 heißt: Thread weg)."""
        if isinstance(self.api, BotApi):
            return await self.api.create_message(thread_id, payload, attachments)
        self._webhook_extras(payload, username, avatar_url)
        return await self.api.execute(payload, attachments, thread_id=thread_id)

    def _reraise(self, err: DiscordError) -> NoReturn:
        """Einen Fehler von Discord übersetzt weiterwerfen."""
        with self.translated():
            raise err
        raise err  # pragma: no cover

    async def _create_thread(
        self,
        channel_id: str | None,
        name: str,
        tag_ids: list[str],
        payload: dict[str, Any],
        attachments: list[Attachment],
        username: str | None,
        avatar_url: str | None,
    ) -> tuple[str, str]:
        if isinstance(self.api, BotApi):
            body: dict[str, Any] = {"name": name, "message": payload}
            if tag_ids:
                body["applied_tags"] = tag_ids
            created = await self.api.create_forum_thread(str(channel_id), body, attachments)
            first = created.get("message") or {}
            return str(created["id"]), str(first.get("id") or created["id"])
        body = {**payload, "thread_name": name}
        if tag_ids:
            body["applied_tags"] = tag_ids
        self._webhook_extras(body, username, avatar_url)
        created = await self.api.execute(body, attachments)
        return str(created["channel_id"]), str(created["id"])

    # ------------------------------------------------------------------ Verwalten
    async def edit_message(
        self,
        channel_id: str | None,
        message_id: str,
        *,
        message: str | None = None,
        embeds: list[dict[str, Any]] | None = None,
        thread_id: str | None = None,
        buttons: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        if message is None and embeds is None and buttons is None:
            raise _invalid("nothing_to_change")
        if buttons:
            self._require_listening()
        checked = build_payload(message, embeds, buttons=buttons)  # prüft Länge, Embeds und Schaltflächen
        patch: dict[str, Any] = {}
        if message is not None:
            patch["content"] = checked.get("content", "")
        if embeds is not None:
            patch["embeds"] = checked.get("embeds", [])
        if buttons is not None:
            patch["components"] = checked["components"]
        async with self._lock:
            with self.translated():
                if isinstance(self.api, BotApi):
                    await self.api.edit_message(str(thread_id or channel_id), str(message_id), patch)
                else:
                    await self.api.edit_message(str(message_id), patch, thread_id=thread_id)
        return {"message_id": str(message_id)}

    async def delete_message(self, channel_id: str | None, message_id: str, *, thread_id: str | None = None) -> None:
        async with self._lock:
            with self.translated():
                if isinstance(self.api, BotApi):
                    await self.api.delete_message(str(thread_id or channel_id), str(message_id))
                else:
                    await self.api.delete_message(str(message_id), thread_id=thread_id)

    async def add_reaction(
        self, channel_id: str | None, message_id: str, emoji: str, *, thread_id: str | None = None
    ) -> None:
        api = self._bot()
        async with self._lock:
            with self.translated():
                await api.add_reaction(str(thread_id or channel_id), str(message_id), emoji)

    async def pin_message(
        self, channel_id: str | None, message_id: str, pinned: bool, *, thread_id: str | None = None
    ) -> None:
        api = self._bot()
        async with self._lock:
            with self.translated():
                await api.pin_message(str(thread_id or channel_id), str(message_id), pinned)

    async def update_thread(
        self, thread_id: str, *, archived: bool | None = None, locked: bool | None = None, name: str | None = None
    ) -> dict[str, Any]:
        api = self._bot()
        patch: dict[str, Any] = {}
        if archived is not None:
            patch["archived"] = archived
        if locked is not None:
            patch["locked"] = locked
        if name:
            patch["name"] = name.strip()[:MAX_THREAD_NAME]
        if not patch:
            raise _invalid("nothing_to_change")
        async with self._lock:
            with self.translated():
                thread = await api.edit_channel(str(thread_id), patch)
        meta = thread.get("thread_metadata") or {}
        return {
            "thread_id": str(thread["id"]),
            "name": thread.get("name"),
            "archived": bool(meta.get("archived")),
            "locked": bool(meta.get("locked")),
        }
