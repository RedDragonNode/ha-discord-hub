"""Was Discord über die beobachteten Server meldet: wer in welchem Sprachkanal ist und welchen Status Mitglieder haben.

Das Gateway schickt beim Anmelden den ganzen Zustand eines Servers (`GUILD_CREATE`) und danach jede Änderung.
Dieser Speicher hält ihn fest, die Sensoren lesen ihn nur.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

STATUS_OFFLINE = "offline"
STATUSES = ["online", "idle", "dnd", STATUS_OFFLINE]

ACTIVITY_CUSTOM = 4
ACTIVITY_TYPES = {
    0: "playing",
    1: "streaming",
    2: "listening",
    3: "watching",
    ACTIVITY_CUSTOM: "custom",
    5: "competing",
}

# Ereignisse, die der Speicher verarbeitet
EVENTS = frozenset(
    {
        "GUILD_CREATE",
        "GUILD_UPDATE",
        "GUILD_DELETE",
        "CHANNEL_CREATE",
        "CHANNEL_UPDATE",
        "CHANNEL_DELETE",
        "VOICE_STATE_UPDATE",
        "PRESENCE_UPDATE",
    }
)


@dataclass(slots=True)
class Voice:
    """Ein Nutzer in einem Sprachkanal."""

    channel_id: str
    name: str | None = None


@dataclass(slots=True)
class Presence:
    """Status und Aktivitäten eines Mitglieds."""

    status: str = STATUS_OFFLINE
    activities: list[dict[str, Any]] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)


@dataclass
class GuildState:
    name: str = ""
    channels: dict[str, str] = field(default_factory=dict)
    voice: dict[str, Voice] = field(default_factory=dict)
    presences: dict[str, Presence] = field(default_factory=dict)


def _display_name(member: Mapping[str, Any] | None) -> str | None:
    member = member or {}
    user = member.get("user") or {}
    return member.get("nick") or user.get("global_name") or user.get("username") or None


def _presence(data: Mapping[str, Any]) -> Presence:
    status = str(data.get("status") or STATUS_OFFLINE)
    return Presence(
        status=status if status in STATUSES else STATUS_OFFLINE,
        activities=[dict(a) for a in data.get("activities") or []],
        platforms=sorted((data.get("client_status") or {}).keys()),
    )


class Monitor:
    """Der Zustand aller Server, die der Bot meldet."""

    def __init__(self) -> None:
        self.guilds: dict[str, GuildState] = {}

    # ------------------------------------------------------------------ Ereignisse
    def handle(self, name: str, data: Mapping[str, Any]) -> bool:
        """Ein Ereignis verarbeiten. True, wenn sich für die Sensoren etwas geändert haben kann."""
        if name == "GUILD_CREATE":
            return self._guild_create(data)
        guild_id = str(data.get("guild_id") or data.get("id") or "")
        if name == "GUILD_DELETE":
            return self.guilds.pop(guild_id, None) is not None
        guild = self.guilds.get(guild_id)
        if guild is None:
            return False  # den Server kennen wir noch nicht, sein GUILD_CREATE bringt den ganzen Zustand mit
        if name == "GUILD_UPDATE":
            guild.name = str(data.get("name") or guild.name)
        elif name in ("CHANNEL_CREATE", "CHANNEL_UPDATE"):
            guild.channels[str(data["id"])] = str(data.get("name") or "")
        elif name == "CHANNEL_DELETE":
            guild.channels.pop(str(data["id"]), None)
        elif name == "VOICE_STATE_UPDATE":
            self._voice_update(guild, data)
        elif name == "PRESENCE_UPDATE":
            guild.presences[str((data.get("user") or {}).get("id") or "")] = _presence(data)
        return True

    def _guild_create(self, data: Mapping[str, Any]) -> bool:
        guild = GuildState(
            name=str(data.get("name") or ""),
            channels={str(c["id"]): str(c.get("name") or "") for c in data.get("channels") or []},
        )
        for state in data.get("voice_states") or []:
            if state.get("channel_id"):
                guild.voice[str(state["user_id"])] = Voice(str(state["channel_id"]), _display_name(state.get("member")))
        for presence in data.get("presences") or []:
            guild.presences[str((presence.get("user") or {}).get("id") or "")] = _presence(presence)
        self.guilds[str(data["id"])] = guild
        return True

    @staticmethod
    def _voice_update(guild: GuildState, data: Mapping[str, Any]) -> None:
        user_id = str(data.get("user_id") or "")
        if data.get("channel_id"):
            known = guild.voice.get(user_id)
            name = _display_name(data.get("member")) or (known.name if known else None)
            guild.voice[user_id] = Voice(str(data["channel_id"]), name)
        else:
            guild.voice.pop(user_id, None)

    # ------------------------------------------------------------------ Abfragen
    def synced(self, guild_id: str) -> bool:
        """Der Server wurde gemeldet, seine Werte stimmen."""
        return guild_id in self.guilds

    def presence_of(self, guild_id: str, user_id: str) -> Presence:
        """Status eines Mitglieds. Wer nicht gemeldet wird, ist offline."""
        guild = self.guilds.get(guild_id)
        return (guild.presences.get(user_id) if guild else None) or Presence()

    def voice_of(self, guild_id: str, user_id: str) -> tuple[Voice, str] | None:
        """(Sprachkanal, Name des Kanals), wenn das Mitglied in einem ist."""
        guild = self.guilds.get(guild_id)
        voice = guild.voice.get(user_id) if guild else None
        if guild is None or voice is None:
            return None
        return voice, guild.channels.get(voice.channel_id, voice.channel_id)

    def voice_count(self, guild_id: str) -> int:
        guild = self.guilds.get(guild_id)
        return len(guild.voice) if guild else 0

    def voice_channels(self, guild_id: str, names: Mapping[str, str]) -> dict[str, list[str]]:
        """Sprachkanal -> Namen der Nutzer darin. Unbekannte Namen ersetzt `names` (Nutzer-ID -> Name), sonst die ID."""
        guild = self.guilds.get(guild_id)
        result: dict[str, list[str]] = {}
        if guild is None:
            return result
        for user_id, voice in guild.voice.items():
            channel = guild.channels.get(voice.channel_id, voice.channel_id)
            result.setdefault(channel, []).append(voice.name or names.get(user_id) or user_id)
        return {channel: sorted(users) for channel, users in sorted(result.items())}


def describe_activity(presence: Presence) -> tuple[str | None, dict[str, Any]]:
    """(Zustand, Attribute) der wichtigsten Aktivität: eine echte (Spiel, Musik), sonst der eigene Status-Text."""
    real = [a for a in presence.activities if a.get("type") != ACTIVITY_CUSTOM]
    custom = next((a for a in presence.activities if a.get("type") == ACTIVITY_CUSTOM), None)
    main = real[0] if real else custom
    if main is None:
        return None, {}
    is_custom = main.get("type") == ACTIVITY_CUSTOM
    text = (main.get("state") or main.get("name")) if is_custom else main.get("name")
    attributes: dict[str, Any] = {
        "type": ACTIVITY_TYPES.get(main.get("type"), "unknown"),
        "details": None if is_custom else main.get("details"),
        "state": None if is_custom else main.get("state"),
        "activities": [a.get("name") for a in presence.activities],
    }
    return (str(text) if text else None), {k: v for k, v in attributes.items() if v not in (None, [])}
