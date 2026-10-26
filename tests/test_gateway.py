"""Das Gateway: Anmeldung, Herzschlag, Fortsetzen nach Abbrüchen und endgültige Fehler (nachgestellte Verbindung)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from custom_components.discord_hub import gateway
from custom_components.discord_hub.gateway import GatewayClient

HELLO = {"op": 10, "d": {"heartbeat_interval": 41250}}


def dispatch(name: str, seq: int, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"op": 0, "t": name, "s": seq, "d": data or {}}


READY = dispatch("READY", 1, {"session_id": "abc", "resume_gateway_url": "wss://resume.example"})


class FakeWS:
    """Eine Verbindung, die vorbereitete Pakete liefert und die gesendeten merkt."""

    def __init__(self, *packets: dict[str, Any] | int, auto_ack: bool = True) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        for packet in packets:
            self.queue.put_nowait(packet)
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.close_code: int | None = None
        self.auto_ack = auto_ack

    async def receive(self) -> Any:
        packet = await self.queue.get()
        if isinstance(packet, int):  # ein Schlusscode
            self.close_code = packet
            self.closed = True
            return SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=packet)
        return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(packet))

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)
        if self.auto_ack and data["op"] == 1:
            self.queue.put_nowait({"op": 11})

    async def close(self, code: int = 1000) -> None:
        if not self.closed:
            self.closed = True
            self.close_code = code
            self.queue.put_nowait(code)


class FakeSession:
    def __init__(self, *connections: FakeWS) -> None:
        self.connections = list(connections)
        self.urls: list[str] = []

    async def ws_connect(self, url: str, **_kwargs: Any) -> FakeWS:
        self.urls.append(url)
        if not self.connections:
            raise aiohttp.ClientError("keine Verbindung mehr vorbereitet")
        return self.connections.pop(0)


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def short(seconds: float) -> None:
        await asyncio.sleep(min(seconds, 0.01))

    monkeypatch.setattr(gateway, "_sleep", short)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.status: list[bool] = []
        self.fatal: list[str] = []

    async def on_dispatch(self, name: str, data: dict[str, Any]) -> None:
        self.events.append((name, data))

    def client(self, session: FakeSession, intents: int = 3) -> GatewayClient:
        return GatewayClient(
            session,  # type: ignore[arg-type]
            "geheimer-token",
            intents,
            self.on_dispatch,
            on_status=self.status.append,
            on_fatal=self.fatal.append,
        )


async def test_identify_dispatch_and_fatal_auth_error():
    ws = FakeWS(HELLO, READY, dispatch("INTERACTION_CREATE", 2, {"id": "9"}), 4004)
    recorder = Recorder()
    await recorder.client(FakeSession(ws), intents=1025).run()
    await asyncio.sleep(0)
    identify = next(p for p in ws.sent if p["op"] == 2)
    assert identify["d"]["token"] == "geheimer-token"
    assert identify["d"]["intents"] == 1025
    assert [name for name, _ in recorder.events] == ["READY", "INTERACTION_CREATE"]
    assert recorder.status == [True, False]
    assert recorder.fatal == ["auth"]


@pytest.mark.parametrize("code", [4013, 4014])
async def test_missing_intents_are_fatal(code):
    recorder = Recorder()
    await recorder.client(FakeSession(FakeWS(HELLO, code))).run()
    assert recorder.fatal == ["intents"]


async def test_heartbeat_carries_the_sequence_and_measures_latency():
    ws = FakeWS(HELLO, READY, dispatch("X", 7))
    client = Recorder().client(FakeSession(ws))
    task = asyncio.create_task(client.run())
    for _ in range(100):
        await asyncio.sleep(0.01)
        if client.latency is not None and len([p for p in ws.sent if p["op"] == 1]) >= 2:
            break
    await client.close()
    await asyncio.wait_for(task, 2)
    beats = [p for p in ws.sent if p["op"] == 1]
    assert len(beats) >= 2
    assert beats[-1]["d"] == 7


async def test_resume_after_a_dropped_connection():
    first = FakeWS(HELLO, READY, dispatch("X", 5), 1006)
    second = FakeWS(HELLO, dispatch("RESUMED", 6), 4004)
    session = FakeSession(first, second)
    recorder = Recorder()
    await recorder.client(session).run()
    resume = next(p for p in second.sent if p["op"] in (2, 6))
    assert resume["op"] == 6
    assert resume["d"] == {"token": "geheimer-token", "session_id": "abc", "seq": 5}
    assert session.urls[1].startswith("wss://resume.example")
    assert recorder.status == [True, False, True, False]


async def test_invalid_session_without_resume_identifies_again():
    first = FakeWS(HELLO, READY, {"op": 9, "d": False})
    second = FakeWS(HELLO, 4004)
    await Recorder().client(FakeSession(first, second)).run()
    assert next(p for p in second.sent if p["op"] in (2, 6))["op"] == 2


async def test_reconnect_request_keeps_the_session():
    first = FakeWS(HELLO, READY, {"op": 7, "d": None})
    second = FakeWS(HELLO, 4004)
    await Recorder().client(FakeSession(first, second)).run()
    assert next(p for p in second.sent if p["op"] in (2, 6))["op"] == 6


async def test_expired_session_close_code_starts_a_new_session():
    first = FakeWS(HELLO, READY, 4009)
    second = FakeWS(HELLO, 4004)
    await Recorder().client(FakeSession(first, second)).run()
    assert next(p for p in second.sent if p["op"] in (2, 6))["op"] == 2


async def test_missing_heartbeat_ack_rebuilds_the_connection():
    first = FakeWS(HELLO, READY, auto_ack=False)
    second = FakeWS(HELLO, 4004)
    await Recorder().client(FakeSession(first, second)).run()
    assert first.close_code == 4000
    assert next(p for p in second.sent if p["op"] in (2, 6))["op"] == 6


async def test_a_failing_handler_does_not_break_the_connection(caplog):
    ws = FakeWS(HELLO, READY, dispatch("BOOM", 2), dispatch("OK", 3), 4004)
    seen: list[str] = []

    async def handler(name: str, data: dict[str, Any]) -> None:
        seen.append(name)
        if name == "BOOM":
            raise RuntimeError("kaputt")

    client = GatewayClient(FakeSession(ws), "t", 1, handler)  # type: ignore[arg-type]
    await client.run()
    await asyncio.sleep(0)
    assert seen == ["READY", "BOOM", "OK"]
    assert "BOOM" in caplog.text


async def test_connection_errors_are_retried():
    session = FakeSession()  # die erste Verbindung scheitert, die zweite kommt
    ws = FakeWS(HELLO, 4004)
    original = session.ws_connect
    calls = {"n": 0}

    async def flaky(url: str, **kwargs: Any) -> FakeWS:
        calls["n"] += 1
        if calls["n"] == 1:
            raise aiohttp.ClientError("weg")
        session.connections.append(ws)
        return await original(url, **kwargs)

    session.ws_connect = flaky  # type: ignore[method-assign]
    await Recorder().client(session).run()
    assert calls["n"] == 2


async def test_close_ends_the_run_and_clears_the_state():
    ws = FakeWS(HELLO, READY)
    recorder = Recorder()
    client = recorder.client(FakeSession(ws))
    task = asyncio.create_task(client.run())
    for _ in range(20):
        await asyncio.sleep(0.01)
        if client.connected:
            break
    assert client.connected
    await client.close()
    await asyncio.wait_for(task, 2)
    assert not client.connected
    assert client.latency is None
    assert recorder.status[-1] is False
