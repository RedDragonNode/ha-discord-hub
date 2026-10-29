"""Der Dialog zum Anlegen und Bearbeiten von Meldungen."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from .conftest import FORUM_SUB, TEXT_SUB, USER_SUB, bot_entry, notice_subentry, setup_entry


async def _start(hass, entry, template: str):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"template": template})
    assert result["step_id"] == "notice"
    return result


def _suggested(result) -> dict:
    return {k.schema: k.description["suggested_value"] for k in result["data_schema"].schema if k.description}


NOTICE = {"target": TEXT_SUB, "title": "", "message": "", "embed": True, "snapshot": False, "cooldown": 0}


async def test_add_a_notice_with_the_texts_of_the_template(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "spiel_saison_recording_started")
    suggested = _suggested(result)
    assert suggested["title"] == "Recording started"
    assert "trigger.season" in suggested["message"]
    # die Texte unverändert abschicken: gespeichert wird nichts, die Meldung folgt dann der Sprache
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"title": suggested["title"], "message": suggested["message"], "cooldown": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Spiel Saison: recording started › #allgemein"
    assert result["data"] == {
        "template": "spiel_saison_recording_started",
        "target": TEXT_SUB,
        "title": "",
        "message": "",
        "embed": True,
        "snapshot": False,
        "camera": "",
        "cooldown": 30,
    }


async def test_a_changed_text_is_kept(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "spiel_saison_season_ended")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"title": "Ende", "message": "{{ trigger.partner }} ist fertig"}
    )
    assert result["data"]["title"] == "Ende"
    assert result["data"]["message"] == "{{ trigger.partner }} ist fertig"


async def test_a_state_notice_needs_an_entity(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "cam_profile_started")
    fields = {k.schema for k in result["data_schema"].schema}
    assert "entity_id" in fields
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"entity_id": "binary_sensor.profil_aufnahme"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["entity_id"] == "binary_sensor.profil_aufnahme"


async def test_a_custom_event_needs_a_name_and_a_custom_state_may_name_a_value(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], NOTICE | {"event_type": "  "})
    assert result["errors"] == {"base": "invalid_event_type"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": " mein_ereignis "}
    )
    assert result["data"]["event_type"] == "mein_ereignis"
    result = await _start(hass, entry, "custom_state")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"entity_id": "sensor.tuer", "state_to": " offen "}
    )
    assert result["data"]["state_to"] == "offen"


async def test_broken_templates_are_refused(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    for field in ("title", "message"):
        broken = await hass.config_entries.subentries.async_configure(
            result["flow_id"], NOTICE | {"event_type": "x", field: "{{ trigger.x "}
        )
        assert broken["errors"] == {"base": "invalid_template"}


async def test_the_snapshot_needs_a_camera(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": "x", "snapshot": True}
    )
    assert refused["errors"] == {"base": "camera_needed"}
    created = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": "x", "snapshot": True, "camera": "camera.fuchsauge"}
    )
    assert created["data"]["camera"] == "camera.fuchsauge"


async def test_a_recording_started_notice_takes_its_cameras_from_the_event(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "spiel_saison_recording_started")
    assert _suggested(result)["snapshot"] is True  # vorbelegt, ohne feste Kamera
    created = await hass.config_entries.subentries.async_configure(result["flow_id"], NOTICE | {"snapshot": True})
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert created["data"]["snapshot"] is True
    assert created["data"]["camera"] == ""


async def test_a_state_notice_without_a_camera_on_its_device_needs_one(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "ctronics_motion")  # der Schnappschuss ist hier vorbelegt
    refused = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"entity_id": "binary_sensor.ohne_geraet", "snapshot": True, "cooldown": 300}
    )
    assert refused["errors"] == {"base": "camera_needed"}


async def test_an_unknown_target_is_refused(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    with pytest.raises(InvalidData):  # die Auswahl lässt nur vorhandene Ziele zu
        await hass.config_entries.subentries.async_configure(
            result["flow_id"], NOTICE | {"event_type": "x", "target": "weg"}
        )


async def test_a_forum_target_asks_for_the_thread(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": "x", "target": FORUM_SUB}
    )
    assert result["step_id"] == "forum"
    assert "Notices" in _suggested(result)["thread_name"]
    refused = await hass.config_entries.subentries.async_configure(result["flow_id"], {"thread_name": "{{ kaputt "})
    assert refused["errors"] == {"base": "invalid_template"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"thread_name": "Bericht", "tags": [" Fuchs ", ""], "daily": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Own event › fuchs"
    assert result["data"]["thread_name"] == "Bericht"
    assert result["data"]["tags"] == ["Fuchs"]
    assert result["data"]["daily"] is False


async def test_the_default_thread_name_is_not_stored(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": "x", "target": FORUM_SUB}
    )
    default = _suggested(result)["thread_name"]
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"thread_name": default})
    assert result["data"]["thread_name"] == ""


async def test_a_direct_message_is_a_target_without_a_thread_step(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, "custom_event")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"event_type": "x", "target": USER_SUB}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_without_a_target_there_is_nothing_to_add(hass, discord):
    entry = await setup_entry(hass, _bot_without_targets())
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_targets"


def _bot_without_targets():
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.discord_hub.const import CONF_KIND, CONF_TOKEN, DOMAIN, KIND_BOT

    from .conftest import BOT_ID, TOKEN

    return MockConfigEntry(domain=DOMAIN, title="Leer", unique_id=BOT_ID, data={CONF_KIND: KIND_BOT, CONF_TOKEN: TOKEN})


async def test_reconfigure_a_notice(hass, discord):
    entry = await setup_entry(
        hass, bot_entry([notice_subentry("spiel_saison_recording_started", title="", message="Eigener Text")])
    )
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "notice")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id}
    )
    assert result["step_id"] == "notice"
    suggested = _suggested(result)
    assert suggested["message"] == "Eigener Text"
    assert suggested["title"] == "Recording started"  # leer gespeichert zeigt den Text der Vorlage
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"message": "Neuer Text", "cooldown": 60, "target": USER_SUB}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    updated = entry.subentries[sub.subentry_id]
    assert updated.data["message"] == "Neuer Text"
    assert updated.data["cooldown"] == 60
    assert updated.data["target"] == USER_SUB
    assert updated.title == "Spiel Saison: recording started › Stefan"


async def test_reconfigure_sends_back_what_the_form_suggests(hass, discord):
    entry = await setup_entry(hass, bot_entry([notice_subentry("custom_event", event_type="x")]))
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "notice")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id}
    )
    suggested = _suggested(result)
    assert "camera" not in suggested  # eine leere Kamera lehnt die Auswahl ab
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], suggested)
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.subentries[sub.subentry_id].data["camera"] == ""


async def test_reconfigure_a_forum_notice_keeps_its_thread_settings(hass, discord):
    entry = await setup_entry(
        hass,
        bot_entry(
            [notice_subentry("custom_event", target=FORUM_SUB, event_type="x", thread_name="Bericht", tags=["Fuchs"])]
        ),
    )
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "notice")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTICE | {"target": FORUM_SUB, "event_type": "x"}
    )
    assert result["step_id"] == "forum"
    assert _suggested(result)["thread_name"] == "Bericht"
    assert _suggested(result)["tags"] == ["Fuchs"]


async def test_reconfigure_a_notice_with_an_unknown_template(hass, discord):
    entry = await setup_entry(hass, bot_entry([notice_subentry("gibt_es_nicht")]))
    sub = next(s for s in entry.subentries.values() if s.subentry_type == "notice")
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "notice"), context={"source": SOURCE_RECONFIGURE, "subentry_id": sub.subentry_id}
    )
    assert result["reason"] == "unknown_template"


@pytest.mark.parametrize("template", ["spiel_saison_recording_started", "ctronics_motion", "custom_state"])
async def test_every_form_builds(hass, discord, template):
    entry = await setup_entry(hass, bot_entry())
    result = await _start(hass, entry, template)
    assert result["type"] is FlowResultType.FORM
