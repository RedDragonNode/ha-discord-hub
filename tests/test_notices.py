"""Meldungen: Ereignisse und Sensoren werden zu Nachrichten, mit Mindestabstand und ohne Home Assistant zu stören."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.discord_hub import files, notice_runner
from custom_components.discord_hub.notice_runner import camera_of_device
from custom_components.discord_hub.notices import TEMPLATES, NoticeTemplate, language_of, parse_notice

from .conftest import (
    API,
    FORUM_ID,
    FORUM_SUB,
    TEXT_ID,
    USER_ID,
    USER_SUB,
    bot_entry,
    notice_subentry,
    payload_of,
    setup_entry,
)

SENSOR = "binary_sensor.fuchsauge_bewegung"


async def settle(hass: HomeAssistant) -> None:
    """Warten, bis Meldungen im Hintergrund gesendet sind (`async_block_till_done` wartet auf sie nicht)."""
    for _ in range(30):
        await asyncio.sleep(0)
    await hass.async_block_till_done()


def mock_text_channel(discord) -> None:
    discord.post(f"{API}/channels/{TEXT_ID}/messages", json={"id": "9", "channel_id": TEXT_ID})


def messages(discord, channel_id: str = TEXT_ID) -> list[Any]:
    """Die Bodies der Nachrichten, die in den Kanal gingen."""
    return [
        c[2]
        for c in discord.mock_calls
        if c[0].upper() == "POST" and c[1].path.endswith(f"/channels/{channel_id}/messages")
    ]


def started(**changes: Any) -> dict[str, Any]:
    return {
        "partner": "Fuchs",
        "nickname": "Fuchsi",
        "partner_id": "p1",
        "season": 3,
        "recording": 7,
        "place": "Wiese",
        "cams": ["a", "b"],
    } | changes


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Die Uhr des Mindestabstands: `clock[0]` vorstellen."""
    now = [1000.0]
    monkeypatch.setattr(notice_runner, "_now", lambda: now[0])
    return now


# ---------------------------------------------------------------- Vorlagen
@pytest.mark.parametrize("template", list(TEMPLATES.values()), ids=list(TEMPLATES))
async def test_every_template_is_complete_and_valid(hass, template: NoticeTemplate):
    from homeassistant.helpers.template import Template

    for language in ("de", "en"):
        assert template.label[language]
        for field in (template.title, template.message):
            assert field[language]
            Template(field[language], hass).ensure_valid()


def test_a_notice_without_a_known_template_is_ignored():
    assert parse_notice("x", {"template": "gibt_es_nicht"}) is None


async def test_the_language_follows_home_assistant(hass):
    assert language_of(hass) == "en"
    hass.config.language = "de-AT"
    assert language_of(hass) == "de"


