<p align="center">
  <img src="docs/banner.png" alt="Discord Hub" width="520">
</p>

# Discord Hub für Home Assistant

[![Tests](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/tests.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hacs.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hacs.yaml)

*[English version](README.en.md)*

**Discord aus Home Assistant heraus, mit allem, was die eingebaute Discord-Integration nicht kann:** Forum-Posts (auch mit einem Tages-Thread, der sich selbst merkt), Embeds, Bilder und Videos (auch ein Schnappschuss direkt aus einer Kamera-Entity), Nachrichten bearbeiten, löschen, anheften, Threads archivieren, dazu Bot **und** Webhooks. Ohne zusätzliche Bibliothek, ohne `rest_command`s und ohne `input_text`-Helfer.

Die Integration ist parallel zur eingebauten `discord`-Integration nutzbar. Beide können denselben Bot verwenden.

| Du willst … | Dafür |
|---|---|
| Text, Embeds, Bilder oder Videos in einen Kanal schicken | `discord_hub.send_message` |
| einen Forum-Post anlegen, auf Wunsch **einen Thread pro Tag** weiterbenutzen | `discord_hub.forum_post` |
| eine Nachricht ändern, löschen, anheften oder mit einem Emoji versehen | `edit_message`, `delete_message`, `pin_message`, `add_reaction` |
| einen Thread archivieren, sperren oder umbenennen | `update_thread` |
| die Tags eines Forums nachsehen | `list_forum_tags` |
| einfach Text schicken wie bei jeder Benachrichtigung | `notify.send_message` auf der Kanal-Entity |

## Installation

1. **HACS:** *HACS → ⋮ → Benutzerdefinierte Repositories* `https://github.com/RedDragonNode/ha-discord-hub` als **Integration** hinzufügen, **Discord Hub** installieren und Home Assistant neu starten.
2. **Bot anlegen** (nur nötig, wenn du einen Bot nutzen willst, ein Webhook geht auch ohne):
   1. Im [Discord Developer Portal](https://discord.com/developers/applications) eine neue Anwendung anlegen, auf der Seite **Bot** den **Token** zurücksetzen und kopieren. Den Token behandelst du wie ein Passwort.
   2. Unter *OAuth2 → URL Generator* den Bereich `bot` wählen und die Berechtigungen **Kanäle ansehen, Nachrichten senden, Links einbetten, Dateien anhängen, Nachrichtenverlauf anzeigen** ankreuzen. Für Forum-Posts kommt **Nachrichten in Threads senden** dazu (die Berechtigung „Nachrichten senden“ heißt in Foren „Beiträge erstellen“), für Threads ändern **Threads verwalten**, für Reaktionen **Reaktionen hinzufügen**, für Anheften und fremde Nachrichten löschen **Nachrichten verwalten** (neuere Discord-Versionen haben fürs Anheften auch eine eigene Berechtigung).
   3. Mit dem erzeugten Link den Bot auf deinen Server einladen.
3. **Integration:** *Einstellungen → Geräte & Dienste → Integration hinzufügen → Discord Hub*, dann **Bot (Token)** oder **Webhook (Adresse)** wählen. Token und Adressen trägst du dort selbst ein, sie liegen nur im Speicher von Home Assistant (nicht im Repo, nicht in der Diagnose, nicht im Protokoll).

## Einrichten

| Art | Was du eingibst | Was du bekommst |
|---|---|---|
| **Bot** | der Token | ein Eintrag je Bot. Dazu fügst du **Kanäle** und **Direktnachrichten** als Untereinträge hinzu |
| **Webhook** | Name und Adresse (*Kanaleinstellungen → Integrationen → Webhooks → Adresse kopieren*) | ein Eintrag je Webhook mit einer `notify`-Entity. Er schreibt nur in den Kanal, zu dem er gehört |

**Kanäle** (*Discord Hub → Kanal hinzufügen*): Du wählst aus den Kanälen des Servers (Text, Ankündigungen, Sprache, Forum, Media), ohne IDs abzutippen. Jeder Kanal bekommt ein Gerät mit einer `notify`-Entity. Diese Entity wählst du in den Diensten als Ziel. **Direktnachrichten** (*Direktnachrichten hinzufügen*) gehen an eine Nutzer-ID (Entwicklermodus in Discord, Rechtsklick auf den Nutzer, *Nutzer-ID kopieren*). Der Bot erreicht nur Nutzer, die mit ihm einen Server teilen.

Nach einem ungültigen Token fragt Home Assistant selbst nach einem neuen (*Zugang erneuern*). Der Token lässt sich auch jederzeit über *Neu konfigurieren* ändern, er muss aber zum selben Bot gehören.

## Dienste

Alle Dienste gehören den `notify`-Entities von Discord Hub. Du wählst den Kanal oder Webhook als **Ziel**. Dienste, die etwas zurückgeben, liefern es unter dem Namen der Entity: `{{ r['notify.fuchs'].thread_id }}`.

> **IDs immer in Anführungszeichen schreiben** (`"1234567890123456789"`). Discord-IDs sind so groß, dass die Oberfläche sie als Zahl verfälscht.

### `discord_hub.send_message`

| Feld | Bedeutung |
|---|---|
| `message` | Text, bis 2000 Zeichen. Erwähnungen wie `<@123>`, `<@&456>`, `<#789>` funktionieren |
| `embeds` | Liste von Embeds mit `title`, `description`, `color`, `url`, `author`, `footer`, `thumbnail`, `image`, `fields`, `timestamp`. Kurzformen: `color` als `#RRGGBB` (oder als Dezimalzahl), `author` und `footer` als Text, `thumbnail` und `image` als Adresse, `timestamp: true` für jetzt |
| `files` | Dateien zum Anhängen, bis zu 10 (siehe unten) |
| `reply_to` | ID einer Nachricht im selben Kanal, auf die geantwortet wird |
| `thread_id` | ID eines Threads im Kanal, die Nachricht geht dann dorthin |
| `allow_everyone` | erlaubt `@everyone` und `@here` im Text (Standard aus, Nutzer und Rollen lassen sich immer erwähnen) |
| `username`, `avatar_url` | nur Webhooks: Name und Bild der Nachricht |

Antwort: `message_id`, `channel_id`.

```yaml
action: discord_hub.send_message
target:
  entity_id: notify.allgemein
data:
  message: "Bewegung im Fuchsbau"
  embeds:
    - title: "Fuchsrevier"
      description: "Um {{ now().strftime('%H:%M') }}"
      color: "#2ECC71"
      timestamp: true
  files: camera.fuchsrevier
```

### `discord_hub.forum_post`

Legt in einem **Forum-Kanal** einen neuen Thread an (bei einem Webhook im Forum, zu dem er gehört).

| Feld | Bedeutung |
|---|---|
| `thread_name` | Titel des Threads, bis 100 Zeichen |
| `message`, `embeds`, `files`, `allow_everyone`, `username`, `avatar_url` | wie bei `send_message`, sie bilden die erste Nachricht |
| `tags` | Forum-Tags **mit Namen** (`["Fuchs"]`) oder IDs. Namen löst der Bot selbst auf, ein Webhook braucht die IDs (siehe `list_forum_tags`) |
| `daily` | **ein Thread pro Tag**: Der erste Aufruf des Tages legt den Thread an, weitere Aufrufe mit demselben `key` schreiben hinein. Ein gelöschter Thread wird durch einen neuen ersetzt |
| `key` | trennt die Tages-Threads eines Forums, zum Beispiel je Sensor (Standard `default`) |

Antwort: `thread_id`, `message_id`, `created` (`true`, wenn der Thread neu angelegt wurde).

Die Integration merkt sich den Thread des Tages selbst (je Forum und `key`, nach 14 Tagen vergisst sie ihn) und führt alle Aufrufe eines Bots nacheinander aus. Das ersetzt Skripte, die dafür `input_text`-Helfer und `mode: queued` brauchen. Ein Skript, das bisher `rest_command`s aufrief, wird zu einem Aufruf:

```yaml
sequence:
  - action: discord_hub.forum_post
    target:
      entity_id: notify.fuchs_forum
    data:
      thread_name: "Bewegung Fuchs - {{ now().strftime('%d.%m.%Y') }}"
      message: "Bewegung erkannt"
      embeds:
        - title: "Bewegung Fuchs"
          description: "Um {{ now().strftime('%H:%M:%S') }}"
          color: 3066993
      tags: ["Fuchs"]
      daily: true
      key: fuchs_belegung
```

### Verwalten

| Dienst | Felder | Hinweis |
|---|---|---|
| `edit_message` | `message_id`, `message`, `embeds`, `thread_id` | ändert eine Nachricht, die dieser Bot oder Webhook gesendet hat. Ein leerer Text oder eine leere Liste entfernt ihn |
| `delete_message` | `message_id`, `thread_id` | löscht eine Nachricht |
| `add_reaction` | `message_id`, `emoji`, `thread_id` | nur Bots |
| `pin_message`, `unpin_message` | `message_id`, `thread_id` | nur Bots |
| `update_thread` | `thread_id`, `archived`, `locked`, `name` | nur Bots, Antwort: `thread_id`, `name`, `archived`, `locked` |
| `list_forum_tags` | | nur Bots, Antwort: `tags` mit `id`, `name`, `emoji`, `moderated` |

`thread_id` brauchst du nur, wenn die Nachricht in einem Thread liegt (dessen ID steht in der Antwort von `forum_post`).

### Dateien

Jeder Eintrag in `files` ist ein Text oder ein Objekt:

| Quelle | Kurzform | Objekt |
|---|---|---|
| lokale Datei | `/media/Aufnahmen/video.mp4` | `path: …` |
| Web-Adresse | `https://…/bild.jpg` | `url: …` |
| Schnappschuss einer Kamera | `camera.fuchsrevier` | `camera: …` |
| Medienquelle (lokal) | `media-source://media_source/local/clip.mp4` | `media: …` |

Im Objekt gehen außerdem `filename` und `spoiler: true`. Lokale Pfade müssen in `allowlist_external_dirs` stehen und Web-Adressen in `allowlist_external_urls` (wie bei der eingebauten Integration). **Medienquellen brauchen das nicht:** Dateien aus dem Medienordner (zum Beispiel Aufnahmen unter `/media/Aufnahmen`) gehen ohne Konfiguration als `media-source://media_source/local/Aufnahmen/video.mp4`. Wie groß eine Datei sein darf, bestimmt der Server (Boost-Stufe): Lehnt Discord sie ab, meldet die Aktion das ausdrücklich, statt sie still zu verwerfen.

## Grenzen

- Der Bot **sendet und verwaltet**. Befehle, Reaktionen und Ereignisse aus Discord in Home Assistant, Status-Sensoren und fertige Meldungen für Spiel Saison, Cam Profile und Ctronics kommen in den nächsten Versionen (siehe unten).
- Ein Webhook kann nicht lesen und nur Nachrichten sowie Forum-Posts erzeugen. Reaktionen, Anheften, Threads ändern und Tag-Namen brauchen einen Bot.
- Discord begrenzt Anfragen. Die Integration wartet bei einer Bremse bis zu 30 Sekunden und wiederholt dann. Ein Fehler beim Senden einer **neuen** Nachricht wird nicht wiederholt, damit nichts doppelt ankommt.

## Geplant

| Version | Inhalt |
|---|---|
| 0.2 | Empfangen: Slash-Befehle, Buttons und Reaktionen als Ereignisse, erlaubte Nutzer und Rollen je Befehl |
| 0.3 | Status-Sensoren: Mitglieder, Anwesenheit, Sprachkanäle |
| 0.4 | Zusammenspiel: Meldungen mit Vorlagen für Spiel Saison, Cam Profile und Ctronics |

## Entwicklung

```
python -m venv .venv && .venv/Scripts/pip install -r requirements_test.txt
python -m pytest
python tools/make_brand.py      # Icon, Logo und Banner neu zeichnen (braucht Pillow)
```

Die Tests laufen gegen ein nachgestelltes Discord, es wird nichts gesendet. MIT-Lizenz.
