"""Meldungen ausführen: auf Ereignisse und Entities hören, den Text rendern und senden.

Eine Meldung darf Home Assistant nie stören: Ein Fehler beim Rendern oder Senden steht als Zeile im Protokoll, mehr
passiert nicht. Mit einem Mindestabstand fluten häufige Quellen (Bewegung) den Kanal nicht.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.template import Template

from .api import Attachment
from .const import (
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_USER_ID,
    FORUM_CHANNELS,
    MAX_EMBEDS,
    MAX_FILES,
    SUBENTRY_CHANNEL,
    SUBENTRY_USER,
)
from .files import async_load_attachments
from .notices import DEFAULT_THREAD_NAME, KIND_EVENT, NoticeConfig, language_of, notices_of

if TYPE_CHECKING:
    from .runtime import DiscordRuntime

_LOGGER = logging.getLogger(__name__)

_IGNORED_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _now() -> float:
    """Die Uhr für den Mindestabstand (eigene Funktion, damit Tests sie vorstellen können)."""
    return time.monotonic()


class NoticeRunner:
    """Die Meldungen eines Bots: hört zu, rendert und sendet."""

    def __init__(self, runtime: DiscordRuntime) -> None:
        self.runtime = runtime
        self.hass: HomeAssistant = runtime.hass
        self.entry = runtime.entry
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._last: dict[tuple[str, str], float] = {}
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ Start und Ende
    @callback
    def async_start(self) -> None:
        for notice in notices_of(self.entry).values():
            if not notice.listens_to:
                continue
            if notice.template.kind == KIND_EVENT:
                self._unsubscribe.append(self.hass.bus.async_listen(notice.event_type, self._event_handler(notice)))
            else:
                self._unsubscribe.append(
                    async_track_state_change_event(self.hass, [notice.entity_id], self._state_handler(notice))
                )

    @callback
    def async_stop(self) -> None:
        while self._unsubscribe:
            self._unsubscribe.pop()()

    # ------------------------------------------------------------------ Auslöser
    def _event_handler(self, notice: NoticeConfig) -> Callable[[Event], None]:
        @callback
        def handle(event: Event) -> None:
            trigger = {
                "platform": "event",
                **event.data,
                "event_type": event.event_type,
                # wie im Auslöser einer Automation, damit sich deren Texte übernehmen lassen
                "event": {"event_type": event.event_type, "data": dict(event.data)},
            }
            self._start(notice, "", {"trigger": trigger})

        return handle

    def _state_handler(self, notice: NoticeConfig) -> Callable[[Event[EventStateChangedData]], None]:
        @callback
        def handle(event: Event[EventStateChangedData]) -> None:
            old, new = event.data["old_state"], event.data["new_state"]
            if not self._state_matches(notice, old, new):
                return
            assert new is not None
            trigger = {
                "platform": "state",
                "entity_id": new.entity_id,
                "name": new.name,
                "from_state": old,
                "to_state": new,
            }
            self._start(notice, new.entity_id, {"trigger": trigger})

        return handle

    @staticmethod
    def _state_matches(notice: NoticeConfig, old: State | None, new: State | None) -> bool:
        """Zählt der Wechsel? Nicht, wenn die Entity gerade erst entsteht, ausfällt oder wiederkommt."""
        if old is None or new is None:
            return False
        if old.state in _IGNORED_STATES or new.state in _IGNORED_STATES or old.state == new.state:
            return False
        wanted = notice.wanted_state
        return wanted is None or new.state == wanted

    # ------------------------------------------------------------------ Senden
    @callback
    def _start(self, notice: NoticeConfig, source: str, variables: dict[str, Any]) -> None:
        """Den Mindestabstand prüfen und das Senden im Hintergrund starten."""
        now = _now()
        key = (notice.subentry_id, source)
        last = self._last.get(key)
        if notice.cooldown and last is not None and now - last < notice.cooldown:
            _LOGGER.debug("Die Meldung %s wartet noch auf ihren Mindestabstand", notice.template.key)
            return
        self._last[key] = now
        self.entry.async_create_background_task(
            self.hass, self._send(notice, variables), f"discord_hub notice {notice.template.key}"
        )

    def _render(self, text: str, variables: dict[str, Any]) -> str:
        return Template(text, self.hass).async_render(variables, parse_result=False).strip()

    async def _send(self, notice: NoticeConfig, variables: dict[str, Any]) -> None:
        try:
            await self._deliver(notice, variables)
        except TemplateError as err:
            _LOGGER.warning("Der Text der Meldung %s ließ sich nicht rendern: %s", notice.template.key, err)
        except HomeAssistantError as err:
            _LOGGER.warning("Die Meldung %s ließ sich nicht senden: %s", notice.template.key, err)
        except Exception:
            _LOGGER.exception("Unerwarteter Fehler bei der Meldung %s", notice.template.key)

    async def _deliver(self, notice: NoticeConfig, variables: dict[str, Any]) -> None:
        language = language_of(self.hass)
        title = self._render(notice.text("title", language), variables)
        message = self._render(notice.text("message", language), variables)
        thread_name = self._render(notice.thread_name or DEFAULT_THREAD_NAME[language], variables) or title
        target = await self._resolve_target(notice)
        if target is None:
            return
        channel_id, is_forum = target
        main = {"title": title, "description": message, "color": notice.embed_color, "timestamp": True}
        text = None if notice.embed else (f"**{title}**\n{message}" if title else message)
        snapshots = await self._snapshots(notice, variables) if notice.snapshot else []
        if snapshots:
            # als Embed bekommt jede Kamera ihr eigenes in der Farbe der Meldung, sonst hängen die Bilder an
            embeds = [main, *self._picture_embeds(notice, snapshots)] if notice.embed else None
            try:
                await self._post(
                    notice, channel_id, is_forum, thread_name, text, embeds, [file for _, file in snapshots]
                )
            except HomeAssistantError as err:
                _LOGGER.warning("Die Meldung %s ging mit den Schnappschüssen nicht: %s", notice.template.key, err)
            else:
                return
        await self._post(notice, channel_id, is_forum, thread_name, text, [main] if notice.embed else None, None)

    async def _snapshots(self, notice: NoticeConfig, variables: dict[str, Any]) -> list[tuple[str, Attachment]]:
        """Die Bilder der Kameras als (Kamera, Datei), alle zugleich. Ein Bild, das fehlt, fällt allein weg."""
        limit = MAX_EMBEDS - 1 if notice.embed else MAX_FILES  # neben dem Text-Embed bleibt Platz für neun
        cameras = self._cameras(notice, variables)[:limit]
        results = await asyncio.gather(*(self._snapshot(notice, camera) for camera in cameras))
        return [result for result in results if result]

    async def _snapshot(self, notice: NoticeConfig, camera: str) -> tuple[str, Attachment] | None:
        try:
            [file] = await async_load_attachments(self.hass, [{"camera": camera}])
        except HomeAssistantError as err:
            _LOGGER.warning("Der Schnappschuss von %s fehlt in der Meldung %s: %s", camera, notice.template.key, err)
            return None
        return camera, file

    def _picture_embeds(self, notice: NoticeConfig, snapshots: list[tuple[str, Attachment]]) -> list[dict[str, Any]]:
        """Je Kamera ein Embed mit ihrem Namen und ihrem Bild."""
        return [
            {
                "title": state.name if (state := self.hass.states.get(camera)) else camera,
                "color": notice.camera_color(camera),
                "image": f"attachment://{file.filename}",
            }
            for camera, file in snapshots
        ]

    async def _post(
        self,
        notice: NoticeConfig,
        channel_id: str,
        is_forum: bool,
        thread_name: str,
        text: str | None,
        embeds: list[dict[str, Any]] | None,
        files: list[Attachment] | None,
    ) -> None:
        if is_forum:
            await self.runtime.forum_post(
                channel_id,
                thread_name=thread_name,
                message=text,
                embeds=embeds,
                files=files,
                tags=list(notice.tags) or None,
                daily=notice.daily,
                key=f"notice_{thread_name}",  # gleicher Name im selben Forum, gleicher Tages-Thread
            )
        else:
            await self.runtime.send_message(channel_id, message=text, embeds=embeds, files=files)

    # ------------------------------------------------------------------ Ziel und Kamera
    async def _resolve_target(self, notice: NoticeConfig) -> tuple[str, bool] | None:
        """(Kanal-ID, ob es ein Forum ist). None, wenn es das Ziel nicht mehr gibt."""
        subentry = self.entry.subentries.get(notice.target_id)
        if subentry is None:
            if notice.subentry_id not in self._warned:
                self._warned.add(notice.subentry_id)
                _LOGGER.warning(
                    "Das Ziel der Meldung %s gibt es nicht mehr, sie wird nicht gesendet", notice.template.key
                )
            return None
        if subentry.subentry_type == SUBENTRY_USER:
            return await self.runtime.dm_channel(str(subentry.data[CONF_USER_ID])), False
        if subentry.subentry_type == SUBENTRY_CHANNEL:
            return str(subentry.data[CONF_CHANNEL_ID]), int(subentry.data.get(CONF_CHANNEL_TYPE, 0)) in FORUM_CHANNELS
        return None

    def _cameras(self, notice: NoticeConfig, variables: dict[str, Any]) -> list[str]:
        """Die Kameras für die Schnappschüsse: die gewählte, sonst die des Ereignisses oder am Gerät der Quelle."""
        if notice.camera:
            return [notice.camera]
        if key := notice.template.cams_key:
            cams = variables["trigger"].get(key)
            found = [cam for cam in cams if isinstance(cam, str) and cam.startswith("camera.")] if cams else []
            return list(dict.fromkeys(found))[:MAX_FILES]
        camera = camera_of_device(self.hass, notice.entity_id)
        return [camera] if camera else []


def camera_of_device(hass: HomeAssistant, entity_id: str) -> str | None:
    """Die Kamera-Entity auf demselben Gerät wie `entity_id` (bei Ctronics: Bewegungs-Sensor und Kamera)."""
    registry = er.async_get(hass)
    if not entity_id or not (entry := registry.async_get(entity_id)) or not entry.device_id:
        return None
    for sibling in er.async_entries_for_device(registry, entry.device_id):
        if sibling.domain == "camera" and not sibling.disabled:
            return sibling.entity_id
    return None