# ---------------------------------------------------------------- Ereignisse
async def test_an_event_becomes_an_embed(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_started")]))
    hass.bus.async_fire("spiel_saison_recording_started", started())
    await settle(hass)
    [body] = messages(discord)
    [embed] = payload_of(body)["embeds"]
    assert embed["title"] == "Recording started"
    assert embed["description"] == "Fuchsi: season 3, recording 7 in Wiese, 2 camera(s)."
    assert embed["color"] == 0x2ECC71


async def test_the_texts_follow_the_language(hass, discord):
    hass.config.language = "de"
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_started")]))
    hass.bus.async_fire("spiel_saison_recording_started", started(nickname="", place=None))
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["title"] == "Aufnahme gestartet"
    assert embed["description"] == "Fuchs: Saison 3, Aufnahme 7, 2 Kamera(s)."


async def test_own_texts_and_plain_messages(hass, discord):
    mock_text_channel(discord)
    notice = notice_subentry(
        "custom_event", event_type="mein_ereignis", title="Hallo", message="{{ trigger.wer }} ruft", embed=False
    )
    await setup_entry(hass, bot_entry([notice]))
    hass.bus.async_fire("mein_ereignis", {"wer": "Fuchs"})
    hass.bus.async_fire("ein_anderes_ereignis", {"wer": "Hase"})
    await settle(hass)
    [body] = messages(discord)
    payload = payload_of(body)
    assert payload["content"] == "**Hallo**\nFuchs ruft"
    assert "embeds" not in payload


async def test_texts_of_an_automation_work_too(hass, discord):
    mock_text_channel(discord)
    notice = notice_subentry(
        "custom_event",
        event_type="mein_ereignis",
        message="{{ trigger.event.data.wer }} ruft ({{ trigger.event.event_type }})",
    )
    await setup_entry(hass, bot_entry([notice]))
    hass.bus.async_fire("mein_ereignis", {"wer": "Fuchs"})
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["description"] == "Fuchs ruft (mein_ereignis)"


async def test_the_season_end_uses_the_numbers_of_the_event(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_season_ended")]))
    hass.bus.async_fire(
        "spiel_saison_season_ended",
        {"partner": "Fuchs", "nickname": None, "season": 2, "recordings": 4, "seconds": 5400},
    )
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["description"] == "Fuchs: season 2 has ended, 4 recordings, 1.5 hours."


async def test_the_stop_event_shows_the_duration(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_stopped")]))
    hass.bus.async_fire(
        "spiel_saison_recording_stopped",
        {"partner": "Fuchs", "nickname": "Fuchsi", "season": 2, "recording": 4, "reason": "manual", "duration_s": 150},
    )
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["description"] == "Fuchsi: season 2, recording 4, duration 2.5 minutes (manual)."


# ---------------------------------------------------------------- Mindestabstand
async def test_the_minimum_interval_holds_back_repeated_events(hass, discord, clock):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="ping", cooldown=300)]))
    hass.bus.async_fire("ping")
    await settle(hass)
    clock[0] += 299
    hass.bus.async_fire("ping")
    await settle(hass)
    assert len(messages(discord)) == 1
    clock[0] += 2
    hass.bus.async_fire("ping")
    await settle(hass)
    assert len(messages(discord)) == 2


async def test_without_an_interval_every_event_is_sent(hass, discord, clock):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="ping", cooldown=0)]))
    for _ in range(3):
        hass.bus.async_fire("ping")
    await settle(hass)
    assert len(messages(discord)) == 3


# ---------------------------------------------------------------- Entities
async def test_a_state_change_to_the_wanted_state_is_sent(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("ctronics_motion", entity_id=SENSOR, cooldown=0)]))
    hass.states.async_set(SENSOR, "off", {"friendly_name": "Fuchsauge Bewegung"})
    hass.states.async_set(SENSOR, "on", {"friendly_name": "Fuchsauge Bewegung"})
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["title"] == "Motion detected"
    assert embed["description"].startswith("Fuchsauge Bewegung at ")


async def test_other_changes_do_not_count(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("ctronics_motion", entity_id=SENSOR, cooldown=0)]))
    hass.states.async_set(SENSOR, "unavailable")  # entsteht erst
    hass.states.async_set(SENSOR, "on")  # kommt wieder, kein Ereignis
    hass.states.async_set(SENSOR, "on", {"extra": 1})  # nur ein Attribut
    hass.states.async_set(SENSOR, "off")  # falsche Richtung
    hass.states.async_set(SENSOR, "unknown")
    hass.states.async_set(SENSOR, "on")  # kommt aus „unknown“
    await settle(hass)
    assert messages(discord) == []


async def test_the_state_notice_gets_the_attributes_of_the_entity(hass, discord):
    mock_text_channel(discord)
    await setup_entry(
        hass, bot_entry([notice_subentry("cam_profile_started", entity_id="binary_sensor.profil_aufnahme")])
    )
    hass.states.async_set("binary_sensor.profil_aufnahme", "off", {"friendly_name": "Profil Treppe"})
    hass.states.async_set(
        "binary_sensor.profil_aufnahme", "on", {"friendly_name": "Profil Treppe", "folder": "Überwachung/Treppe"}
    )
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["description"] == "Profil Treppe: recording started (folder Überwachung/Treppe)."


