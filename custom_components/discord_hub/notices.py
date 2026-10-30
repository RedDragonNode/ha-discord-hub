"""Meldungen: Ereignisse und Sensoren (zum Beispiel von Spiel Saison, Cam Profile und Ctronics) werden zu Nachrichten.

Eine Meldung ist ein Untereintrag eines Bots: Sie hört auf ein Ereignis oder auf den Zustand einer Entity, rendert ihren
Text als Vorlage von Home Assistant und schickt ihn an einen Kanal, ein Forum oder eine Direktnachricht des Bots.
Die Vorlagen hier liefern die Voreinstellungen für die bekannten Quellen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CAMERA,
    CONF_COOLDOWN,
    CONF_DAILY,
    CONF_EMBED,
    CONF_ENTITY_ID,
    CONF_EVENT_TYPE,
    CONF_MESSAGE,
    CONF_SNAPSHOT,
    CONF_STATE_TO,
    CONF_TAGS,
    CONF_TARGET,
    CONF_TEMPLATE,
    CONF_THREAD_NAME,
    CONF_TITLE,
    SUBENTRY_NOTICE,
)

KIND_EVENT = "event"
KIND_STATE = "state"

Texts = dict[str, str]  # Sprache ("de", "en") -> Text


@dataclass(frozen=True)
class NoticeTemplate:
    """Eine Vorlage: worauf sie hört und welchen Text sie von sich aus schickt."""

    key: str
    kind: str  # KIND_EVENT oder KIND_STATE
    label: Texts
    title: Texts
    message: Texts
    color: str = "#3498DB"
    cooldown: int = 0  # Mindestabstand in Sekunden, wenn nichts anderes eingestellt wird
    snapshot: bool = False  # ein Schnappschuss der Kamera hängt standardmäßig an
    event_type: str | None = None  # Ereignis, auf das die Vorlage hört (None: eigenes Ereignis)
    entity_domain: str | None = None  # Auswahl der Entity einschränken
    integration: str | None = None
    device_class: str | None = None
    to_state: str | None = None  # Zustand, bei dem sie auslöst (None: bei jeder Änderung)
    cams_key: str | None = None  # Feld des Ereignisses mit den Kamera-Entities, von denen je ein Schnappschuss kommt


_SS_PARTNER = "{{ trigger.nickname or trigger.partner }}"

TEMPLATES: dict[str, NoticeTemplate] = {
    template.key: template
    for template in (
        NoticeTemplate(
            key="spiel_saison_recording_started",
            kind=KIND_EVENT,
            event_type="spiel_saison_recording_started",
            color="#2ECC71",
            snapshot=True,
            cams_key="cams",
            label={"de": "Spiel Saison: Aufnahme gestartet", "en": "Spiel Saison: recording started"},
            title={"de": "Aufnahme gestartet", "en": "Recording started"},
            message={
                "de": _SS_PARTNER + ": Saison {{ trigger.season }}, Aufnahme {{ trigger.recording }}"
                "{% if trigger.place %} in {{ trigger.place }}{% endif %}, {{ trigger.cams | length }} Kamera(s)."
                "{% if trigger.folder %}\nOrdner: {{ trigger.folder }}{% endif %}"
                "{% if trigger.files %}\nVideos:"
                "{% for file in trigger.files %}\n• {{ file['name'] }}{% endfor %}{% endif %}",
                "en": _SS_PARTNER + ": season {{ trigger.season }}, recording {{ trigger.recording }}"
                "{% if trigger.place %} in {{ trigger.place }}{% endif %}, {{ trigger.cams | length }} camera(s)."
                "{% if trigger.folder %}\nFolder: {{ trigger.folder }}{% endif %}"
                "{% if trigger.files %}\nVideos:"
                "{% for file in trigger.files %}\n• {{ file['name'] }}{% endfor %}{% endif %}",
            },
        ),
        NoticeTemplate(
            key="spiel_saison_recording_stopped",
            kind=KIND_EVENT,
            event_type="spiel_saison_recording_stopped",
            color="#95A5A6",
            label={"de": "Spiel Saison: Aufnahme gestoppt", "en": "Spiel Saison: recording stopped"},
            title={"de": "Aufnahme beendet", "en": "Recording stopped"},
            message={
                "de": _SS_PARTNER + ": Saison {{ trigger.season }}, Aufnahme {{ trigger.recording }}, Dauer "
                "{{ (trigger.duration_s | int(0) / 60) | round(1) }} Minuten ({{ trigger.reason }}).",
                "en": _SS_PARTNER + ": season {{ trigger.season }}, recording {{ trigger.recording }}, duration "
                "{{ (trigger.duration_s | int(0) / 60) | round(1) }} minutes ({{ trigger.reason }}).",
            },
        ),
        NoticeTemplate(
            key="spiel_saison_season_started",
            kind=KIND_EVENT,
            event_type="spiel_saison_season_started",
            color="#3498DB",
            label={"de": "Spiel Saison: Saison gestartet", "en": "Spiel Saison: season started"},
            title={"de": "Neue Saison", "en": "New season"},
            message={
                "de": "{{ trigger.partner }}: Saison {{ trigger.season }} beginnt am {{ trigger.start }}.",
                "en": "{{ trigger.partner }}: season {{ trigger.season }} begins on {{ trigger.start }}.",
            },
        ),
        NoticeTemplate(
            key="spiel_saison_season_ended",
            kind=KIND_EVENT,
            event_type="spiel_saison_season_ended",
            color="#9B59B6",
            label={"de": "Spiel Saison: Saison beendet", "en": "Spiel Saison: season ended"},
            title={"de": "Saison beendet", "en": "Season ended"},
            message={
                "de": _SS_PARTNER + ": Saison {{ trigger.season }} ist zu Ende, {{ trigger.recordings }} Aufnahmen, "
                "{{ (trigger.seconds | int(0) / 3600) | round(1) }} Stunden.",
                "en": _SS_PARTNER + ": season {{ trigger.season }} has ended, {{ trigger.recordings }} recordings, "
                "{{ (trigger.seconds | int(0) / 3600) | round(1) }} hours.",
            },
        ),
        NoticeTemplate(
            key="cam_profile_started",
            kind=KIND_STATE,
            to_state="on",
            entity_domain="binary_sensor",
            integration="cam_profile",
            device_class="running",
            color="#2ECC71",
            label={"de": "Cam Profile: Aufnahme beginnt", "en": "Cam Profile: recording starts"},
            title={"de": "Aufnahme läuft", "en": "Recording"},
            message={
                "de": "{{ trigger.name }}: Aufnahme gestartet"
                "{% if trigger.to_state.attributes.folder %}"
                " (Ordner {{ trigger.to_state.attributes.folder }}){% endif %}.",
                "en": "{{ trigger.name }}: recording started"
                "{% if trigger.to_state.attributes.folder %}"
                " (folder {{ trigger.to_state.attributes.folder }}){% endif %}.",
            },
        ),
        NoticeTemplate(
            key="cam_profile_stopped",
            kind=KIND_STATE,
            to_state="off",
            entity_domain="binary_sensor",
            integration="cam_profile",
            device_class="running",
            color="#95A5A6",
            label={"de": "Cam Profile: Aufnahme endet", "en": "Cam Profile: recording ends"},
            title={"de": "Aufnahme beendet", "en": "Recording stopped"},
            message={
                "de": "{{ trigger.name }}: Aufnahme beendet.",
                "en": "{{ trigger.name }}: recording stopped.",
            },
        ),
        NoticeTemplate(
            key="cam_profile_recorder",
            kind=KIND_STATE,
            to_state="off",
            entity_domain="binary_sensor",
            integration="cam_profile",
            device_class="connectivity",
            color="#E74C3C",
            cooldown=900,
            label={"de": "Cam Profile: Recorder nicht erreichbar", "en": "Cam Profile: recorder unreachable"},
            title={"de": "Recorder nicht erreichbar", "en": "Recorder unreachable"},
            message={
                "de": "Der Cam Profile Recorder ist nicht erreichbar, Aufnahmen laufen vielleicht nicht.",
                "en": "The Cam Profile Recorder cannot be reached, recordings may not be running.",
            },
        ),
        NoticeTemplate(
            key="ctronics_motion",
            kind=KIND_STATE,
            to_state="on",
            entity_domain="binary_sensor",
            integration="ctronics_cam",
            device_class="motion",
            color="#F1C40F",
            cooldown=300,
            snapshot=True,
            label={"de": "Ctronics: Bewegung", "en": "Ctronics: motion"},
            title={"de": "Bewegung erkannt", "en": "Motion detected"},
            message={
                "de": "{{ trigger.name }} um {{ now().strftime('%H:%M:%S') }}.",
                "en": "{{ trigger.name }} at {{ now().strftime('%H:%M:%S') }}.",
            },
        ),
        NoticeTemplate(
            key="custom_event",
            kind=KIND_EVENT,
            label={"de": "Eigenes Ereignis", "en": "Own event"},
            title={"de": "Ereignis", "en": "Event"},
            message={"de": "{{ trigger.event_type }}", "en": "{{ trigger.event_type }}"},
        ),
        NoticeTemplate(
            key="custom_state",
            kind=KIND_STATE,
            label={"de": "Eigene Entity", "en": "Own entity"},
            title={"de": "Zustand geändert", "en": "State changed"},
            message={
                "de": "{{ trigger.name }}: {{ trigger.to_state.state }}",
                "en": "{{ trigger.name }}: {{ trigger.to_state.state }}",
            },
        ),
    )
}

DEFAULT_THREAD_NAME: Texts = {
    "de": "Meldungen {{ now().strftime('%d.%m.%Y') }}",
    "en": "Notices {{ now().strftime('%Y-%m-%d') }}",
}


def language_of(hass: HomeAssistant) -> str:
    """Die Sprache der Vorlagentexte: Deutsch oder Englisch, nach der Sprache von Home Assistant."""
    return "de" if str(hass.config.language).startswith("de") else "en"


@dataclass(frozen=True)
class NoticeConfig:
    """Eine Meldung, wie sie im Untereintrag steht."""

    subentry_id: str
    template: NoticeTemplate
    target_id: str  # der Untereintrag (Kanal oder Direktnachricht), an den sie geht
    entity_id: str
    event_type: str
    state_to: str
    title: str  # leer: der Text der Vorlage
    message: str  # leer: der Text der Vorlage
    embed: bool
    snapshot: bool
    camera: str
    cooldown: int
    thread_name: str
    tags: tuple[str, ...]
    daily: bool

    @property
    def listens_to(self) -> str:
        """Das Ereignis oder die Entity, auf die sie hört."""
        return self.event_type if self.template.kind == KIND_EVENT else self.entity_id

    @property
    def wanted_state(self) -> str | None:
        """Der Zustand, bei dem sie auslöst (None: bei jeder Änderung)."""
        return self.template.to_state or self.state_to or None

    def text(self, field: str, language: str) -> str:
        """`title` oder `message`: der eigene Text, sonst der der Vorlage."""
        own = getattr(self, field)
        return own or getattr(self.template, field)[language]


def parse_notice(subentry_id: str, data: dict[str, Any]) -> NoticeConfig | None:
    """Eine Meldung aus den Daten eines Untereintrags. Eine unbekannte Vorlage ergibt None."""
    template = TEMPLATES.get(str(data.get(CONF_TEMPLATE)))
    if template is None:
        return None
    return NoticeConfig(
        subentry_id=subentry_id,
        template=template,
        target_id=str(data.get(CONF_TARGET) or ""),
        entity_id=str(data.get(CONF_ENTITY_ID) or ""),
        event_type=str(template.event_type or data.get(CONF_EVENT_TYPE) or ""),
        state_to=str(data.get(CONF_STATE_TO) or "").strip(),
        title=str(data.get(CONF_TITLE) or ""),
        message=str(data.get(CONF_MESSAGE) or ""),
        embed=bool(data.get(CONF_EMBED, True)),
        snapshot=bool(data.get(CONF_SNAPSHOT, template.snapshot)),
        camera=str(data.get(CONF_CAMERA) or ""),
        cooldown=max(int(data.get(CONF_COOLDOWN, template.cooldown) or 0), 0),
        thread_name=str(data.get(CONF_THREAD_NAME) or ""),
        tags=tuple(str(tag) for tag in data.get(CONF_TAGS) or []),
        daily=bool(data.get(CONF_DAILY, True)),
    )


def notices_of(entry: ConfigEntry) -> dict[str, NoticeConfig]:
    """Die Meldungen eines Bots, je Untereintrag."""
    notices = {}
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_NOTICE and (
            notice := parse_notice(subentry.subentry_id, dict(subentry.data))
        ):
            notices[subentry.subentry_id] = notice
    return notices
