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
| see members, online status and voice channels of a server | sensors, created with *Watch a server* and *Watch a member* |
| react to commands, buttons and reactions from Discord | events `discord_hub_command`, `discord_hub_button`, `discord_hub_reaction`, answer with `respond` |
| just send text like any notification | `notify.send_message` on the channel entity |

## Installation

1. **HACS:** *HACS → ⋮ → Custom repositories*, add `https://github.com/RedDragonNode/ha-discord-hub` as an **Integration**, install **Discord Hub** and restart Home Assistant.
2. **Create a bot** (only if you want a bot, a webhook works without):
   1. In the [Discord Developer Portal](https://discord.com/developers/applications) create an application, reset the **token** on the **Bot** page and copy it. Treat the token like a password.
   2. Under *OAuth2 → URL Generator* choose the scope `bot` (for commands also `applications.commands`) and tick the permissions **View Channels, Send Messages, Embed Links, Attach Files, Read Message History**. Forum posts also need **Send Messages in Threads** (the permission “Send Messages” is called “Create Posts” in forums), changing threads needs **Manage Threads**, reactions need **Add Reactions**, pinning and deleting other people's messages need **Manage Messages** (newer Discord versions also have a separate permission for pinning).
   3. Invite the bot to your server with the generated link.
3. **Integration:** *Settings → Devices & services → Add integration → Discord Hub*, then choose **Bot (token)** or **Webhook (address)**. You enter the token or address there yourself; they live only in Home Assistant's storage (not in the repository, not in diagnostics, not in the log).

## Setup

| Kind | You enter | You get |
|---|---|---|
| **Bot** | the token | one entry per bot. You add **channels**, **direct messages**, **commands**, **servers** and **members** to it as sub-entries |
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

An object can also take `filename` and `spoiler: true`. Local paths must be in `allowlist_external_dirs` and web addresses in `allowlist_external_urls` (as with the built-in integration). **Media sources need neither:** files from the media folder (for example recordings under `/media/Aufnahmen`) work without any configuration as `media-source://media_source/local/Aufnahmen/video.mp4`. How large a file may be is decided by the server (boost level): if Discord refuses it, the action says so explicitly instead of silently dropping it.

## Receiving

Commands, button clicks and reactions from Discord arrive in Home Assistant as **events**. For that the bot has to listen to Discord. It does as soon as you add a command or turn on **Listen to Discord** under *Configure* of the bot. The bot then shows as online in Discord, and the **Connected** sensor on the bot's device (under *Diagnostic*) shows the connection. It is an outgoing connection to Discord, you need neither a public address nor an open port.

| Option under *Configure* | Meaning |
|---|---|
| **Listen to Discord** | the bot opens the connection even if it has no command (for buttons and reactions) |
| **Receive messages** | additionally the event `discord_hub_message` for messages. Needs the **Message Content Intent** (*Developer Portal → Bot → Privileged Gateway Intents*). If it is missing Discord closes the connection and a notice appears under *Repairs* |
| **Track member status** | status and activity of the watched members (see *Watching*). Needs the **Presence Intent** |
| **Allowed users** and **Allowed roles** (IDs) | limit who can press buttons and react (empty: everyone). Commands without a list of their own use them |

### Slash commands

*Discord Hub → Add command* creates a command on a server. It works at once and disappears when you delete it. The integration only touches commands it created itself. The bot has to be invited with the scope `applications.commands` (*OAuth2 → URL Generator*), otherwise a notice under *Repairs* says that Discord refuses the commands.

| Field | Meaning |
|---|---|
| **Name**, **Description** | `/name` and the text Discord shows for it. Name: lowercase letters, digits, `-` and `_` |
| **Options** | one per line as `name:type:description`. A `?` after the name makes it optional, a choice goes in square brackets. Types: `text`, `integer`, `number`, `switch`, `user`, `channel` (the German words `ganzzahl`, `zahl`, `schalter`, `nutzer`, `kanal` work too). Example: `mode:text:Operating mode [auto\|on\|off]` and `degrees?:number:Target temperature` (required options before optional ones, at most five) |
| **Immediate reply** | text the bot sends at once. Empty: Discord shows “thinking” until your automation answers with `respond`. If no answer comes after 10 seconds it says “Done” |
| **Reply visible only to the user** | only the person who used the command sees the answer |
| **Allowed users**, **Allowed roles**, **Everyone may use it** | who may use it |

**Who may is settled before anything happens:** a command without an entry is closed to everyone (it needs users, roles, **Everyone may use it** or allowed users in the bot's options). Anyone else gets an answer only they can see, and nothing happens in Home Assistant. Otherwise anyone on a server can trigger a slash command.

Every command fires the event `discord_hub_command`, and its `event` entity on the device `/name` reports “used” with the same data as attributes:

| Field | Content |
|---|---|
| `command` | name of the command |
| `options` | the values of the options as `name: value` (the ID for `user` and `channel`) |
| `interaction_id` | the interaction `respond` answers |
| `user_id`, `user_name`, `roles` | who it was |
| `guild_id`, `channel_id`, `entry_id`, `bot_id` | where, and which bot |

```yaml
triggers:
  - trigger: event
    event_type: discord_hub_command
    event_data:
      command: light
actions:
  - action: light.turn_on
    target:
      entity_id: light.playroom
    data:
      brightness_pct: "{{ trigger.event.data.options.brightness | default(50) }}"
  - action: discord_hub.respond
    data:
      interaction_id: "{{ trigger.event.data.interaction_id }}"
      message: "The light is on."
```

With the entity it also works without event data in the trigger: `trigger: event.received`, `target: {entity_id: event.light}`, `options: {event_type: [used]}`, the values are then in `trigger.to_state.attributes`.

### Buttons

`send_message` and `edit_message` take `buttons`: a list with `label`, `custom_id` (up to 100 characters), `style` (`primary`, `secondary`, `success`, `danger`, `link`), for `link` a `url` instead of the `custom_id`, plus `emoji` and `disabled`. Up to five per row, at most 25. A click fires `discord_hub_button` (with `custom_id`, `message_id`, `interaction_id` and the user) and is confirmed at once. Buttons only work with a bot that listens to Discord. `buttons: []` on `edit_message` removes them again.

```yaml
actions:
  - action: discord_hub.send_message
    target:
      entity_id: notify.allgemein
    data:
      message: "Motion in the fox den. Acknowledge the alarm?"
      buttons:
        - {label: "Acknowledge", custom_id: "alarm_acknowledged", style: "success"}
```

### `discord_hub.respond`

Answers a command or a button click, up to 14 minutes later.

| Field | Meaning |
|---|---|
| `interaction_id` | from the event |
| `message`, `embeds`, `buttons` | the answer. The first answer to a command fills the “thinking” message, further answers are new messages |
| `ephemeral` | visible only to the user (for further answers, the first one follows the command) |
| `update` | for a button: changes the message with the button (for example replace the text and `buttons: []`) instead of sending a new one |

### Reactions and messages

`discord_hub_reaction` arrives when someone adds or removes a reaction (`action: add` or `remove`, plus `emoji`, `emoji_id`, `message_id` and the user). Reactions of the bot itself are skipped. `discord_hub_message` (only with **Receive messages**) arrives for every message by a human with `content`, `message_id`, `reply_to` and the user. Both follow the allowed users and roles of the options.

## Watching

The bot can report what is going on on your server: how many members there are, who sits in a voice channel and which status a member has. For that it opens the same connection to Discord as for receiving (see above). Under *Discord Hub* you add a **server** or a **member** as a sub-entry.

### Servers

*Discord Hub → Watch a server* creates a device with three sensors:

| Sensor | Content |
|---|---|
| **Members** | the number of members |
| **Online** | the number of members that are online right now |
| **In voice channels** | how many users are in voice channels. The attribute `channels` shows who sits in which channel |

The integration asks Discord for **Members** and **Online** every five minutes. Discord returns **approximate** numbers and needs no special intent for them. **In voice channels** comes straight from the connection and needs no privileged intent either. The name of a user is the one Discord sends when they join, otherwise that of a watched member, otherwise the ID.

### Members

*Discord Hub → Watch a member* creates a device for one member. Copy the user ID in Discord (developer mode, right-click the user, *Copy User ID*).

| Entity | Content |
|---|---|
| **In voice channel** (`binary_sensor`) | on while the member sits in a voice channel. Attributes: `channel` and `channel_id` |
| **Status** (`sensor`) | `online`, `idle`, `dnd` or `offline`. Attribute `platforms`: `desktop`, `mobile`, `web` |
| **Activity** (`sensor`) | the game or the music, otherwise the member's own status text. Attributes: `type`, `details`, `state`, `activities`. Without an activity it reads `unknown` |

**Status** and **Activity** exist only if **Track member status** is on under *Configure* of the bot. That needs the **Presence Intent** (*Developer Portal → Bot → Privileged Gateway Intents*). If it is missing Discord closes the connection and a notice appears under *Repairs*. Without the option there is only **In voice channel**. Whoever does not show up for Discord (for example invisible) reads `offline`.

The sensors whose values come from the connection show "unavailable" when the connection has been gone for more than 30 seconds. Short reconnects that Discord asks for regularly are not visible in them.

### The connection

The **Connected** sensor on the bot's device shows in its attributes how often and why the connection was rebuilt: `sessions` (new logins), `resumes` (resumed sessions), `reconnects`, `last_reason` (for example `reconnect_requested` when Discord asked for it) as well as `last_connected` and `last_disconnected`. Every reconnect is also written to the log at INFO level (`logger:` with `custom_components.discord_hub: info`).

## Limits

- The bot **sends, manages, receives and watches**. Ready-made notices for Spiel Saison, Cam Profile and Ctronics come in the next version (see below).
- A webhook cannot read and can only create messages and forum posts. Reactions, pinning, changing threads and tag names need a bot.
- Discord limits requests. When it slows us down the integration waits up to 30 seconds and then retries. A failed attempt to send a **new** message is not retried, so nothing arrives twice.

## Planned

| Version | Content |
|---|---|
| 0.4 | Working together: notices with templates for Spiel Saison, Cam Profile and Ctronics |

## Development

```
python -m venv .venv && .venv/Scripts/pip install -r requirements_test.txt
python -m pytest
python tools/make_brand.py      # redraw icon, logo and banner (needs Pillow)
```

The tests run against a simulated Discord, nothing is sent. MIT license.
