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
SUBENTRY_COMMAND = "command"
SUBENTRY_SERVER = "server"
SUBENTRY_MEMBER = "member"
SUBENTRY_NOTICE = "notice"

# Optionen eines Bots (Hören auf Discord)
OPT_LISTEN = "listen"
OPT_RECEIVE_MESSAGES = "receive_messages"
OPT_TRACK_PRESENCE = "track_presence"
OPT_ALLOWED_USERS = "allowed_users"
OPT_ALLOWED_ROLES = "allowed_roles"

# Felder eines Befehls (Untereintrag)
CONF_DESCRIPTION = "description"
CONF_OPTIONS = "options"
CONF_REPLY = "reply"
CONF_EPHEMERAL = "ephemeral"
CONF_EVERYONE = "everyone"
CONF_USERS = "users"
CONF_ROLES = "roles"

# Felder einer Meldung (Untereintrag)
CONF_TEMPLATE = "template"
CONF_TARGET = "target"
CONF_ENTITY_ID = "entity_id"
CONF_EVENT_TYPE = "event_type"
CONF_STATE_TO = "state_to"
CONF_TITLE = "title"
CONF_MESSAGE = "message"
CONF_EMBED = "embed"
CONF_SNAPSHOT = "snapshot"
CONF_CAMERA = "camera"
CONF_COOLDOWN = "cooldown"
CONF_THREAD_NAME = "thread_name"
CONF_TAGS = "tags"
CONF_DAILY = "daily"
MAX_COOLDOWN = 86400

# Ereignisse auf dem Bus von Home Assistant
EVENT_COMMAND = f"{DOMAIN}_command"
EVENT_BUTTON = f"{DOMAIN}_button"
EVENT_REACTION = f"{DOMAIN}_reaction"
EVENT_MESSAGE = f"{DOMAIN}_message"

# Wie oft die Mitgliederzahlen eines Servers bei Discord abgefragt werden
COUNTS_REFRESH_SECONDS = 300
# So lange darf die Verbindung weg sein, bevor die Sensoren aus dem Gateway „nicht verfügbar“ melden
OFFLINE_GRACE_SECONDS = 30

# Wie lange eine Interaktion beantwortet werden kann (Discord erlaubt 15 Minuten)
INTERACTION_SECONDS = 14 * 60
# Wie lange ein Befehl auf `respond` wartet, bevor die Integration ihn mit „Erledigt“ beantwortet
RESPOND_GRACE_SECONDS = 10

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
SERVICE_RESPOND = "respond"

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
ATTR_BUTTONS = "buttons"
ATTR_INTERACTION_ID = "interaction_id"
ATTR_EPHEMERAL = "ephemeral"
ATTR_UPDATE = "update"

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
