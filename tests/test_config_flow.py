"""Config-Flow: Bot, Webhook, Zugang erneuern und die Untereinträge."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.discord_hub.config_flow import DiscordHubConfigFlow
from custom_components.discord_hub.const import (
    CONF_CHANNEL_ID,
    CONF_CHANNEL_TYPE,
    CONF_GUILD_ID,
    CONF_KIND,
    CONF_NAME,
    CONF_TOKEN,
    CONF_USER_ID,
    CONF_WEBHOOK_URL,
    DOMAIN,
    KIND_BOT,
    KIND_WEBHOOK,
)

from .conftest import (
    API,
    BOT_ID,
    ME,
    TEXT_ID,
    TOKEN,
    WEBHOOK_ID,
    WEBHOOK_TOKEN,
    WEBHOOK_URL,
    bot_entry,
    setup_entry,
    webhook_entry,
)


async def _start(hass, choice: str):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["bot", "webhook"]
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": choice})


async def test_add_bot(hass, discord):
    result = await _start(hass, "bot")
    assert result["step_id"] == "bot"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: f"  {TOKEN} "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA Waechter"
    assert result["data"] == {CONF_KIND: KIND_BOT, CONF_TOKEN: TOKEN}
    assert result["result"].unique_id == BOT_ID


async def test_bot_with_a_wrong_token(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", status=401, json={"message": "401: Unauthorized"})
    result = await _start(hass, "bot")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "falsch"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_bot_when_discord_is_down(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", status=400, json={"message": "kaputt"})
    result = await _start(hass, "bot")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_same_bot_twice(hass, discord):
    bot_entry().add_to_hass(hass)
    result = await _start(hass, "bot")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: TOKEN})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_add_webhook(hass, discord):
    result = await _start(hass, "webhook")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: " Hook ", CONF_WEBHOOK_URL: f"{WEBHOOK_URL}?wait=true"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hook"
    assert result["data"] == {CONF_KIND: KIND_WEBHOOK, CONF_WEBHOOK_URL: WEBHOOK_URL}
    assert result["result"].unique_id == WEBHOOK_ID


async def test_webhook_with_a_bad_address(hass, discord):
    result = await _start(hass, "webhook")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Hook", CONF_WEBHOOK_URL: "https://example.com/nope"}
    )
    assert result["errors"] == {"base": "invalid_webhook"}


async def test_webhook_that_does_not_exist(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/webhooks/{WEBHOOK_ID}/{WEBHOOK_TOKEN}", status=404, json={"message": "Unknown Webhook"})
    result = await _start(hass, "webhook")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Hook", CONF_WEBHOOK_URL: WEBHOOK_URL}
    )
    assert result["errors"] == {"base": "invalid_webhook"}


async def test_reauth_with_the_same_bot(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "neuer-token"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "neuer-token"


async def test_reauth_with_another_bot(hass, aioclient_mock):
    aioclient_mock.get(f"{API}/users/@me", json=ME)
    entry = await setup_entry(hass, bot_entry())
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API}/users/@me", json={**ME, "id": "99"})
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_TOKEN: "anderer-bot"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[CONF_TOKEN] == TOKEN


async def test_reconfigure_webhook(hass, discord):
    entry = await setup_entry(hass, webhook_entry())
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    new_url = f"https://discord.com/api/webhooks/{WEBHOOK_ID}/neues-geheimnis"
    discord.get(f"{API}/webhooks/{WEBHOOK_ID}/neues-geheimnis", json={"id": WEBHOOK_ID})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_WEBHOOK_URL: new_url})
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_WEBHOOK_URL] == new_url


# ---------------------------------------------------------------- Untereinträge
def _guilds(*names: str):
    return [{"id": str(i + 1), "name": name} for i, name in enumerate(names)]


CHANNELS = [
    {"id": "10", "type": 4, "name": "Haus", "position": 0},
    {"id": TEXT_ID, "type": 0, "name": "allgemein", "position": 1, "parent_id": "10"},
    {"id": "201", "type": 15, "name": "fuchs", "position": 2, "parent_id": "10"},
    {"id": "202", "type": 2, "name": "Sprache", "position": 3},
    {"id": "203", "type": 13, "name": "Bühne", "position": 4},
    {"id": "204", "type": 5, "name": "news", "position": 5},
]


async def test_add_channel_with_one_server(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.get(f"{API}/users/@me/guilds", json=_guilds("Fuchsbau"))
    discord.get(f"{API}/guilds/1/channels", json=CHANNELS)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "channel"
    schema_options = result["data_schema"].schema[CONF_CHANNEL_ID].config["options"]
    labels = {o["value"]: o["label"] for o in schema_options}
    # der Bühnen-Kanal fehlt, und der schon eingerichtete Kanal ebenfalls
    assert labels == {
        "201": "Haus › fuchs (Forum)",
        "202": "🔊 Sprache",
        "204": "📢 news",
    }
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_CHANNEL_ID: "201"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "fuchs"
    assert result["data"] == {CONF_GUILD_ID: "1", CONF_CHANNEL_ID: "201", CONF_CHANNEL_TYPE: 15, CONF_NAME: "fuchs"}


async def test_add_channel_with_several_servers(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.get(f"{API}/users/@me/guilds", json=_guilds("Fuchsbau", "Hasenbau"))
    discord.get(f"{API}/guilds/2/channels", json=[{"id": "300", "type": 0, "name": "hasen", "position": 0}])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_GUILD_ID: "2"})
    assert result["step_id"] == "channel"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {CONF_CHANNEL_ID: "300"})
    assert result["title"] == "#hasen"


async def test_add_channel_when_the_bot_is_on_no_server(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.get(f"{API}/users/@me/guilds", json=[])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_guilds"


async def test_add_channel_when_all_are_added(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.get(f"{API}/users/@me/guilds", json=_guilds("Fuchsbau"))
    discord.get(f"{API}/guilds/1/channels", json=[CHANNELS[1]])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "channel"), context={"source": SOURCE_USER}
    )
    assert result["reason"] == "no_channels"


async def test_add_direct_messages(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.post(f"{API}/users/@me/channels", json={"id": "900"})
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "user"), context={"source": SOURCE_USER})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Tobieas", CONF_USER_ID: " 555 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_USER_ID: "555", CONF_NAME: "Tobieas"}


async def test_direct_messages_with_a_bad_id(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "user"), context={"source": SOURCE_USER})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Tobieas", CONF_USER_ID: "kein-id"}
    )
    assert result["errors"] == {"base": "invalid_user"}


async def test_direct_messages_to_an_unknown_user(hass, discord):
    entry = await setup_entry(hass, bot_entry())
    discord.post(f"{API}/users/@me/channels", status=404, json={"message": "Unknown User"})
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "user"), context={"source": SOURCE_USER})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Niemand", CONF_USER_ID: "123"}
    )
    assert result["errors"] == {"base": "invalid_user"}


async def test_a_webhook_has_no_subentries(hass, discord):
    entry = await setup_entry(hass, webhook_entry())
    assert DiscordHubConfigFlow.async_get_supported_subentry_types(entry) == {}
    bot = await setup_entry(hass, bot_entry())
    assert set(DiscordHubConfigFlow.async_get_supported_subentry_types(bot)) == {"channel", "user", "command"}
