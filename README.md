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
| Nachrichten aus Spiel Saison, Cam Profile oder Ctronics bekommen, ohne eine Automation zu schreiben | *Meldung hinzufügen* |
| Mitglieder, Online-Status und Sprachkanäle eines Servers sehen | Sensoren, mit *Server beobachten* und *Mitglied beobachten* angelegt |
| auf Befehle, Buttons und Reaktionen aus Discord reagieren | Ereignisse `discord_hub_command`, `discord_hub_button`, `discord_hub_reaction`, Antwort mit `respond` |
| einfach Text schicken wie bei jeder Benachrichtigung | `notify.send_message` auf der Kanal-Entity |

## Installation

1. **HACS:** *HACS → ⋮ → Benutzerdefinierte Repositories* `https://github.com/RedDragonNode/ha-discord-hub` als **Integration** hinzufügen, **Discord Hub** installieren und Home Assistant neu starten.
2. **Bot anlegen** (nur nötig, wenn du einen Bot nutzen willst, ein Webhook geht auch ohne):
   1. Im [Discord Developer Portal](https://discord.com/developers/applications) eine neue Anwendung anlegen, auf der Seite **Bot** den **Token** zurücksetzen und kopieren. Den Token behandelst du wie ein Passwort.
   2. Unter *OAuth2 → URL Generator* den Bereich `bot` (für Befehle zusätzlich `applications.commands`) wählen und die Berechtigungen **Kanäle ansehen, Nachrichten senden, Links einbetten, Dateien anhängen, Nachrichtenverlauf anzeigen** ankreuzen. Für Forum-Posts kommt **Nachrichten in Threads senden** dazu (die Berechtigung „Nachrichten senden“ heißt in Foren „Beiträge erstellen“), für Threads ändern **Threads verwalten**, für Reaktionen **Reaktionen hinzufügen**, für Anheften und fremde Nachrichten löschen **Nachrichten verwalten** (neuere Discord-Versionen haben fürs Anheften auch eine eigene Berechtigung).
   3. Mit dem erzeugten Link den Bot auf deinen Server einladen.
3. **Integration:** *Einstellungen → Geräte & Dienste → Integration hinzufügen → Discord Hub*, dann **Bot (Token)** oder **Webhook (Adresse)** wählen. Token und Adressen trägst du dort selbst ein, sie liegen nur im Speicher von Home Assistant (nicht im Repo, nicht in der Diagnose, nicht im Protokoll).

## Einrichten

| Art | Was du eingibst | Was du bekommst |
|---|---|---|
| **Bot** | der Token | ein Eintrag je Bot. Dazu fügst du **Kanäle**, **Direktnachrichten**, **Befehle**, **Server**, **Mitglieder** und **Meldungen** als Untereinträge hinzu |
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

## Empfangen

Befehle, Button-Klicks und Reaktionen aus Discord kommen als **Ereignisse** in Home Assistant an. Dafür muss der Bot auf Discord hören. Das tut er, sobald du einen Befehl anlegst oder unter *Konfigurieren* des Bots **Auf Discord hören** einschaltest. Der Bot steht dann in Discord auf online, und der Sensor **Verbunden** am Gerät des Bots (unter *Diagnose*) zeigt die Verbindung. Es ist eine ausgehende Verbindung zu Discord, du brauchst weder eine öffentliche Adresse noch einen offenen Port.

| Option unter *Konfigurieren* | Bedeutung |
|---|---|
| **Auf Discord hören** | der Bot baut die Verbindung auf, auch wenn er keinen Befehl hat (für Buttons und Reaktionen) |
| **Nachrichten empfangen** | zusätzlich das Ereignis `discord_hub_message` für Nachrichten. Braucht den **Message Content Intent** (*Developer Portal → Bot → Privileged Gateway Intents*). Fehlt er, beendet Discord die Verbindung, und unter *Reparaturen* steht ein Hinweis |
| **Status der Mitglieder verfolgen** | Status und Aktivität der beobachteten Mitglieder (siehe *Beobachten*). Braucht den **Presence Intent** |
| **Erlaubte Nutzer** und **Erlaubte Rollen** (IDs) | begrenzen, wer Buttons drücken und reagieren darf (leer: jeder). Befehle ohne eigene Liste benutzen sie |

### Slash-Befehle

*Discord Hub → Befehl hinzufügen* legt einen Befehl auf einem Server an, er gilt sofort und verschwindet wieder, wenn du ihn löschst. Die Integration fasst nur Befehle an, die sie selbst angelegt hat. Der Bot muss mit dem Bereich `applications.commands` eingeladen sein (*OAuth2 → URL Generator*), sonst meldet ein Hinweis unter *Reparaturen*, dass Discord die Befehle ablehnt.

| Feld | Bedeutung |
|---|---|
| **Name**, **Beschreibung** | `/name` und der Text, den Discord dazu zeigt. Name: kleine Buchstaben, Ziffern, `-` und `_` |
| **Optionen** | eine je Zeile als `name:typ:Beschreibung`. Ein `?` hinter dem Namen macht sie freiwillig, eine Auswahl steht in eckigen Klammern. Typen: `text`, `ganzzahl`, `zahl`, `schalter`, `nutzer`, `kanal`. Beispiel: `modus:text:Betriebsart [auto\|an\|aus]` und `grad?:zahl:Zieltemperatur` (erforderliche Optionen vor den freiwilligen, höchstens fünf) |
| **Sofortige Antwort** | Text, den der Bot sofort schickt. Leer: Discord zeigt „denkt nach“, bis deine Automation mit `respond` antwortet. Kommt nach 10 Sekunden keine Antwort, steht dort „Erledigt“ |
| **Antwort nur für den Nutzer sichtbar** | die Antwort sehen nur der, der den Befehl benutzt hat |
| **Erlaubte Nutzer**, **Erlaubte Rollen**, **Jeder darf** | wer ihn benutzen darf |

**Wer darf, steht fest, bevor etwas passiert:** Ein Befehl ohne Eintrag ist für alle gesperrt (er braucht Nutzer, Rollen, **Jeder darf** oder erlaubte Nutzer in den Optionen des Bots). Wer nicht darf, bekommt eine Antwort nur für sich, und in Home Assistant passiert nichts. Slash-Befehle kann auf einem Server sonst jeder auslösen.

Jeder Befehl löst das Ereignis `discord_hub_command` aus, und seine `event`-Entity am Gerät `/name` meldet „used“ mit denselben Daten als Attributen:

| Feld | Inhalt |
|---|---|
| `command` | Name des Befehls |
| `options` | die Werte der Optionen als `name: wert` (bei `nutzer` und `kanal` die ID) |
| `interaction_id` | die Interaktion, auf die `respond` antwortet |
| `user_id`, `user_name`, `roles` | wer es war |
| `guild_id`, `channel_id`, `entry_id`, `bot_id` | wo, und welcher Bot |

```yaml
triggers:
  - trigger: event
    event_type: discord_hub_command
    event_data:
      command: licht
actions:
  - action: light.turn_on
    target:
      entity_id: light.spielzimmer
    data:
      brightness_pct: "{{ trigger.event.data.options.helligkeit | default(50) }}"
  - action: discord_hub.respond
    data:
      interaction_id: "{{ trigger.event.data.interaction_id }}"
      message: "Das Licht ist an."
```

Mit der Entity geht es auch ohne Ereignis-Daten im Trigger: `trigger: event.received`, `target: {entity_id: event.licht}`, `options: {event_type: [used]}`, die Werte stehen dann in `trigger.to_state.attributes`.

### Buttons

`send_message` und `edit_message` nehmen `buttons` an: eine Liste mit `label`, `custom_id` (bis 100 Zeichen), `style` (`primary`, `secondary`, `success`, `danger`, `link`), bei `link` eine `url` statt der `custom_id`, dazu `emoji` und `disabled`. Bis zu fünf je Zeile, höchstens 25. Ein Klick löst `discord_hub_button` aus (mit `custom_id`, `message_id`, `interaction_id` und dem Nutzer) und wird sofort bestätigt. Buttons gehen nur mit einem Bot, der auf Discord hört. Mit `buttons: []` bei `edit_message` verschwinden sie wieder.

```yaml
actions:
  - action: discord_hub.send_message
    target:
      entity_id: notify.allgemein
    data:
      message: "Bewegung im Fuchsbau. Alarm quittieren?"
      buttons:
        - {label: "Quittieren", custom_id: "alarm_quittiert", style: "success"}
```

### `discord_hub.respond`

Antwortet auf einen Befehl oder Button-Klick, bis zu 14 Minuten danach.

| Feld | Bedeutung |
|---|---|
| `interaction_id` | aus dem Ereignis |
| `message`, `embeds`, `buttons` | die Antwort. Die erste Antwort auf einen Befehl füllt die „denkt nach“-Nachricht, weitere sind neue Nachrichten |
| `ephemeral` | nur für den Nutzer sichtbar (für weitere Antworten, die erste folgt dem Befehl) |
| `update` | bei einem Button: ändert die Nachricht mit dem Button (zum Beispiel Text ersetzen und `buttons: []`), statt eine neue zu schicken |

### Reaktionen und Nachrichten

`discord_hub_reaction` kommt, wenn jemand eine Reaktion setzt oder entfernt (`action: add` oder `remove`, dazu `emoji`, `emoji_id`, `message_id` und der Nutzer). Reaktionen des Bots selbst werden übergangen. `discord_hub_message` (nur mit **Nachrichten empfangen**) kommt für jede Nachricht eines Menschen mit `content`, `message_id`, `reply_to` und dem Nutzer. Beide folgen den erlaubten Nutzern und Rollen der Optionen.

## Beobachten

Der Bot kann melden, was auf deinem Server los ist: wie viele Mitglieder da sind, wer in einem Sprachkanal sitzt und welchen Status ein Mitglied hat. Dafür baut er dieselbe Verbindung zu Discord auf wie beim Empfangen (siehe oben). Du legst unter *Discord Hub* einen **Server** oder ein **Mitglied** als Untereintrag an.

### Server

*Discord Hub → Server beobachten* legt ein Gerät mit drei Sensoren an:

| Sensor | Inhalt |
|---|---|
| **Mitglieder** | die Zahl der Mitglieder |
| **Online** | die Zahl der Mitglieder, die gerade online sind |
| **In Sprachkanälen** | wie viele Nutzer in Sprachkanälen sind. Das Attribut `channels` zeigt, wer in welchem Kanal sitzt |

**Mitglieder** und **Online** fragt die Integration alle fünf Minuten bei Discord ab. Discord liefert **ungefähre** Zahlen und verlangt dafür keinen besonderen Intent. **In Sprachkanälen** kommt sofort aus der Verbindung und braucht ebenfalls keinen privilegierten Intent. Als Name eines Nutzers steht der, den Discord beim Beitritt mitschickt, sonst der eines beobachteten Mitglieds, sonst seine ID.

### Mitglieder

*Discord Hub → Mitglied beobachten* legt ein Gerät für ein Mitglied an. Die Nutzer-ID kopierst du in Discord (Entwicklermodus, Rechtsklick auf den Nutzer, *Nutzer-ID kopieren*).

| Entity | Inhalt |
|---|---|
| **Im Sprachkanal** (`binary_sensor`) | an, wenn das Mitglied in einem Sprachkanal sitzt. Attribute: `channel` und `channel_id` |
| **Status** (`sensor`) | `online`, `idle`, `dnd` oder `offline`. Attribut `platforms`: `desktop`, `mobile`, `web` |
| **Aktivität** (`sensor`) | das Spiel oder die Musik, sonst der eigene Status-Text des Mitglieds. Attribute: `type`, `details`, `state`, `activities`. Ohne Aktivität steht dort `unknown` |

**Status** und **Aktivität** gibt es nur, wenn unter *Konfigurieren* des Bots **Status der Mitglieder verfolgen** an ist. Das braucht den **Presence Intent** (*Developer Portal → Bot → Privileged Gateway Intents*). Fehlt er, beendet Discord die Verbindung, und unter *Reparaturen* steht ein Hinweis. Ohne die Option gibt es nur **Im Sprachkanal**. Wer Discord nicht freigibt (zum Beispiel unsichtbar), steht auf `offline`.

Die Sensoren, deren Werte aus der Verbindung kommen, zeigen „nicht verfügbar“, wenn die Verbindung länger als 30 Sekunden weg ist. Kurze Neuverbindungen, die Discord regelmäßig verlangt, sieht man ihnen nicht an.

### Die Verbindung

Der Sensor **Verbunden** am Gerät des Bots zeigt in seinen Attributen, wie oft und warum die Verbindung neu aufgebaut wurde: `sessions` (neue Anmeldungen), `resumes` (fortgesetzte Sitzungen), `reconnects`, `last_reason` (zum Beispiel `reconnect_requested`, wenn Discord es verlangt hat) sowie `last_connected` und `last_disconnected`. Jede Neuverbindung steht außerdem im Protokoll auf der Stufe INFO (`logger:` mit `custom_components.discord_hub: info`).

## Meldungen

Eine **Meldung** schickt eine Nachricht an Discord, wenn in Home Assistant etwas passiert, ohne dass du eine Automation schreibst. Du legst sie unter *Discord Hub → Meldung hinzufügen* als Untereintrag eines Bots an: Vorlage wählen, Ziel wählen, den Text bei Bedarf anpassen. Dafür muss der Bot nicht auf Discord hören, er sendet nur.

### Vorlagen

| Vorlage | Löst aus bei | Daten |
|---|---|---|
| **Spiel Saison: Aufnahme gestartet** | Ereignis `spiel_saison_recording_started` | `partner`, `nickname`, `season`, `recording`, `place`, `folder`, `cams`, `session` und `files` (die zwei letzten ab Spiel Saison 0.14.0, `files` nennt die Videos als Liste mit `cam` und `name`, ohne Endung), auf Wunsch mit einem **Schnappschuss von jeder Kamera** der Aufnahme (bis zu zehn) |
| **Spiel Saison: Aufnahme gestoppt** | Ereignis `spiel_saison_recording_stopped` | `partner`, `nickname`, `season`, `recording`, `place`, `reason`, `duration_s` |
| **Spiel Saison: Saison gestartet** | Ereignis `spiel_saison_season_started` | `partner`, `season`, `start` |
| **Spiel Saison: Saison beendet** | Ereignis `spiel_saison_season_ended` | `partner`, `nickname`, `season`, `recordings`, `seconds`, `start` |
| **Cam Profile: Aufnahme beginnt** und **endet** | der Sensor **Aufnahme** eines Profils (oder einer Kamera) wird `on` beziehungsweise `off` | Name der Entity, Attribute wie `folder` |
| **Cam Profile: Recorder nicht erreichbar** | der Sensor **Recorder erreichbar** wird `off` | Name der Entity |
| **Ctronics: Bewegung** | der Sensor **Bewegung** einer Kamera wird `on` | Name der Entity, auf Wunsch mit **Schnappschuss** |
| **Eigenes Ereignis** | ein beliebiges Ereignis auf dem Bus von Home Assistant | alle Daten des Ereignisses |
| **Eigene Entity** | eine beliebige Entity, bei jeder Zustandsänderung oder bei einem Zustand | Name, alter und neuer Zustand |

Bei Entities zählt nur ein echter Wechsel: Ein Sensor, der gerade erst entsteht, ausfällt oder aus „nicht verfügbar“ zurückkommt, löst nichts aus.

### Einrichten

| Feld | Bedeutung |
|---|---|
| **Ziel** | ein Kanal, ein Forum oder eine Direktnachricht, die du dem Bot schon hinzugefügt hast |
| **Entity** oder **Ereignis** | die Quelle (bei den Vorlagen für Entities die Entity, bei **Eigenes Ereignis** der Name des Ereignisses) |
| **Titel** und **Text** | Vorlagen von Home Assistant. Ein leerer Text benutzt den der Vorlage (auf Deutsch oder Englisch, je nach Sprache von Home Assistant) |
| **Als Embed senden** | an: Titel und Text als Embed mit Farbe der Vorlage und Uhrzeit. Aus: ein Text mit fettem Titel |
| **Schnappschuss der Kamera anhängen** und **Kamera** | hängt ein Bild an. Bei **Ctronics: Bewegung** vorbelegt: Ohne eigene Wahl kommt es von der Kamera auf demselben Gerät wie der Bewegungs-Sensor. Bei **Spiel Saison: Aufnahme gestartet** vorbelegt: Ohne eigene Wahl kommt von jeder Kamera der Aufnahme (`trigger.cams`) ein Bild. Wählst du eine **Kamera**, kommt nur deren Bild. Lässt sich ein Bild nicht holen, fällt nur dieses weg, die Meldung geht trotzdem raus |
| **Mindestabstand in Sekunden** | so lange wartet dieselbe Meldung nach dem Senden, bevor sie noch einmal sendet (bei Bewegung 300, bei Ereignissen von Spiel Saison 0, 0 sendet jede). Bei Entities zählt er je Meldung |
| **Name des Threads**, **Tags**, **Ein Thread pro Tag** | nur bei einem Forum als Ziel. Der Name ist ebenfalls eine Vorlage. Mit einem Thread pro Tag schreiben alle Meldungen eines Forums mit demselben Namen in denselben Thread des Tages, ein anderer Name ergibt einen eigenen Thread |

In Titel und Text steht die Variable `trigger`: Bei einem Ereignis hat sie dessen Daten (`trigger.season`, `trigger.partner`) und `trigger.event_type` (die Schreibweise einer Automation, `trigger.event.data.season`, geht ebenso), bei einer Entity `trigger.name`, `trigger.entity_id`, `trigger.from_state` und `trigger.to_state` (mit `trigger.to_state.state` und `trigger.to_state.attributes.folder`). Alle Funktionen der Vorlagen von Home Assistant gehen (`now()`, `states()` und so weiter). Das Bearbeiten ändert eine Meldung, ohne dass du sie neu anlegen musst.

**Eine Meldung stört Home Assistant nie.** Ist ein Text kaputt, das Ziel gelöscht oder Discord nicht erreichbar, steht eine Zeile im Protokoll, mehr passiert nicht.

### Als Automation

Willst du mehr Kontrolle, geht dasselbe mit einer Automation. Hier die Beispiele zu den Vorlagen:

```yaml
# Spiel Saison: Aufnahme gestartet
triggers:
  - trigger: event
    event_type: spiel_saison_recording_started
actions:
  - action: discord_hub.send_message
    target:
      entity_id: notify.allgemein
    data:
      embeds:
        - title: "Aufnahme gestartet"
          description: >-
            {{ trigger.event.data.nickname }}: Saison {{ trigger.event.data.season }},
            Aufnahme {{ trigger.event.data.recording }}
          color: "#2ECC71"
          timestamp: true
```

```yaml
# Cam Profile: ein Profil beginnt die Aufnahme
triggers:
  - trigger: state
    entity_id: binary_sensor.profil_treppe_aufnahme
    from: "off"
    to: "on"
actions:
  - action: discord_hub.send_message
    target:
      entity_id: notify.allgemein
    data:
      message: "{{ trigger.to_state.name }}: Aufnahme gestartet"
```

```yaml
# Ctronics: Bewegung mit Schnappschuss, höchstens alle fünf Minuten
mode: single
triggers:
  - trigger: motion.detected
    target:
      entity_id: binary_sensor.fuchsauge_bewegung
actions:
  - action: discord_hub.send_message
    target:
      entity_id: notify.allgemein
    data:
      message: "Bewegung am Fuchsauge"
      files: camera.fuchsauge
  - delay: "00:05:00"
```

## Grenzen

- Der Bot **sendet, verwaltet, empfängt, beobachtet und meldet**. Videos der Aufnahmen schickt Discord Hub nicht mit (sie sind meist größer, als Discord erlaubt), Schnappschüsse von Kameras gehen.
- Ein Webhook kann nicht lesen und nur Nachrichten sowie Forum-Posts erzeugen. Reaktionen, Anheften, Threads ändern und Tag-Namen brauchen einen Bot.
- Discord begrenzt Anfragen. Die Integration wartet bei einer Bremse bis zu 30 Sekunden und wiederholt dann. Ein Fehler beim Senden einer **neuen** Nachricht wird nicht wiederholt, damit nichts doppelt ankommt.

## Entwicklung

```
python -m venv .venv && .venv/Scripts/pip install -r requirements_test.txt
python -m pytest
python tools/make_brand.py      # Icon, Logo und Banner neu zeichnen (braucht Pillow)
```

Die Tests laufen gegen ein nachgestelltes Discord, es wird nichts gesendet. MIT-Lizenz.
