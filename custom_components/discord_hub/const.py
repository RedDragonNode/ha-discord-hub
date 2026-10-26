"""Konstanten von Discord Hub."""

from __future__ import annotations

DOMAIN = "discord_hub"

# Art des Eintrags: ein Bot (Token) oder ein Webhook (Adresse)
CONF_KIND = "kind"
KIND_BOT = "bot"
KIND_WEBHOOK = "webhook"

CONF_TOKEN = "api_token"
CONF_WEBHOOK_URL = "webhook_url"
CONF_NAME = "name"
CONF_GUILD_ID = "guild_id"
CONF_CHANNEL_ID = "channel_id"
CONF_CHANNEL_TYPE = "channel_type"
CONF_USER_ID = "user_id"

# Untereinträge eines Bots
SUBENTRY_CHANNEL = "channel"
SUBENTRY_USER = "user"

# Kanaltypen von Discord
CHANNEL_TEXT = 0
CHANNEL_VOICE = 2
CHANNEL_CATEGORY = 4
CHANNEL_ANNOUNCEMENT = 5
CHANNEL_FORUM = 15
CHANNEL_MEDIA = 16
SELECTABLE_CHANNELS = (CHANNEL_TEXT, CHANNEL_VOICE, CHANNEL_ANNOUNCEMENT, CHANNEL_FORUM, CHANNEL_MEDIA)
FORUM_CHANNELS = (CHANNEL_FORUM, CHANNEL_MEDIA)

# Dienste
SERVICE_SEND_MESSAGE = "send_message"
SERVICE_FORUM_POST = "forum_post"
SERVICE_EDIT_MESSAGE = "edit_message"
SERVICE_DELETE_MESSAGE = "delete_message"
SERVICE_ADD_REACTION = "add_reaction"
SERVICE_PIN_MESSAGE = "pin_message"
SERVICE_UNPIN_MESSAGE = "unpin_message"
SERVICE_UPDATE_THREAD = "update_thread"
SERVICE_LIST_FORUM_TAGS = "list_forum_tags"

# Felder der Dienste
ATTR_MESSAGE = "message"
ATTR_EMBEDS = "embeds"
ATTR_FILES = "files"
ATTR_REPLY_TO = "reply_to"
ATTR_THREAD_ID = "thread_id"
ATTR_ALLOW_EVERYONE = "allow_everyone"
ATTR_USERNAME = "username"
ATTR_AVATAR_URL = "avatar_url"
ATTR_THREAD_NAME = "thread_name"
ATTR_TAGS = "tags"
ATTR_DAILY = "daily"
ATTR_KEY = "key"
ATTR_MESSAGE_ID = "message_id"
ATTR_EMOJI = "emoji"
ATTR_ARCHIVED = "archived"
ATTR_LOCKED = "locked"
ATTR_NAME = "name"

# Grenzen von Discord
MAX_CONTENT = 2000
MAX_EMBEDS = 10
MAX_FILES = 10
MAX_THREAD_NAME = 100
# Obergrenze, damit nicht versehentlich riesige Dateien in den Speicher geladen werden. Das echte Limit
# hängt vom Server ab (Boost-Stufe) und wird von Discord selbst geprüft.
MAX_FILE_BYTES = 100 * 1024 * 1024

# Gespeicherte Tages-Threads (je Eintrag) werden nach so vielen Tagen vergessen
DAILY_KEEP_DAYS = 14
# Wie lange die Tags eines Forums im Speicher bleiben
TAG_CACHE_SECONDS = 600
