"""Schlanker Client für die REST-Schnittstelle von Discord (Bot und Webhook), ohne zusätzliche Bibliothek.

Er wiederholt Anfragen bei Rate-Limits (429) und Serverfehlern, ordnet Fehler zu und hält Token und
Webhook-Adressen aus allen Meldungen heraus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/RedDragonNode/ha-discord-hub, 0.2.0)"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120)

MAX_ATTEMPTS = 4
MAX_RETRY_WAIT = 30.0  # längere Wartezeiten von Discord geben wir als Fehler weiter

# Fehlercodes von Discord (JSON-Feld "code")
CODE_FILE_TOO_LARGE = 40005


async def _sleep(seconds: float) -> None:
    """Warten (eigene Funktion, damit Tests nicht wirklich warten müssen)."""
    await asyncio.sleep(seconds)


class DiscordError(Exception):
    """Discord hat die Anfrage abgelehnt oder war nicht erreichbar."""

    def __init__(self, message: str, *, status: int | None = None, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class DiscordConnectionError(DiscordError):
    """Discord ist nicht erreichbar."""


class DiscordAuthError(DiscordError):
    """Token oder Webhook sind ungültig (401)."""


class DiscordForbiddenError(DiscordError):
    """Dem Bot fehlt eine Berechtigung (403)."""


class DiscordNotFoundError(DiscordError):
    """Kanal, Nachricht, Thread oder Webhook gibt es nicht (404)."""


class DiscordTooLargeError(DiscordError):
    """Die Dateien sind für diesen Server zu groß (413)."""


class DiscordRateLimitError(DiscordError):
    """Discord bremst länger, als wir warten wollen (429)."""


@dataclass(frozen=True)
class Attachment:
    """Eine Datei, die an eine Nachricht angehängt wird."""

    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


class _Http:
    """Gemeinsame Anfragen mit Wiederholung. `secret` wird in Protokoll und Fehlern durch *** ersetzt."""

    def __init__(self, session: aiohttp.ClientSession, base: str, headers: dict[str, str], secret: str) -> None:
        self._session = session
        self._base = base
        self._headers = {"User-Agent": USER_AGENT, **headers}
        self._secret = secret

    def _clean(self, text: str) -> str:
        return text.replace(self._secret, "***") if self._secret else text

    @staticmethod
    def _form(payload: dict[str, Any] | None, files: list[Attachment]) -> aiohttp.FormData:
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload or {}), content_type="application/json")
        for index, file in enumerate(files):
            form.add_field(f"files[{index}]", file.data, filename=file.filename, content_type=file.content_type)
        return form

    async def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        files: list[Attachment] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        """Eine Anfrage senden. Gibt die JSON-Antwort zurück, bei 204 None."""
        url = f"{self._base}{path}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            kwargs: dict[str, Any] = {"headers": self._headers, "params": params, "timeout": REQUEST_TIMEOUT}
            if files:
                kwargs["data"] = self._form(payload, files)  # eine Form ist nach dem Senden verbraucht
            elif payload is not None:
                kwargs["json"] = payload
            try:
                async with self._session.request(method, url, **kwargs) as resp:
                    status = resp.status
                    body = await resp.read()
                    retry_header = resp.headers.get("Retry-After")
            except (TimeoutError, aiohttp.ClientError) as err:
                raise DiscordConnectionError(self._clean(str(err) or type(err).__name__)) from err
            data: Any = None
            if body:
                try:
                    data = json.loads(body)
                except ValueError:
                    data = None
            if 200 <= status < 300:
                return data
            message = (data.get("message") if isinstance(data, dict) else None) or f"HTTP {status}"
            code = data.get("code") if isinstance(data, dict) else None
            if status == 429:
                wait = _retry_after(data, retry_header)
                if attempt < MAX_ATTEMPTS and wait <= MAX_RETRY_WAIT:
                    _LOGGER.debug("Discord bremst, nächster Versuch in %.1f s", wait)
                    await _sleep(wait)
                    continue
                raise DiscordRateLimitError(message, status=status, code=code)
            if status >= 500 and attempt < MAX_ATTEMPTS and method != "POST":
                # ein POST könnte trotz Fehlermeldung angekommen sein, ihn nicht zu wiederholen verhindert Doppelte
                await _sleep(attempt)
                continue
            raise _error_for(status, code, self._clean(str(message)))
        raise DiscordError("unreachable")  # pragma: no cover


_WEBHOOK_URL = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/(\d+)/([\w-]+)/?(?:\?.*)?$"
)


def parse_webhook_url(url: str) -> tuple[str, str] | None:
    """(ID, Token) aus der Adresse eines Webhooks, None wenn es keine ist."""
    match = _WEBHOOK_URL.match(url.strip())
    return (match.group(1), match.group(2)) if match else None


def _retry_after(data: Any, header: str | None) -> float:
    for value in (data.get("retry_after") if isinstance(data, dict) else None, header):
        try:
            return max(float(value), 0.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return 1.0


def _error_for(status: int, code: int | None, message: str) -> DiscordError:
    if status == 401:
        return DiscordAuthError(message, status=status, code=code)
    if status == 403:
        return DiscordForbiddenError(message, status=status, code=code)
    if status == 404:
        return DiscordNotFoundError(message, status=status, code=code)
    if status == 413 or code == CODE_FILE_TOO_LARGE:
        return DiscordTooLargeError(message, status=status, code=code)
    return DiscordError(message, status=status, code=code)


class BotApi(_Http):
    """Anfragen als Bot (Token)."""

    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        super().__init__(session, API_BASE, {"Authorization": f"Bot {token}"}, token)

    async def get_me(self) -> dict[str, Any]:
        return await self.request("GET", "/users/@me")

    async def get_guilds(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/users/@me/guilds", params={"limit": "200"})

    async def get_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", f"/guilds/{guild_id}/channels")

    async def get_channel(self, channel_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/channels/{channel_id}")

    async def create_dm(self, user_id: str) -> dict[str, Any]:
        return await self.request("POST", "/users/@me/channels", payload={"recipient_id": user_id})

    async def create_message(
        self, channel_id: str, payload: dict[str, Any], files: list[Attachment] | None = None
    ) -> dict[str, Any]:
        return await self.request("POST", f"/channels/{channel_id}/messages", payload=payload, files=files)

    async def edit_message(self, channel_id: str, message_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/channels/{channel_id}/messages/{message_id}", payload=payload)

    async def delete_message(self, channel_id: str, message_id: str) -> None:
        await self.request("DELETE", f"/channels/{channel_id}/messages/{message_id}")

    async def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        encoded = quote(emoji, safe="")
        await self.request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{encoded}/@me")

    async def pin_message(self, channel_id: str, message_id: str, pinned: bool) -> None:
        method = "PUT" if pinned else "DELETE"
        try:
            await self.request(method, f"/channels/{channel_id}/messages/pins/{message_id}")
        except DiscordNotFoundError:
            # ältere Schnittstelle, falls die neue (noch) nicht antwortet
            await self.request(method, f"/channels/{channel_id}/pins/{message_id}")

    async def create_forum_thread(
        self, channel_id: str, payload: dict[str, Any], files: list[Attachment] | None = None
    ) -> dict[str, Any]:
        return await self.request("POST", f"/channels/{channel_id}/threads", payload=payload, files=files)

    async def edit_channel(self, channel_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return await self.request("PATCH", f"/channels/{channel_id}", payload=patch)

    # ------------------------------------------------------------------ Befehle und Interaktionen
    async def upsert_guild_command(self, app_id: str, guild_id: str, definition: dict[str, Any]) -> dict[str, Any]:
        """Einen Befehl auf einem Server anlegen oder (bei gleichem Namen) aktualisieren. Er gilt sofort."""
        return await self.request("POST", f"/applications/{app_id}/guilds/{guild_id}/commands", payload=definition)

    async def delete_guild_command(self, app_id: str, guild_id: str, command_id: str) -> None:
        await self.request("DELETE", f"/applications/{app_id}/guilds/{guild_id}/commands/{command_id}")

    async def interaction_callback(self, interaction_id: str, token: str, payload: dict[str, Any]) -> None:
        """Auf eine Interaktion antworten (binnen 3 Sekunden): sofort, mit „denkt nach“ oder als Aktualisierung."""
        await self.request("POST", f"/interactions/{interaction_id}/{token}/callback", payload=payload)


class WebhookApi(_Http):
    """Anfragen über die Adresse eines Webhooks. Die Adresse enthält das Geheimnis und kommt nie ins Protokoll."""

    def __init__(self, session: aiohttp.ClientSession, webhook_id: str, webhook_token: str) -> None:
        super().__init__(session, f"{API_BASE}/webhooks/{webhook_id}/{webhook_token}", {}, webhook_token)

    async def get_info(self) -> dict[str, Any]:
        return await self.request("GET", "")

    async def execute(
        self,
        payload: dict[str, Any],
        files: list[Attachment] | None = None,
        *,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        params = {"wait": "true"}
        if thread_id:
            params["thread_id"] = thread_id
        return await self.request("POST", "", payload=payload, files=files, params=params)

    async def edit_message(
        self, message_id: str, payload: dict[str, Any], *, thread_id: str | None = None
    ) -> dict[str, Any]:
        params = {"thread_id": thread_id} if thread_id else None
        return await self.request("PATCH", f"/messages/{message_id}", payload=payload, params=params)

    async def delete_message(self, message_id: str, *, thread_id: str | None = None) -> None:
        params = {"thread_id": thread_id} if thread_id else None
        await self.request("DELETE", f"/messages/{message_id}", params=params)