async def test_the_minimum_interval_also_holds_for_a_state_notice(hass, discord, clock):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("ctronics_motion", entity_id=SENSOR, cooldown=300)]))
    for _ in range(2):
        hass.states.async_set(SENSOR, "off")
        hass.states.async_set(SENSOR, "on")
        await settle(hass)
    assert len(messages(discord)) == 1


async def test_a_custom_state_can_wait_for_one_value(hass, discord):
    mock_text_channel(discord)
    notice = notice_subentry("custom_state", entity_id="sensor.tuer", state_to="offen")
    await setup_entry(hass, bot_entry([notice]))
    hass.states.async_set("sensor.tuer", "zu")
    hass.states.async_set("sensor.tuer", "angelehnt")
    hass.states.async_set("sensor.tuer", "offen")
    await settle(hass)
    [embed] = payload_of(messages(discord)[0])["embeds"]
    assert embed["description"] == "tuer: offen"
    assert len(messages(discord)) == 1


async def test_a_custom_state_without_a_value_reports_every_change(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("custom_state", entity_id="sensor.tuer")]))
    hass.states.async_set("sensor.tuer", "zu")
    hass.states.async_set("sensor.tuer", "angelehnt")
    hass.states.async_set("sensor.tuer", "offen")
    await settle(hass)
    assert len(messages(discord)) == 2


# ---------------------------------------------------------------- Ziele
async def test_a_notice_to_a_forum_uses_the_daily_thread(hass, discord):
    discord.post(f"{API}/channels/{FORUM_ID}/threads", json={"id": "T1", "message": {"id": "M1"}})
    discord.post(f"{API}/channels/T1/messages", json={"id": "M2", "channel_id": "T1"})
    notice = notice_subentry("custom_event", target=FORUM_SUB, event_type="ping", thread_name="Bericht", daily=True)
    await setup_entry(hass, bot_entry([notice]))
    hass.bus.async_fire("ping")
    await settle(hass)
    hass.bus.async_fire("ping")
    await settle(hass)
    threads = [
        c for c in discord.mock_calls if c[0].upper() == "POST" and c[1].path.endswith(f"/channels/{FORUM_ID}/threads")
    ]
    assert len(threads) == 1
    assert payload_of(threads[0][2])["name"] == "Bericht"
    assert len(messages(discord, "T1")) == 1  # der zweite Aufruf schreibt in den Thread


async def _two_forum_notices(hass, discord, first_name: str, second_name: str) -> list:
    discord.post(f"{API}/channels/{FORUM_ID}/threads", json={"id": "T1", "message": {"id": "M1"}})
    discord.post(f"{API}/channels/T1/messages", json={"id": "M2", "channel_id": "T1"})
    first = notice_subentry("custom_event", target=FORUM_SUB, event_type="ping", thread_name=first_name, daily=True)
    second = notice_subentry("spiel_saison_season_started", target=FORUM_SUB, thread_name=second_name, daily=True)
    await setup_entry(hass, bot_entry([first, second]))
    hass.bus.async_fire("ping")
    await settle(hass)
    hass.bus.async_fire("spiel_saison_season_started", {"partner": "Fuchs", "season": 1, "start": "2026-11-01"})
    await settle(hass)
    return [
        c for c in discord.mock_calls if c[0].upper() == "POST" and c[1].path.endswith(f"/channels/{FORUM_ID}/threads")
    ]


async def test_notices_with_the_same_thread_name_share_the_daily_thread(hass, discord):
    threads = await _two_forum_notices(hass, discord, "Bericht", "Bericht")
    assert len(threads) == 1
    assert len(messages(discord, "T1")) == 1  # die zweite Meldung schreibt in den Thread der ersten


async def test_notices_with_other_thread_names_get_their_own_threads(hass, discord):
    threads = await _two_forum_notices(hass, discord, "Bericht", "Saison")
    assert [payload_of(c[2])["name"] for c in threads] == ["Bericht", "Saison"]


async def test_a_forum_notice_without_a_thread_name_gets_one_with_the_date(hass, discord):
    discord.post(f"{API}/channels/{FORUM_ID}/threads", json={"id": "T1", "message": {"id": "M1"}})
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", target=FORUM_SUB, event_type="ping")]))
    hass.bus.async_fire("ping")
    await settle(hass)
    [call] = [c for c in discord.mock_calls if c[1].path.endswith(f"/channels/{FORUM_ID}/threads")]
    assert payload_of(call[2])["name"].startswith("Notices 20")


