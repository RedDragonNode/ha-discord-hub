<p align="center">
  <img src="docs/banner.png" alt="Discord Hub" width="520">
</p>

# Discord Hub for Home Assistant

[![Tests](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/tests.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/tests.yaml)
[![Hassfest](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hassfest.yaml)
[![HACS](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hacs.yaml/badge.svg)](https://github.com/RedDragonNode/ha-discord-hub/actions/workflows/hacs.yaml)

*[Deutsche Version](README.md)*

**Discord from Home Assistant, with everything the built-in Discord integration cannot do:** forum posts (including a daily thread that remembers itself), embeds, images and videos (also a snapshot straight from a camera entity), editing, deleting and pinning messages, archiving threads, plus a bot **and** webhooks. No extra library, no `rest_command`s and no `input_text` helpers.

It can run next to the built-in `discord` integration. Both may use the same bot.

| You want to … | Use |
|---|---|
| send text, embeds, images or videos to a channel | `discord_hub.send_message` |
| create a forum post, optionally **reusing one thread per day** | `discord_hub.forum_post` |
| edit, delete, pin or react to a message | `edit_message`, `delete_message`, `pin_message`, `add_reaction` |
| archive, lock or rename a thread | `update_thread` |
| look up the tags of a forum | `list_forum_tags` |
| just send text like any notification | `notify.send_message` on the channel entity |

## Installation

1. **HACS:** *HACS → ⋮ → Custom repositories*, add `https://github.com/RedDragonNode/ha-discord-hub` as an **Integration**, install **Discord Hub** and restart Home Assistant.
2. **Create a bot** (only if you want a bot, a webhook works without):
   1. In the [Discord Developer Portal](https://discord.com/developers/applications) create an application, reset the **token** on the **Bot** page and copy it. Treat the token like a password.
   2. Under *OAuth2 → URL Generator* choose the scope `bot` and tick the permissions **View Channels, Send Messages, Embed Links, Attach Files, Read Message History**. Forum posts also need **Send Messages in Threads** (the permission “Send Messages” is called “Create Posts” in forums), changing threads needs **Manage Threads**, reactions need **Add Reactions**, pinning and deleting other people's messages need **Manage Messages**.
   3. Invite the bot to your server with the generated link.
3. **Integration:** *Settings → Devices & services → Add integration → Discord Hub*, then choose **Bot (token)** or **Webhook (address)**. You enter the token or address there yourself; they live only in Home Assistant's storage (not in the repository, not in diagnostics, not in the log).

## Setup

| Kind | You enter | You get |
|---|---|---|
| **Bot** | the token | one entry per bot. You add **channels** and **direct messages** to it as sub-entries |
| **Webhook** | a name and the address (*channel settings → Integrations → Webhooks → copy address*) | one entry per webhook with one `notify` entity. It writes only into the channel it belongs to |

**Channels** (*Discord Hub → Add channel*): you pick from the channels of the server (text, announcement, voice, forum, media) without typing IDs. Every channel gets a device with one `notify` entity, which you choose as the target of the actions. **Direct messages** (*Add direct messages*) go to a user ID (developer mode in Discord, right click the user, *Copy user ID*). The bot can only reach users who share a server with it.

After an invalid token Home Assistant itself asks for a new one (*Renew access*). You can also change the token at any time with *Reconfigure*, but it must belong to the same bot.

## Actions

All actions belong to the `notify` entities of Discord Hub. You choose the channel or webhook as the **target**. Actions that return something put it under the name of the entity: `{{ r['notify.fuchs'].thread_id }}`.

> **Always quote IDs** (`"1234567890123456789"`). Discord IDs are so large that the interface corrupts them as numbers.

### `discord_hub.send_message`

| Field | Meaning |
|---|---|
| `message` | text, up to 2000 characters. Mentions like `<@123>`, `<@&456>`, `<#789>` work |
| `embeds` | list of embeds with `title`, `description`, `color`, `url`, `author`, `footer`, `thumbnail`, `image`, `fields`, `timestamp`. Short forms: `color` as `#RRGGBB` (or a decimal number), `author` and `footer` as text, `thumbnail` and `image` as an address, `timestamp: true` for now |
| `files` | files to attach, up to 10 (see below) |
| `reply_to` | ID of a message in the same channel to answer |
| `thread_id` | ID of a thread in the channel, the message then goes there |
| `allow_everyone` | allows `@everyone` and `@here` in the text (off by default, users and roles can always be mentioned) |
| `username`, `avatar_url` | webhooks only: name and picture of the message |

Response: `message_id`, `channel_id`.

```yaml
action: discord_hub.send_message
target:
  entity_id: notify.allgemein
data:
  message: "Motion in the fox den"
  embeds:
    - title: "Fox territory"
      description: "At {{ now().strftime('%H:%M') }}"
      color: "#2ECC71"
      timestamp: true
  files: camera.fuchsrevier
```

### `discord_hub.forum_post`

Creates a new thread in a **forum channel** (for a webhook in the forum it belongs to).

| Field | Meaning |
|---|---|
| `thread_name` | title of the thread, up to 100 characters |
| `message`, `embeds`, `files`, `allow_everyone`, `username`, `avatar_url` | as for `send_message`, they make up the first message |
| `tags` | forum tags **by name** (`["Fuchs"]`) or ID. A bot resolves names itself, a webhook needs IDs (see `list_forum_tags`) |
| `daily` | **one thread per day**: the first call of the day creates the thread, later calls with the same `key` write into it. A deleted thread is replaced by a new one |
| `key` | tells the daily threads of one forum apart, for example per sensor (default `default`) |

Response: `thread_id`, `message_id`, `created` (`true` if the thread is new).

The integration remembers the thread of the day itself (per forum and `key`, it forgets it after 14 days) and runs all calls of one bot one after another. This replaces scripts that need `input_text` helpers and `mode: queued` for it. A script that used to call `rest_command`s becomes one call:

```yaml
sequence:
  - action: discord_hub.forum_post
    target:
      entity_id: notify.fuchs_forum
    data:
      thread_name: "Motion fox - {{ now().strftime('%d.%m.%Y') }}"
      message: "Motion detected"
      embeds:
        - title: "Motion fox"
          description: "At {{ now().strftime('%H:%M:%S') }}"
          color: 3066993
      tags: ["Fuchs"]
      daily: true
      key: fuchs_belegung
```

### Managing

| Action | Fields | Note |
|---|---|---|
| `edit_message` | `message_id`, `message`, `embeds`, `thread_id` | changes a message sent by this bot or webhook. An empty text or list removes it |
| `delete_message` | `message_id`, `thread_id` | deletes a message |
| `add_reaction` | `message_id`, `emoji`, `thread_id` | bots only |
| `pin_message`, `unpin_message` | `message_id`, `thread_id` | bots only |
| `update_thread` | `thread_id`, `archived`, `locked`, `name` | bots only, response: `thread_id`, `name`, `archived`, `locked` |
| `list_forum_tags` | | bots only, response: `tags` with `id`, `name`, `emoji`, `moderated` |

You need `thread_id` only if the message is inside a thread (its ID is in the response of `forum_post`).

### Files

Every entry of `files` is a text or an object:

| Source | Short form | Object |
|---|---|---|
| local file | `/media/Aufnahmen/video.mp4` | `path: …` |
| web address | `https://…/image.jpg` | `url: …` |
| camera snapshot | `camera.fuchsrevier` | `camera: …` |
| media source (local) | `media-source://media_source/local/clip.mp4` | `media: …` |

An object can also take `filename` and `spoiler: true`. Local paths must be in `allowlist_external_dirs` and web addresses in `allowlist_external_urls` (as with the built-in integration). How large a file may be is decided by the server (boost level): if Discord refuses it, the action says so explicitly instead of silently dropping it.

## Limits

- The bot **sends and manages**. Commands, reactions and events from Discord into Home Assistant, status sensors and ready-made notices for Spiel Saison, Cam Profile and Ctronics come in the next versions (see below).
- A webhook cannot read and can only create messages and forum posts. Reactions, pinning, changing threads and tag names need a bot.
- Discord limits requests. When it slows us down the integration waits up to 30 seconds and then retries. A failed attempt to send a **new** message is not retried, so nothing arrives twice.

## Planned

| Version | Content |
|---|---|
| 0.2 | Receiving: slash commands, buttons and reactions as events, allowed users and roles per command |
| 0.3 | Status sensors: members, presence, voice channels |
| 0.4 | Working together: notices with templates for Spiel Saison, Cam Profile and Ctronics |

## Development

```
python -m venv .venv && .venv/Scripts/pip install -r requirements_test.txt
python -m pytest
python tools/make_brand.py      # redraw icon, logo and banner (needs Pillow)
```

The tests run against a simulated Discord, nothing is sent. MIT license.
