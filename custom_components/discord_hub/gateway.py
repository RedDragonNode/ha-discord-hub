"""Die dauerhafte Verbindung zu Discord (Gateway), ohne zusätzliche Bibliothek.

Sie hält den Herzschlag, meldet den Bot an, setzt nach Abbrüchen die alte Sitzung fort und gibt alle Ereignisse
(Interaktionen, Reaktionen, Nachrichten) an einen Handler weiter. Endgültige Fehler (falscher Token, nicht
freigeschaltete Intents) beenden sie und werden gemeldet, alles andere versucht sie mit wachsender Pause erneut.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

GATEWAY_URL = "wss://gateway.discord.gg"
GATEWAY_QUERY = "/?v=10&encoding=json"

# Operationen des Gateways
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Intents (welche Ereignisse Discord schickt)
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MESSAGES = 1 << 9
INTENT_GUILD_MESSAGE_REACTIONS = 1 << 10
INTENT_DIRECT_MESSAGES = 1 << 12
INTENT_DIRECT_MESSAGE_REACTIONS = 1 << 13
INTENT_MESSAGE_CONTENT = 1 << 15  # privilegiert: im Developer Portal freischalten

# Schlusscodes, nach denen es keinen Sinn hat, es noch einmal zu versuchen
CLOSE_AUTH_FAILED = 4004
CLOSE_INVALID_INTENTS = 4013
CLOSE_DISALLOWED_INTENTS = 4014
FATAL_CODES = {CLOSE_AUTH_FAILED, 4010, 4011, 4012, CLOSE_INVALID_INTENTS, CLOSE_DISALLOWED_INTENTS}
# Nach diesen Codes ist die Sitzung verloren, es wird neu angemeldet statt fortgesetzt
NEW_SESSION_CODES = {4007, 4009}

REASON_AUTH = "auth"
REASON_INTENTS = "intents"
REASON_OTHER = "other"

MAX_BACKOFF = 60.0

DispatchHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
StatusHandler = Callable[[bool], None]
FatalHandler = Callable[[str], None]


async def _sleep(seconds: float) -> None:
    """Warten (eigene Funktion, damit Tests nicht wirklich warten müssen)."""
    await asyncio.sleep(seconds)


class GatewayFatal(Exception):
    """Discord lehnt die Anmeldung endgültig ab."""

    def __init__(self, reason: str, code: int | None) -> None:
        super().__init__(f"{reason} ({code})")
        self.reason = reason
        self.code = code


class GatewayClient:
    """Eine Gateway-Verbindung eines Bots."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        intents: int,
        on_dispatch: DispatchHandler,
        *,
        on_status: StatusHandler | None = None,
        on_fatal: FatalHandler | None = None,
    ) -> None:
        self._session = session
        self._token = token
        self._intents = intents
        self._on_dispatch = on_dispatch
        self._on_status = on_status
        self._on_fatal = on_fatal
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._closing = False
        self._session_id: str | None = None
        self._resume_url: str | None = None
        self._seq: int | None = None
        self._ack = True
        self._heartbeat_sent = 0.0
        self._tasks: set[asyncio.Task[None]] = set()
        self._failures = 0
        self.connected = False
        self.latency: float | None = None

    # ------------------------------------------------------------------ Lauf
    async def run(self) -> None:
        """Verbinden und verbunden bleiben, bis `close` aufgerufen wird oder Discord endgültig ablehnt."""
        while not self._closing:
            try:
                await self._run_once()
            except GatewayFatal as err:
                self._set_connected(False)
                _LOGGER.error("Discord lehnt die Verbindung endgültig ab: %s", err)
                if self._on_fatal:
                    self._on_fatal(err.reason)
                return
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.debug("Verbindung zu Discord abgebrochen: %s", type(err).__name__)
            except Exception:
                _LOGGER.exception("Unerwarteter Fehler in der Verbindung zu Discord")
            self._set_connected(False)
            if self._closing:
                break
            self._failures += 1
            await _sleep(min(2.0 ** (self._failures - 1), MAX_BACKOFF))

    async def close(self) -> None:
        """Verbindung beenden und alle laufenden Aufgaben abbrechen."""
        self._closing = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        for task in list(self._tasks):
            task.cancel()
        self._set_connected(False)

    def _set_connected(self, connected: bool) -> None:
        if connected != self.connected:
            self.connected = connected
            if not connected:
                self.latency = None
            if self._on_status:
                self._on_status(connected)

    # ------------------------------------------------------------------ eine Verbindung
    async def _run_once(self) -> None:
        url = f"{self._resume_url or GATEWAY_URL}{GATEWAY_QUERY}"
        ws = await self._session.ws_connect(url, heartbeat=None, max_msg_size=0)
        self._ws = ws
        heartbeat: asyncio.Task[None] | None = None
        try:
            hello = await self._next(ws)
            if not hello or hello.get("op") != OP_HELLO:
                return
            interval = hello["d"]["heartbeat_interval"] / 1000
            self._ack = True
            heartbeat = asyncio.create_task(self._heartbeat(ws, interval))
            await self._login(ws)
            while True:
                message = await self._next(ws)
                if message is None:
                    self._handle_close(ws.close_code)
                    return
                if not await self._handle(ws, message):
                    return
        finally:
            if heartbeat:
                heartbeat.cancel()
            if not ws.closed:
                await ws.close()
            self._ws = None

    async def _next(self, ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any] | None:
        """Das nächste Paket als JSON, None wenn die Verbindung zu ist."""
        message = await ws.receive()
        if message.type == aiohttp.WSMsgType.TEXT:
            return json.loads(message.data)
        if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
            return None
        raise aiohttp.ClientError(f"unerwarteter Pakettyp {message.type}")

    def _handle_close(self, code: int | None) -> None:
        if code == CLOSE_AUTH_FAILED:
            raise GatewayFatal(REASON_AUTH, code)
        if code in (CLOSE_INVALID_INTENTS, CLOSE_DISALLOWED_INTENTS):
            raise GatewayFatal(REASON_INTENTS, code)
        if code in FATAL_CODES:
            raise GatewayFatal(REASON_OTHER, code)
        if code in NEW_SESSION_CODES:
            self._reset_session()

    def _reset_session(self) -> None:
        self._session_id = None
        self._resume_url = None
        self._seq = None

    async def _login(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        if self._session_id and self._seq is not None:
            await ws.send_json(
                {"op": OP_RESUME, "d": {"token": self._token, "session_id": self._session_id, "seq": self._seq}}
            )
            return
        await ws.send_json(
            {
                "op": OP_IDENTIFY,
                "d": {
                    "token": self._token,
                    "intents": self._intents,
                    "properties": {"os": "linux", "browser": "discord_hub", "device": "discord_hub"},
                },
            }
        )

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse, interval: float) -> None:
        """Alle `interval` Sekunden einen Herzschlag schicken. Bleibt die Bestätigung aus, ist die Verbindung tot."""
        await _sleep(interval * random.random())
        while True:
            if not self._ack:
                _LOGGER.debug("Discord bestätigt den Herzschlag nicht, die Verbindung wird neu aufgebaut")
                await ws.close(code=4000)
                return
            await self._send_heartbeat(ws)
            await _sleep(interval)

    async def _send_heartbeat(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ack = False
        self._heartbeat_sent = asyncio.get_running_loop().time()
        await ws.send_json({"op": OP_HEARTBEAT, "d": self._seq})

    async def _handle(self, ws: aiohttp.ClientWebSocketResponse, message: dict[str, Any]) -> bool:
        """Ein Paket verarbeiten. False beendet diese Verbindung (der Lauf baut sie neu auf)."""
        op = message.get("op")
        if op == OP_DISPATCH:
            if message.get("s") is not None:
                self._seq = message["s"]
            await self._dispatch(message.get("t") or "", message.get("d") or {})
        elif op == OP_HEARTBEAT:
            await self._send_heartbeat(ws)
        elif op == OP_HEARTBEAT_ACK:
            self._ack = True
            self.latency = asyncio.get_running_loop().time() - self._heartbeat_sent
        elif op == OP_RECONNECT:
            await ws.close(code=4000)  # die Sitzung bleibt erhalten und wird fortgesetzt
            return False
        elif op == OP_INVALID_SESSION:
            if not message.get("d"):
                self._reset_session()
            await _sleep(random.uniform(1, 5))
            await ws.close(code=4000)
            return False
        return True

    async def _dispatch(self, name: str, data: dict[str, Any]) -> None:
        if name == "READY":
            self._session_id = data.get("session_id")
            self._resume_url = data.get("resume_gateway_url")
            self._failures = 0
            self._set_connected(True)
        elif name == "RESUMED":
            self._failures = 0
            self._set_connected(True)
        # jedes Ereignis in einer eigenen Aufgabe, damit ein langsamer Handler den Herzschlag nicht aufhält
        task = asyncio.create_task(self._safely(name, data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safely(self, name: str, data: dict[str, Any]) -> None:
        try:
            await self._on_dispatch(name, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Fehler beim Verarbeiten des Discord-Ereignisses %s", name)