async def test_a_notice_to_a_direct_message(hass, discord):
    discord.post(f"{API}/users/@me/channels", json={"id": "DM1"})
    discord.post(f"{API}/channels/DM1/messages", json={"id": "9", "channel_id": "DM1"})
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", target=USER_SUB, event_type="ping")]))
    hass.bus.async_fire("ping")
    await settle(hass)
    assert len(messages(discord, "DM1")) == 1
    assert USER_ID in str([c[2] for c in discord.mock_calls if c[1].path.endswith("/users/@me/channels")])


async def test_a_notice_whose_target_is_gone_logs_once_and_sends_nothing(hass, discord, caplog):
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", target="weg", event_type="ping")]))
    for _ in range(2):
        hass.bus.async_fire("ping")
        await settle(hass)
    assert messages(discord) == []
    assert caplog.text.count("gibt es nicht mehr") == 1


# ---------------------------------------------------------------- Schnappschuss
async def test_a_snapshot_is_attached(hass, discord):
    mock_text_channel(discord)
    notice = notice_subentry("custom_event", event_type="ping", snapshot=True, camera="camera.fuchsauge")
    await setup_entry(hass, bot_entry([notice]))
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)) as get_image:
        hass.bus.async_fire("ping")
        await settle(hass)
    get_image.assert_awaited_once_with(hass, "camera.fuchsauge")
    [body] = messages(discord)
    assert not isinstance(body, dict)  # mit Datei geht die Nachricht als Formular


async def test_a_missing_snapshot_does_not_stop_the_notice(hass, discord, caplog):
    mock_text_channel(discord)
    notice = notice_subentry("custom_event", event_type="ping", snapshot=True, camera="camera.fuchsauge")
    await setup_entry(hass, bot_entry([notice]))
    with patch.object(files.camera, "async_get_image", AsyncMock(side_effect=HomeAssistantError("kein Bild"))):
        hass.bus.async_fire("ping")
        await settle(hass)
    [body] = messages(discord)
    assert isinstance(body, dict)
    assert "camera.fuchsauge" in caplog.text


def _attached(body: Any) -> list[str]:
    """Die Dateinamen, die an einer Nachricht hängen."""
    return [field[0]["filename"] for field in body._fields[1:]]


async def test_a_recording_started_notice_takes_a_snapshot_of_each_camera(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_started", snapshot=True)]))
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")
    cams = ["camera.pirsch", "camera.wiese", "camera.pirsch", "light.keine_kamera"]
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)) as get_image:
        hass.bus.async_fire("spiel_saison_recording_started", started(cams=cams, folder="Spiel_Saison/Fuchs"))
        await settle(hass)
    assert [call.args[1] for call in get_image.await_args_list] == ["camera.pirsch", "camera.wiese"]
    [body] = messages(discord)
    assert _attached(body) == ["pirsch.jpg", "wiese.jpg"]
    [embed] = payload_of(body)["embeds"]
    assert "Folder: Spiel_Saison/Fuchs" in embed["description"]  # Tests laufen mit englischer Sprache


async def test_a_camera_without_an_image_only_drops_its_own_snapshot(hass, discord, caplog):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_started", snapshot=True)]))
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")

    async def get_image(_hass, entity_id):
        if entity_id == "camera.pirsch":
            raise HomeAssistantError("kein Bild")
        return image

    with patch.object(files.camera, "async_get_image", AsyncMock(side_effect=get_image)):
        hass.bus.async_fire("spiel_saison_recording_started", started(cams=["camera.pirsch", "camera.wiese"]))
        await settle(hass)
    [body] = messages(discord)
    assert _attached(body) == ["wiese.jpg"]
    assert "camera.pirsch" in caplog.text


async def test_a_chosen_camera_wins_over_the_cameras_of_the_event(hass, discord):
    mock_text_channel(discord)
    notice = notice_subentry("spiel_saison_recording_started", snapshot=True, camera="camera.fest")
    await setup_entry(hass, bot_entry([notice]))
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)) as get_image:
        hass.bus.async_fire("spiel_saison_recording_started", started(cams=["camera.pirsch", "camera.wiese"]))
        await settle(hass)
    get_image.assert_awaited_once_with(hass, "camera.fest")


async def test_a_recording_started_notice_without_snapshots_sends_text_only(hass, discord):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("spiel_saison_recording_started", snapshot=False)]))
    with patch.object(files.camera, "async_get_image", AsyncMock()) as get_image:
        hass.bus.async_fire("spiel_saison_recording_started", started(cams=["camera.pirsch"]))
        await settle(hass)
    get_image.assert_not_awaited()
    [body] = messages(discord)
    assert isinstance(body, dict)


async def test_the_camera_on_the_same_device_is_found(hass):
    entry = bot_entry()
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("ctronics_cam", "abc")}, name="Fuchsauge"
    )
    registry = er.async_get(hass)
    motion = registry.async_get_or_create(
        "binary_sensor", "ctronics_cam", "abc_motion", device_id=device.id, suggested_object_id="fuchsauge_bewegung"
    )
    assert camera_of_device(hass, motion.entity_id) is None
    camera = registry.async_get_or_create(
        "camera", "ctronics_cam", "abc_cam", device_id=device.id, suggested_object_id="fuchsauge"
    )
    assert camera_of_device(hass, motion.entity_id) == camera.entity_id
    assert camera_of_device(hass, "binary_sensor.gibt_es_nicht") is None
    assert camera_of_device(hass, "") is None


async def test_a_ctronics_notice_takes_the_snapshot_of_its_own_camera(hass, discord):
    mock_text_channel(discord)
    entry = bot_entry(
        [notice_subentry("ctronics_motion", entity_id="binary_sensor.fuchsauge_bewegung", snapshot=True, cooldown=0)]
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("ctronics_cam", "abc")}, name="Fuchsauge"
    )
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "binary_sensor", "ctronics_cam", "abc_motion", device_id=device.id, suggested_object_id="fuchsauge_bewegung"
    )
    registry.async_get_or_create(
        "camera", "ctronics_cam", "abc_cam", device_id=device.id, suggested_object_id="fuchsauge"
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    image = SimpleNamespace(content=b"\xff\xd8jpeg", content_type="image/jpeg")
    with patch.object(files.camera, "async_get_image", AsyncMock(return_value=image)) as get_image:
        hass.states.async_set("binary_sensor.fuchsauge_bewegung", "off")
        hass.states.async_set("binary_sensor.fuchsauge_bewegung", "on")
        await settle(hass)
    get_image.assert_awaited_once_with(hass, "camera.fuchsauge")


# ---------------------------------------------------------------- Fehler stören nicht
async def test_a_broken_template_is_logged_and_nothing_is_sent(hass, discord, caplog):
    mock_text_channel(discord)
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="ping", message="{{ 1 / 0 }}")]))
    hass.bus.async_fire("ping")
    await settle(hass)
    assert messages(discord) == []
    assert "ließ sich nicht rendern" in caplog.text


async def test_a_refusal_by_discord_is_logged(hass, discord, caplog):
    discord.post(
        f"{API}/channels/{TEXT_ID}/messages", status=403, json={"code": 50013, "message": "Missing Permissions"}
    )
    await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="ping")]))
    with caplog.at_level(logging.WARNING):
        hass.bus.async_fire("ping")
        await settle(hass)
    assert "ließ sich nicht senden" in caplog.text


async def test_unloading_stops_the_listening(hass, discord):
    mock_text_channel(discord)
    entry = await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="ping")]))
    await hass.config_entries.async_unload(entry.entry_id)
    hass.bus.async_fire("ping")
    await settle(hass)
    assert messages(discord) == []


async def test_a_webhook_has_no_notices(hass, discord):
    from .conftest import webhook_entry

    entry = await setup_entry(hass, webhook_entry())
    assert entry.runtime_data.notices is None
