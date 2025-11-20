import asyncio
import datetime
import hikari
import lightbulb
import random
import re

from lightbulb import commands
from typing import Any, Optional, Union

from utils.atlas import Atlas, Map
from utils.settings_manager import ServerSettings, SettingsManager
from utils.consts import ADMIN_DENIES, ADMIN_PERMISSIONS, READ_DENIES, READ_PERMISSIONS, WRITE_DENIES, WRITE_PERMISSIONS
from utils.type_enforcer import TypeEnforcer

WEBHOOK_NAME = "Expedition"

plugin = lightbulb.Plugin("MapPlugin")

atlas = Atlas()
settings_manager = SettingsManager()

guildEnforcer = TypeEnforcer[hikari.Guild]()
guildChannelEnforcer = TypeEnforcer[hikari.GuildChannel]()
textableGuildChannelEnforcer = TypeEnforcer[hikari.TextableGuildChannel]()
mapEnforcer = TypeEnforcer[Map]()
memberEnforcer = TypeEnforcer[hikari.Member]()
interactionMemberEnforcer = TypeEnforcer[hikari.InteractionMember]()
stringEnforcer = TypeEnforcer[str]()

emote_pattern = r'^<(a?):.*:(\d+)>$'
link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'

MAX_DISPLAY_NAME_LENGTH = 80

def flatten_list_of_lists(lists):
    return [item for sublist in lists for item in sublist]

async def get_role_with_name(guild:hikari.Guild, role_name: str, should_fetch: bool = True) -> Optional[hikari.Role]:
    if should_fetch:
        await guild.fetch_roles()
    roles = guild.get_roles()
    for role_id, role in roles.items():
        if role.name == role_name:
            return role
    return None

async def get_everyone_role(guild: hikari.Guild) -> hikari.Role:
    optional_role = await get_role_with_name(guild, "@everyone")
    if optional_role is None:
        raise ValueError("Guild somehow doesn't have an @everyone role")
    role: hikari.Role = optional_role
    return role

async def get_private_perms(guild: hikari.Guild) -> hikari.PermissionOverwrite:
    everyone_role = await get_everyone_role(guild)
    return hikari.PermissionOverwrite(
        id=everyone_role.id,
        type=hikari.channels.PermissionOverwriteType.ROLE, # pyright: ignore[reportAttributeAccessIssue]
        deny=(hikari.Permissions.VIEW_CHANNEL)
    )

async def ensure_category_exists(guild: hikari.Guild, channel_name: str) -> hikari.GuildChannel:
    for channel_id, channel in guild.get_channels().items():
        if channel.name == channel_name and (channel.type == hikari.channels.ChannelType.GUILD_CATEGORY): # pyright: ignore[reportAttributeAccessIssue]
            return channel
    private_perms = await get_private_perms(guild)
    return await guild.create_category(channel_name, permission_overwrites = [private_perms])

async def get_guild(ctx: lightbulb.SlashContext) -> hikari.Guild:
    return await guildEnforcer.ensure_type(ctx.get_guild(), ctx, "For some reason the bot could not tell which server the command came from")

async def get_map(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_name: str) -> Map:
    return await mapEnforcer.ensure_type(atlas.get_map(guild.id, map_name), ctx, f"Could not find map under name {map_name}")

def get_flint_log_channel(guild: hikari.Guild) -> Optional[hikari.TextableGuildChannel]:
    for channel_id, channel in guild.get_channels().items():
        if channel.name == "flint-log" and channel.type == hikari.ChannelType.GUILD_TEXT and isinstance(channel, hikari.TextableGuildChannel):
            return channel
    return None

async def log_action_to_flint(ctx: lightbulb.SlashContext, action: str, player: hikari.User, channel: hikari.GuildChannel):
    guild = await get_guild(ctx)
    flint_log_channel = get_flint_log_channel(guild)
    if flint_log_channel is None:
        return
    await flint_log_channel.send(f"{player.mention} {action} {channel.mention}")

def get_channels_in_category(guild: hikari.Guild, category: hikari.GuildChannel) -> list[hikari.GuildChannel]:
    channels = []
    for channel_id, channel, in guild.get_channels().items():
        if channel.parent_id == category.id:
            channels.append(channel)
    return channels

def get_channels_in_categories(guild: hikari.Guild, category_ids: list[int]) -> list[hikari.GuildChannel]:
    channels = []
    for channel_id, channel, in guild.get_channels().items():
        if channel.parent_id in category_ids:
            channels.append(channel)
    return channels

async def get_category_for_chats(guild: hikari.Guild, map_name: str, channel_count: int) -> hikari.GuildChannel:
    i = 0
    for i in range(10):
        category = await ensure_category_exists(guild, f"{map_name}-channels-{i}")
        channel_count_in_category = len(get_channels_in_category(guild, category))
        if channel_count_in_category + channel_count <= 45:
            return category
    raise ValueError("Somehow hit i=10 for getting category for chats o.o")

def get_sanitized_player_name(player: hikari.Member) -> str:
    return ''.join((filter(lambda c: c.isalnum() ,player.display_name))).lower()
    
def get_player_location_name(player:hikari.Member, location: str) -> str:
    return f"{get_sanitized_player_name(player)}-{location.lower()}"

async def ensure_location_channel(ctx: lightbulb.SlashContext, guild: hikari.Guild, player: hikari.Member, category: hikari.GuildChannel, map_of_location: Map, location: str, player_in: bool) -> hikari.GuildChannel:
    channel_name = get_player_location_name(player, location)
    for channel in get_channels_in_category(guild, category):
        if channel.name == channel_name:
            return channel
    private_perms = await get_private_perms(guild)
    user_perms = hikari.PermissionOverwrite(
        id=player.id,
        type=hikari.PermissionOverwriteType.MEMBER,
        allow=WRITE_PERMISSIONS if player_in else READ_PERMISSIONS,
        deny=WRITE_DENIES if player_in else READ_DENIES
    )
    perms = [private_perms, user_perms]
    server_settings = settings_manager.get_settings(guild.id)
    if server_settings.admin_role_id is not None:
        perms.append(hikari.PermissionOverwrite(
            id=server_settings.admin_role_id,
            type=hikari.PermissionOverwriteType.ROLE,
            allow=ADMIN_PERMISSIONS,
            deny=ADMIN_DENIES
        ))
    channel = await guild.create_text_channel(channel_name, permission_overwrites=perms, category=category.id)
    await ensure_webhook_on_channel(ctx, channel)
    return channel

async def ensure_spectator_locations_channel(ctx: lightbulb.SlashContext, guild: hikari.Guild, category: hikari.GuildChannel, created_map: Map) -> hikari.GuildChannel:
    channel_name = f"{created_map.name.lower()}-locations"
    for channel in get_channels_in_category(guild, category):
        if channel.name == channel_name:
            return channel
    private_perms = await get_private_perms(guild)
    perms = [private_perms]
    server_settings = settings_manager.get_settings(guild.id)
    if server_settings.admin_role_id is not None:
        perms.append(hikari.PermissionOverwrite(
            id=server_settings.admin_role_id,
            type=hikari.PermissionOverwriteType.ROLE,
            allow=ADMIN_PERMISSIONS,
            deny=ADMIN_DENIES
        ))
    if server_settings.spectator_role_id is not None:
        perms.append(hikari.PermissionOverwrite(
            id=server_settings.spectator_role_id,
            type=hikari.PermissionOverwriteType.ROLE,
            allow=READ_PERMISSIONS,
            deny=READ_DENIES
        ))
    channel = await guild.create_text_channel(channel_name, permission_overwrites=perms, category=category.id)
    await ensure_webhook_on_channel(ctx, channel)
    return channel

async def ensure_spectator_channel(ctx: lightbulb.SlashContext, guild: hikari.Guild, category: hikari.GuildChannel, map_of_location: Map, location: str) -> hikari.GuildChannel:
    channel_name = f"{map_of_location.name.lower()}-{location.lower()}"
    for channel in get_channels_in_category(guild, category):
        if channel.name == channel_name:
            return channel
    private_perms = await get_private_perms(guild)
    perms = [private_perms]
    server_settings = settings_manager.get_settings(guild.id)
    if server_settings.admin_role_id is not None:
        perms.append(hikari.PermissionOverwrite(
            id=server_settings.admin_role_id,
            type=hikari.PermissionOverwriteType.ROLE,
            allow=ADMIN_PERMISSIONS,
            deny=ADMIN_DENIES
        ))
    if server_settings.spectator_role_id is not None:
        perms.append(hikari.PermissionOverwrite(
            id=server_settings.spectator_role_id,
            type=hikari.PermissionOverwriteType.ROLE,
            allow=READ_PERMISSIONS,
            deny=READ_DENIES
        ))
    channel = await guild.create_text_channel(channel_name, permission_overwrites=perms, category=category.id)
    await ensure_webhook_on_channel(ctx, channel)
    return channel

def find_locations_channel(guild: hikari.Guild, map_to_use: Map) -> Optional[hikari.TextableGuildChannel]:
    for channel_id, channel in guild.get_channels().items():
        if channel.name == f"{map_to_use.name.lower()}-locations" and isinstance(channel, hikari.TextableGuildChannel):
            return channel
    return None

def separate_link_markdown(s: str) -> Optional[tuple[str, str]]:
    match = re.match(link_pattern, s)
    return (match.group(1), match.group(2)) if match else None

cached_locations_channel_message_arrays: dict[str, list[hikari.Message]] = {}
async def get_locations_channel_message_array(locations_channel: hikari.TextableGuildChannel, map_to_use: Map) -> list[hikari.Message]:
    if map_to_use.name in cached_locations_channel_message_arrays:
        return cached_locations_channel_message_arrays[map_to_use.name]
    locations_channel_message_array = []
    async for message in locations_channel.fetch_history():
        locations_channel_message_array.append(message)

    locations_channel_message_array = locations_channel_message_array[::-1]
    return locations_channel_message_array
    
def cache_locations_channel_message_array(map_name: str, message_array: list[hikari.Message]) -> None:
    cached_locations_channel_message_arrays[map_name] = message_array

async def locations_message(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_to_use: Map, players_changed: list[hikari.Member], change_message: Optional[hikari.Message], new_location: Optional[str]) -> None:
    locations_channel = find_locations_channel(guild, map_to_use)
    if not locations_channel:
        return
    locations_channel_message_array = []

    locations_channel_message_array = await get_locations_channel_message_array(locations_channel, map_to_use)
    locations_channel_message_str = "\n".join(list(map(lambda m: m.content if m.content is not None else "", locations_channel_message_array)))
    if not locations_channel_message_str and new_location is not None:
        players_list = ", ".join(list(map(lambda player_changed: f"[{get_sanitized_player_name(player_changed).capitalize()}]({change_message.make_link(guild) if change_message else 'https://example.com'})", players_changed)))
        await locations_channel.send(f"{new_location.capitalize()}: {players_list}\n")
        return
    
    new_message = ""
    locations_visited = set()
    sanitized_player_names = set(map(lambda player_changed: get_sanitized_player_name(player_changed), players_changed))
    for line in locations_channel_message_str.split('\n'):
        if line.strip() == "":
            new_message += line + "\n"
            continue
        split_line = line.split(':')
        if len(split_line) < 2:
            new_message += line + "\n"

        location = split_line[0].strip().lower()
        locations_visited.add(location)
        players_with_links: list[tuple[str, str]] = [
            link
            for entry in ":".join(split_line[1:]).strip().split(',')
            if (link := separate_link_markdown(entry.strip())) is not None
        ]
        new_players_with_links = []
        for player_with_link in players_with_links:
            if player_with_link[0].lower() not in sanitized_player_names:
                new_players_with_links.append(player_with_link)
        if new_location is not None and location == new_location.lower():
            for player_changed in players_changed:
                new_players_with_links.append((get_sanitized_player_name(player_changed).capitalize(), change_message.make_link(guild) if change_message else "https://example.com"))
        if len(new_players_with_links) == 0:
            continue
        new_message += f"{location.capitalize()}: {', '.join(map(lambda entry: f'[{entry[0]}]({entry[1]})', new_players_with_links))}\n"
    if new_location is not None and new_location not in locations_visited:
        players_list = ", ".join(list(map(lambda player_changed: f"[{get_sanitized_player_name(player_changed).capitalize()}]({change_message.make_link(guild) if change_message else 'https://example.com'})", players_changed)))
        new_message += f"{new_location.capitalize()}: {players_list}\n"

    if not new_message:
        return
    
    current_message = ""
    current_message_index = 0
    new_locations_channel_message_array = []
    for line in new_message.split('\n'):
        if len(current_message) + len(line) > 1800:
            if current_message_index >= len(locations_channel_message_array):
                await locations_channel.send(current_message)
            else:
                await locations_channel_message_array[current_message_index].edit(content=current_message)
            current_message = ""
            current_message_index += 1
        current_message += "\n" + line
    if current_message:
        if current_message_index >= len(locations_channel_message_array):
            new_locations_channel_message_array.append(await locations_channel.send(current_message))
        else:
            new_locations_channel_message_array.append(await locations_channel_message_array[current_message_index].edit(content=current_message))
    cache_locations_channel_message_array(map_to_use.name, new_locations_channel_message_array)
    current_message_index += 1
    while current_message_index < len(locations_channel_message_array):
        await locations_channel_message_array[current_message_index].delete()
        current_message_index += 1

def get_all_location_channels_for_map(guild: hikari.Guild, map_name: str) -> list[hikari.GuildChannel]:
    map_chat_category_ids: list[int] = []
    for channel_id, channel in guild.get_channels().items():
        if channel.name is not None and f"{map_name}-channels-" in channel.name and (channel.type == hikari.channels.ChannelType.GUILD_CATEGORY): # pyright: ignore[reportAttributeAccessIssue]
            map_chat_category_ids.append(channel.id)
    return get_channels_in_categories(guild, map_chat_category_ids)

def get_player_location_channels(guild: hikari.Guild, player: hikari.Member, map_name: str) -> list[hikari.GuildChannel]:
    map_chat_category_ids: list[int] = []
    for channel_id, channel in guild.get_channels().items():
        if channel.name is not None and f"{map_name}-channels-" in channel.name and (channel.type == hikari.channels.ChannelType.GUILD_CATEGORY):  # pyright: ignore[reportAttributeAccessIssue]
            map_chat_category_ids.append(channel.id)
    player_location_channels = []
    for channel in get_channels_in_categories(guild, map_chat_category_ids):
        if channel.name is not None and f"{get_sanitized_player_name(player)}-" in channel.name:
            player_location_channels.append(channel)
    return player_location_channels

def get_maps_player_is_in(guild: hikari.Guild, player: hikari.Member) -> list[Map]:
    server_maps = atlas.get_maps_in_server(guild.id)
    maps_player_is_in = []
    for server_map in server_maps:
        if get_player_location_channels(guild, player, server_map.name):
            maps_player_is_in.append(server_map)
    return maps_player_is_in

def get_category_of_channel(guild: hikari.Guild, channel_id: int) -> Optional[hikari.GuildChannel]:
    nullable_channel = guild.get_channel(channel_id)
    if nullable_channel is None:
        return None
    channel: hikari.GuildChannel = nullable_channel
    return guild.get_channel(channel.parent_id) if channel.parent_id is not None else None

def get_map_name_from_category(category_name: str) -> Optional[str]:
    split_name = category_name.split("-")
    return split_name[0] if len(split_name) > 1 else None

def get_active_channel_for_player_in_map(guild: hikari.Guild, player: hikari.Member, map_to_use: Map) -> Optional[hikari.TextableGuildChannel]:
    player_location_channels = get_player_location_channels(guild, player, map_to_use.name)
    for player_location_channel in player_location_channels:
        if player.id in player_location_channel.permission_overwrites and player_location_channel.permission_overwrites[player.id].allow.SEND_MESSAGES and isinstance(player_location_channel, hikari.TextableGuildChannel):
            return player_location_channel
    return None

def get_player_location_channel_in_map(guild: hikari.Guild, player: hikari.Member, map_to_use: Map, location: str) -> Optional[hikari.TextableGuildChannel]:
    player_location_channels = get_player_location_channels(guild, player, map_to_use.name)
    location_channel_name = get_player_location_name(player, location)
    filtered_player_location_channels = [
        player_location_channel
        for player_location_channel in player_location_channels
        if player_location_channel.name == location_channel_name and isinstance(player_location_channel, hikari.TextableGuildChannel)
    ]
    return filtered_player_location_channels[0] if filtered_player_location_channels else None

async def get_players_in_map_with_role(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_to_use: Map, role: hikari.Role) -> list[hikari.Member]:
    players_with_role_in_map = []
    all_location_channels = get_all_location_channels_for_map(guild, map_to_use.name)
    for location_channel in all_location_channels:
        player = await get_player_from_location(ctx.bot, guild, location_channel)
        if player is not None and role.id in player.role_ids:
            players_with_role_in_map.append(player)
    return players_with_role_in_map

async def get_player_to_location_channel_map_for_players(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_to_use: Map, players: list[hikari.Member]) -> dict[hikari.Member, hikari.GuildTextChannel]:
    player_to_location_channel_map = {}
    all_location_channels = get_all_location_channels_for_map(guild, map_to_use.name)
    player_ids = list(map(lambda p: p.id, players))
    for location_channel in all_location_channels:
        player = await get_player_from_location(ctx.bot, guild, location_channel)
        if player is not None and player.id in player_ids:
            player_to_location_channel_map[player] = location_channel
    return player_to_location_channel_map

async def make_channel_readable_for_player(channel: hikari.GuildChannel, player: hikari.Member):
    permissions = hikari.PermissionOverwrite(
        id=player.id,
        type=hikari.PermissionOverwriteType.MEMBER,
        allow=READ_PERMISSIONS,
        deny=READ_DENIES
    )
    return await channel.edit(permission_overwrites=[permissions])

async def make_channel_writeable_for_player(channel: hikari.GuildChannel, player: hikari.Member):
    permissions = hikari.PermissionOverwrite(
        id=player.id,
        type=hikari.PermissionOverwriteType.MEMBER,
        allow=WRITE_PERMISSIONS,
        deny=WRITE_DENIES
    )
    return await channel.edit(permission_overwrites=[permissions])

def get_location_channels_location(channel: hikari.GuildChannel) -> Optional[str]:
    if channel.name is None:
        return None
    split_channel = channel.name.split('-')
    if len(split_channel) < 2:
        return None
    return "-".join(split_channel[1:])

async def ensure_webhook_on_channel(ctx: lightbulb.SlashContext, channel: hikari.GuildChannel) -> hikari.PartialWebhook:
    if not isinstance(channel, hikari.GuildTextChannel):
        raise ValueError("Trying to attach webhook to non-text-channel")
    text_channel: hikari.GuildTextChannel = channel
    channel_webhooks = await ctx.bot.rest.fetch_channel_webhooks(text_channel)
    for webhook in channel_webhooks:
        if webhook.name == WEBHOOK_NAME:
            return webhook
    webhook = await ctx.bot.rest.create_webhook(text_channel, WEBHOOK_NAME)
    return webhook

async def get_player_from_location(bot: lightbulb.BotApp, guild: hikari.Guild, location_channel: hikari.GuildChannel) -> Optional[hikari.Member]:
    channel_permissions = location_channel.permission_overwrites
    for overwrite_id, permission in channel_permissions.items():
        if permission.type != hikari.PermissionOverwriteType.MEMBER:
            continue
        player_id = permission.id
        nullable_player = guild.get_member(player_id)
        channel_player: hikari.Member = nullable_player if nullable_player is not None else await bot.rest.fetch_member(guild.id, player_id)
        return channel_player
    return None # player could have left server

async def get_players_in_location(bot: lightbulb.BotApp, guild: hikari.Guild, map_channels: list[hikari.GuildChannel], location:str) -> list[hikari.Member]:
    location_players = []
    for map_channel in map_channels:
        map_channel_location = get_location_channels_location(map_channel)
        if location == map_channel_location:
            channel_permissions = map_channel.permission_overwrites
            player = await get_player_from_location(bot, guild, map_channel)
            if player is not None:
                location_players.append(player)
    return location_players

def find_spectator_channel(guild: hikari.Guild, map_to_use: Map, location: str) -> Optional[hikari.GuildTextChannel]:
    nullable_spectator_channel_category = None
    for possible_spectator_category_id, possible_spectator_category in guild.get_channels().items():
        if possible_spectator_category.name == f"{map_to_use.name.lower()}-spectator" and possible_spectator_category.type == hikari.ChannelType.GUILD_CATEGORY:
            nullable_spectator_channel_category = possible_spectator_category
            break
    if nullable_spectator_channel_category is None:
        return None
    spectator_channel_category: hikari.GuildChannel = nullable_spectator_channel_category
    spectator_channels = get_channels_in_category(guild, spectator_channel_category)
    for spectator_channel in spectator_channels:
        if not isinstance(spectator_channel, hikari.GuildTextChannel):
            continue
        spectator_text_channel: hikari.GuildTextChannel = spectator_channel
        spectator_location = get_location_channels_location(spectator_text_channel)
        if spectator_location == location:
            return spectator_text_channel
    return None

async def ensure_location_role(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_name: str, location: str) -> hikari.Role:
    existing_roles = await guild.fetch_roles()
    location_role_name = f"{map_name.lower()}-{location.lower()}"
    for role in existing_roles:
        if location_role_name == role.name:
            return role
    return await ctx.bot.rest.create_role(guild, name=location_role_name)

async def set_new_location_role(ctx: lightbulb.SlashContext, player: hikari.Member, guild: hikari.Guild, map_name: str, location: str) -> list[hikari.Role]:
    roles = await player.fetch_roles()
    roles = list(filter(lambda r: not r.name.startswith(f"{map_name.lower()}-"), roles))
    new_role = await ensure_location_role(ctx, guild, map_name, location)
    roles.append(new_role)
    await player.edit(roles=roles)
    return roles

def replace_rpt_emotes(s: str) -> str:
    s = s.replace("<:RPTblank:602609116334129171>", "<:RPTblank:1054538954982035496>")
    s = s.replace("<:NRG:870956313344090142>", "<:NRG:1055177876401573928>")
    s = s.replace("<:rawmanna:789156956292120576>", "<:rawmanna:1055177874526715904>")
    s = s.replace("<:RPTmark:604411500744146984>", "<:RPTmark:1055177873109041243>")
    return s

async def find_message_in_channel(bot: hikari.GatewayBot, channel: hikari.GuildTextChannel, original_content: str) -> Optional[hikari.Message]:
    if original_content.startswith("*In Reply to"):
        original_content_lines = original_content.split('\n')
        original_content = "\n".join(original_content_lines[2:])
    i = 0
    async for message in bot.rest.fetch_messages(channel):
        if i == 99:
            break
        if message.content == original_content:
            return message
        i += 1
    return None

def transform_text_content(bot: hikari.GatewayBot, content: str) -> str:
    is_only_emote = re.match(emote_pattern, content)
    if is_only_emote:
        cached_emoji = bot.cache.get_emoji(int(is_only_emote.group(2)))
        if not cached_emoji:
            postfix = "gif" if is_only_emote.group(1) else "png"
            content = f"https://cdn.discordapp.com/emojis/{is_only_emote.group(2)}.{postfix}?size=48"
    content = replace_rpt_emotes(content)
    return content

async def execute_mirrored_webhook(bot: hikari.GatewayBot, webhook: hikari.ExecutableWebhook, display_name: hikari.UndefinedOr[str], message: hikari.Message, channel: hikari.GuildTextChannel):
    content = message.content or ""
    embeds = message.embeds
    avatar_url: Union[hikari.UndefinedType, str, hikari.URL] = message.author.avatar_url or hikari.UNDEFINED
    avatar_url = message.member.guild_avatar_url if message.member and message.member.guild_avatar_url else avatar_url
    
    if ((content.startswith("https://") or content.startswith("http://")) and 
        len(content.split(' ')) == 1 
        and len(embeds) == 1 and not embeds[0].author and not embeds[0].description and not embeds[0].fields
        and embeds[0].url == content):
        embeds = []
    content = transform_text_content(bot, content)
    if message.stickers:
        content = f"https://media.discordapp.net/stickers/{message.stickers[0].id}.png?size=160"
    for embed in embeds:
        embed.description = replace_rpt_emotes(embed.description) if embed.description is not None else None
        for field in embed.fields:
            if field is not None:
                field.value = replace_rpt_emotes(field.value)
    if message.referenced_message and len(content) < 1750 and message.referenced_message.content:
        found_message = await find_message_in_channel(bot, channel, message.referenced_message.content)
        if found_message:
            quoted_reply = f"*In Reply to {found_message.make_link(channel.get_guild())}*"
            content = f"{quoted_reply}\n\n{content}"

    await webhook.execute(
        content=content,
        username=display_name,
        avatar_url=avatar_url,
        attachments=message.attachments,
        user_mentions=message.user_mentions_ids if hasattr(message, 'user_mentions_ids') else [],
        embeds=embeds,
        mentions_everyone=False,
        flags=message.flags
    )

async def edit_location_to_move(player: hikari.Member, location_channel: hikari.GuildChannel, new_location: str) -> tuple[bool, float]:
    try:
        await location_channel.edit(name=get_player_location_name(player, new_location))
        return True, 0
    except hikari.RateLimitedError as e:
        return False, e.retry_after

async def move_players_to_location(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_to_use: Map, players: list[hikari.Member], new_location: str, team_name: Optional[str], ignore_cooldown: bool) -> None:
    settings = settings_manager.get_settings(guild.id)
    player = await interactionMemberEnforcer.ensure_type(ctx.interaction.member, ctx, "Could not determine which member issued the command")
    async with map_to_use.cond:
        moved_players = {}
        players_left_behind = []
        players_already_there = []

        if new_location not in map_to_use.locations:
            await ctx.respond(f"{new_location} is not in the map you are moving with")
            return
        
        if new_location in map_to_use.role_requirements:
            found_good_role = False
            for role_id in player.role_ids:
                if role_id in map_to_use.role_requirements[new_location]:
                    found_good_role = True
                    break
            if not found_good_role:
                await ctx.respond(f"You do not have the required role to move to {new_location}")
                return
        
        player_to_location_channel = await get_player_to_location_channel_map_for_players(ctx, guild, map_to_use, players)

        async def attempt_edit(player: hikari.Member, location_channel: hikari.GuildChannel, location: str):
            result, _ = await edit_location_to_move(player, location_channel, new_location)
            return player, result, location
        
        async_tasks = []
        for player, location_channel in player_to_location_channel.items():
            location = get_location_channels_location(location_channel)
            if location is None:
                players_left_behind.append((player, "Could not determine current location"))
                continue
            if location == new_location:
                players_already_there.append(player)
                continue
            if not ignore_cooldown and player.id in map_to_use.cooldowns:
                last_movement_time: datetime.datetime = map_to_use.cooldowns[player.id]
                next_possible_movement_time = last_movement_time + datetime.timedelta(minutes=settings.cooldown_minutes)
                diff = next_possible_movement_time - datetime.datetime.now()
                if diff.total_seconds() > 0:
                    players_left_behind.append((player, f"Cooldown has {diff.total_seconds()} seconds left"))
                    continue
            async_tasks.append(asyncio.create_task(attempt_edit(player, location_channel, location)))
        await asyncio.gather(*async_tasks)
        for task in async_tasks:
            player, success, location = task.result()
            if success:
                moved_players[location] = moved_players.get(location, []) + [player]
                map_to_use.reset_cooldown(player.id)
            else:
                players_left_behind.append((player, f"Discord rate limits"))

        moved_players_list = flatten_list_of_lists(moved_players.values())
        if not moved_players:
            if len(players) == 1 and players_left_behind:
                await ctx.respond(f"Could not move to {new_location}: {players_left_behind[0][1]}")
                return
            elif len(players) == 1 and players_already_there:
                await ctx.respond(f"Already in {new_location}")
                return
            await ctx.respond(f"No players were moved, all players were either already in {new_location} or left behind due to cooldowns or missing roles")
            return
        async_tasks = []
        if settings.announce_entry and player_to_location_channel:
            location_channel = list(player_to_location_channel.values())[0]
            category = get_category_of_channel(guild, location_channel.id)
            if category is not None:
                chat_channels = get_channels_in_category(guild, category)
                moved_player_ids = set(map(lambda p: p.id, moved_players_list))
                moved_players_string = ", ".join(map(lambda p: p.display_name, moved_players_list))
                for chat_channel in chat_channels:
                    if not isinstance(chat_channel, hikari.TextableGuildChannel):
                        continue
                    chat_player = await get_player_from_location(ctx.bot, guild, chat_channel) # shouldn't actually wait for it most of the time
                    if chat_player is None or chat_player.id in moved_player_ids:
                        continue
                    chat_text_channel: hikari.TextableGuildChannel = chat_channel
                    chat_channel_location = get_location_channels_location(chat_text_channel)
                    if chat_channel_location == new_location:
                        async_tasks.append(asyncio.create_task(chat_text_channel.send(f"{moved_players_string} {'have' if len(moved_players_list) > 1 else 'has'} entered {new_location}")))
        await asyncio.gather(*async_tasks)
        nullable_spectator_to_text_channel = find_spectator_channel(guild, map_to_use, new_location)
        to_message = None
        movees_name = f"Team {team_name}" if team_name is not None else players[0].display_name
        if nullable_spectator_to_text_channel is not None:
            to_message = await nullable_spectator_to_text_channel.send(
                f"{movees_name} moved to {new_location}")
        async_tasks = []
        for location, players in moved_players.items():
            nullable_spectator_from_text_channel = find_spectator_channel(guild, map_to_use, location)
            if nullable_spectator_from_text_channel is not None:
                location_text = new_location if to_message is None else f"[{new_location}]({to_message.make_link(guild)})"
                async_tasks.append(asyncio.create_task(nullable_spectator_from_text_channel.send(
                    f"{movees_name} moved from {location} to {location_text}")))
        if settings.should_track_roles:
            for player in flatten_list_of_lists(moved_players.values()):
                async_tasks.append(asyncio.create_task(set_new_location_role(ctx, player, guild, map_to_use.name, new_location)))
        channel = guild.get_channel(ctx.channel_id)
        if channel is not None:
            for player in flatten_list_of_lists(moved_players.values()):
                async_tasks.append(asyncio.create_task(log_action_to_flint(ctx, "move", player, channel)))
        if len(players) > 1:
            async_tasks.append(asyncio.create_task(ctx.respond(
                f"""Players moved to {new_location}: {', '.join(map(lambda p: p.display_name, flatten_list_of_lists(moved_players.values())))}
    Players left behind: {', '.join(map(lambda p: f"{p[0].display_name} ({p[1]})", players_left_behind)) if players_left_behind else 'None'}
    Players already there: {', '.join(map(lambda p: p.display_name, players_already_there)) if players_already_there else 'None'}"""
            )))
        else:
            async_tasks.append(asyncio.create_task(ctx.respond(
                f"""Player moved to {new_location}""")))
        async_tasks.append(asyncio.create_task(locations_message(ctx, guild, map_to_use, flatten_list_of_lists(moved_players.values()), to_message, new_location)))
        await asyncio.gather(*async_tasks)

def message_is_bot_or_commandlike(message: hikari.PartialMessage) -> bool:
    return (message.content is not None and message.content is not hikari.UNDEFINED and message.content[0] in ("=", "!", "/", "?", ".")) or (bool(message.author) and message.author.is_bot)

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("locations", "Comma separated list of locations (eg. 'forest, beach'), that people can move to (first is default)", type=str)
@lightbulb.option("map-name", "Name the map will have, will be a prefix for all map-related channels", type=str)
@lightbulb.command("create-map", "Creates a map with the given name, and the locations (comma-separated)")
@lightbulb.implements(commands.SlashCommand)
async def create_map(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding map...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    map_name = ctx.options['map-name'].lower()
    locations = list(map(lambda location: location.strip(), ctx.options['locations'].split(',')))
    if ' ' in map_name or '-' in map_name:
        await ctx.respond("map_name: `{}` cannot have a space or - in it".format(map_name))
        return
    for location in locations:
        if ' ' in location:
            await ctx.respond("location name: `{}` cannot have a space in it".format(location))
            return

    created_map = await atlas.create_map(guild.id, map_name, locations)
    async with created_map.cond:
        await ensure_category_exists(guild, f"{created_map.name}-channels-0")
        category = await ensure_category_exists(guild, f"{created_map.name}-spectator")
        await ensure_spectator_locations_channel(ctx, guild, category, created_map)
        for location in locations:
            await ensure_spectator_channel(ctx, guild, category, created_map, location)
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_UPDATE, f"Map {created_map.name} created with locations: `{locations}`")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("player", "Member you want to add to the given map", type=hikari.Member)
@lightbulb.option("map-name", "Name of the map the player will be added to, must already exist", type=str)
@lightbulb.command("add-player", "Adds the given member to the given map, placing them in the map's default location")
@lightbulb.implements(commands.SlashCommand)
async def add_player(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding player to map...", flags=hikari.MessageFlag.LOADING)
    map_name = ctx.options["map-name"].lower()
    guild = await get_guild(ctx)
    player = await memberEnforcer.ensure_type(ctx.options['player'], ctx, "Somehow couldn't get player from the command")
    fetched_map = await get_map(ctx, guild, map_name)
    async with fetched_map.cond:
        category_for_chats = await get_category_for_chats(guild, fetched_map.name, 1)
        starting_location = fetched_map.locations[0]
        channel = await ensure_location_channel(ctx, guild, player, category_for_chats, fetched_map, starting_location, True)
        nullable_spectator_text_channel = find_spectator_channel(guild, fetched_map, starting_location)
        settings = settings_manager.get_settings(guild.id)
        if settings.should_track_roles:
            await set_new_location_role(ctx, player, guild, fetched_map.name, starting_location)
        if nullable_spectator_text_channel is not None:
            spec_message = await nullable_spectator_text_channel.send(f"{player.mention} finds themselves on {fetched_map.name}")
            await locations_message(ctx, guild, fetched_map, [player], spec_message, starting_location)
        await ctx.respond(f"{get_sanitized_player_name(player)} added to {fetched_map.name} at {fetched_map.locations[0]}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("map-name", "Name of the map where talking will be toggled", type=str)
@lightbulb.command("toggle-talking", "Toggles whether talking is disabled/enabled in a given map")
@lightbulb.implements(commands.SlashCommand)
async def toggle_talking(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Toggling talking on the map...", flags=hikari.MessageFlag.LOADING)
    map_name = ctx.options["map-name"].lower()
    guild = await get_guild(ctx)
    result = await atlas.toggle_talking(guild.id, map_name)
    if result is None:
        await ctx.respond(f"Something went wrong, unsure of current state of talking in {map_name}")
        return 
    await ctx.respond(f"Talking in {map_name} is now {'on' if result else 'off'}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("toggle-announce-entry", "Toggles announcing to everyone in a map when a player enters")
@lightbulb.implements(commands.SlashCommand)
async def toggle_announce_entry(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Toggling entry announcements...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    server_settings = settings_manager.get_settings(guild.id)
    new_value = not server_settings.announce_entry
    await settings_manager.set_announce_entry(guild.id, new_value)
    await ctx.respond(f"{'Enabled' if new_value else 'Disabled'} entry")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("player", "Member you want to remove from the given map", type=hikari.Member)
@lightbulb.option("map-name", "Name of the map the player will be removed from", type=str)
@lightbulb.command("remove-player", 'Removes the given member from the given map, deleting "their" channels')
@lightbulb.implements(commands.SlashCommand)
async def remove_player(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Removing player from map...", flags=hikari.MessageFlag.LOADING)
    map_name = ctx.options["map-name"].lower()
    guild = await get_guild(ctx)
    player = ctx.options['player']
    fetched_map = await get_map(ctx, guild, map_name)
    active_location_channel = await guildChannelEnforcer.ensure_type(get_active_channel_for_player_in_map(guild, player, fetched_map), ctx, "Player is not active on the map...")
    active_location = await stringEnforcer.ensure_type(get_location_channels_location(active_location_channel), ctx, "Player is not active on the map...")
    async with fetched_map.cond:
        for channel in get_player_location_channels(guild, player, fetched_map.name):
            await channel.delete()
        await locations_message(ctx, guild, fetched_map, [player], None, None)
    nullable_spectator_text_channel = find_spectator_channel(guild, fetched_map, active_location)
    if nullable_spectator_text_channel is not None:
        await nullable_spectator_text_channel.send(f"{player.mention} removed from {fetched_map.name}")
    settings = settings_manager.get_settings(guild.id)
    if settings.should_track_roles:    
        roles = await player.fetch_roles()
        roles = list(filter(lambda r: not r.name.startswith(f"expedition-{fetched_map.name.lower()}-"), roles))
        await player.edit(roles=roles)
    await ctx.respond(f"{get_sanitized_player_name(player)} removed from {fetched_map.name}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("location", "Where you want to move the player", type=str)
@lightbulb.option("map-name", "Name of the map the player will be moved in", type=str)
@lightbulb.option("player", "Member you want to move", type=hikari.Member)
@lightbulb.command("move-player", "Moves the given member to the given location in the given map")
@lightbulb.implements(commands.SlashCommand)
async def move_player(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Moving player...", flags=hikari.MessageFlag.LOADING)
    map_name = ctx.options["map-name"].lower()
    guild = await get_guild(ctx)
    player = ctx.options['player']
    location = ctx.options['location'].lower()
    map_to_use = await get_map(ctx, guild, map_name)
    maps_player_is_in = get_maps_player_is_in(guild, player)
    if map_to_use not in maps_player_is_in:
        await ctx.respond(f"{player.display_name} is not in {map_name}")
        return
    await move_players_to_location(ctx, guild, map_to_use, [player], location, None, True)

@plugin.command
@lightbulb.option("location", "Where you want to move the player", type=str)
@lightbulb.option("map-name", "Name of the map the player will be moved in", type=str)
@lightbulb.option("team", "Team role you want to move, rolename must contain 'team' or 'tribe'", type=hikari.Role)
@lightbulb.command("move-team", "Moves all players of a role to a location, can only be used by admins or team members")
@lightbulb.implements(commands.SlashCommand)
async def move_team(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Moving team...", flags=hikari.MessageFlag.LOADING)
    map_name: str = ctx.options["map-name"].lower()
    guild = await get_guild(ctx)
    new_location: str = ctx.options['location'].lower()
    team_role: hikari.Role = ctx.options['team']
    map_to_use = await get_map(ctx, guild, map_name)
    player = await interactionMemberEnforcer.ensure_type(ctx.interaction.member, ctx, "Somehow couldn't get player from the command")
    if "tribe" not in team_role.name.lower() and "team" not in team_role.name.lower():
        await ctx.respond(f"Role {team_role.name} does not contain 'team' or 'tribe', please use a different role")
        return
    if player and player.permissions & hikari.Permissions.MANAGE_GUILD == 0 and team_role.id not in player.role_ids:
        await ctx.respond("You are not allowed to move other teams, only admins or team members can do that")
        return
    players_to_move = await get_players_in_map_with_role(ctx, guild, map_to_use, team_role)
    await move_players_to_location(ctx, guild, map_to_use, players_to_move, new_location, team_role.name, True)

@plugin.command
@lightbulb.option("location", "Where you want to go", type=str)
@lightbulb.command("move", "Moves to the given location, based on your current map")
@lightbulb.implements(commands.SlashCommand)
async def move(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Moving you...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    player = await memberEnforcer.ensure_type(ctx.member, ctx, "Somehow couldn't find the player associated with who performed the command, contact the admins")
    location = ctx.options['location'].lower()
    maps_player_is_in = get_maps_player_is_in(guild, player)
    if not maps_player_is_in:
        await ctx.respond("Cannot move when you're not in a map")
        return
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        error_message = "Since you are in two maps, we need you to use the move command in the map you want to move in"
        category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
        category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
        map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
        if map_name not in map(lambda m: m.name, maps_player_is_in):
            await ctx.respond(error_message)
            return
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    await move_players_to_location(ctx, guild, map_to_use, [player], location, None, False)

@plugin.command
@lightbulb.command("whos-here", "Moves to the given location, based on your current map")
@lightbulb.implements(commands.SlashCommand)
async def whos_here(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Determining who's in your location...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    player = await memberEnforcer.ensure_type(ctx.member, ctx, "Somehow couldn't find the player associated with who performed the command, contact the admins")
    maps_player_is_in = get_maps_player_is_in(guild, player)
    if not maps_player_is_in:
        await ctx.respond("You're not in a map")
        return
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        error_message = "Since you are in two maps, we need you to use the command in the map you want check on"
        category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
        category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
        map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
        if map_name not in map(lambda m: m.name, maps_player_is_in):
            await ctx.respond(error_message)
            return
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    active_channel = await guildChannelEnforcer.ensure_type(
        get_active_channel_for_player_in_map(guild, player, map_to_use), ctx, "Could not find a channel you are active in for your location, if this is an error contact the admins")
    category = await guildChannelEnforcer.ensure_type(
        get_category_of_channel(guild, active_channel.id), ctx, "Could not find category of active channel, contact the admins")
    location = await stringEnforcer.ensure_type(get_location_channels_location(active_channel), ctx, "Could not determine location from your active channel, contact the admins")
    map_channels = get_channels_in_category(guild, category)
    location_players = await get_players_in_location(ctx.bot, guild, map_channels, location)
    if len(location_players) <= 1:
        await ctx.respond(f"You're the only one in {location}")
        return
    players_string = ', '.join(map(lambda p: f"{p.mention} ({p.display_name})", location_players))
    await ctx.respond(f"{players_string} are in {location}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("role", "Role that will have read-access on all spectator channels", type=hikari.Role)
@lightbulb.command("spectator-role", "Set role that all subsequently created channels will have that role as a spectator")
@lightbulb.implements(commands.SlashCommand)
async def spectator_role(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting spectator role id...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    role: hikari.Role = ctx.options['role']
    await settings_manager.set_spectator_role_id(guild.id, role.id)
    await ctx.respond(f"{role.mention} set as spectator role for the server")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("role", "Role that will have manage-access on all expedition channels", type=hikari.Role)
@lightbulb.command("admin-role", "Set role that all subsequently created channels will have that role as an admin")
@lightbulb.implements(commands.SlashCommand)
async def admin_role(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting admin role id...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    role: hikari.Role = ctx.options['role']
    await settings_manager.set_admin_role_id(guild.id, role.id)
    await ctx.respond(f"{role.mention} set as admin role for the server")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("enable-role-tracking", "Players added to a map will get roles matching to the locations they are in with this enabled")
@lightbulb.implements(commands.SlashCommand)
async def enable_role_tracking(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Enabling role tracking...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    await settings_manager.set_should_track_roles(guild.id, True)
    await ctx.respond(f"Enabled role tracking")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("disable-role-tracking", "Players added to a map will not get roles matching to the locations they are in with this disabled")
@lightbulb.implements(commands.SlashCommand)
async def disable_role_tracking(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Disabling role tracking...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    await settings_manager.set_should_track_roles(guild.id, False)
    await ctx.respond(f"Disabled role tracking")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("toggle-bot-and-command-mirroring", "Turns on/off command like and bot messages mirroring to spectator channels, default on")
@lightbulb.implements(commands.SlashCommand)
async def toggle_sync_commands_and_bots_to_spectators(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Enabling syncing command and bot messages to spectators...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    server_settings = settings_manager.get_settings(guild.id)
    new_value = not server_settings.sync_commands_and_bots_to_spectators
    await settings_manager.set_sync_commands_and_bots_to_spectators(guild.id, new_value)
    await ctx.respond(f"{'Enabled' if new_value else 'Disabled'} syncing command and bot messages to spectators")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("minutes", "Minutes to set cooldown to (must be >=5)", type=int)
@lightbulb.command("set-movement-cooldown", "How many minutes a player has to wait before moving again (must be >= 5 due to discord rate limits)")
@lightbulb.implements(commands.SlashCommand)
async def set_movement_cooldown(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting cooldown...", flags=hikari.MessageFlag.LOADING)
    minutes = ctx.options['minutes']
    if minutes < 5:
        await ctx.respond("The cooldown must be greater than 5 minutes due to discord rate limits on editing channels")
        return
    guild = await get_guild(ctx)
    await settings_manager.set_cooldown_minutes(guild.id, minutes)
    await ctx.respond(f"Cooldown set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("toggle-yelling", "Turn on/off the ability for players to yell")
@lightbulb.implements(commands.SlashCommand)
async def toggle_yelling(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Toggling yelling...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    server_settings = settings_manager.get_settings(guild.id)
    new_value = not server_settings.yell_enabled
    await settings_manager.set_yell_enabled(guild.id, new_value)
    await ctx.respond(f"{'Enabled' if new_value else 'Disabled'} yelling")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("seconds", "Seconds to set cooldown to (0 means no cooldown, which is default)", type=int)
@lightbulb.command("set-yell-cooldown", "How many seconds a player has to wait between yelling")
@lightbulb.implements(commands.SlashCommand)
async def set_yell_cooldown(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting cooldown...", flags=hikari.MessageFlag.LOADING)
    seconds = ctx.options['seconds']
    guild = await get_guild(ctx)
    await settings_manager.set_yell_cooldown_seconds(guild.id, seconds)
    await ctx.respond(f"Cooldown set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("toggle-whispering", "Turn on/off the ability for players to whisper")
@lightbulb.implements(commands.SlashCommand)
async def toggle_whispering(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Toggling whispering...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    server_settings = settings_manager.get_settings(guild.id)
    new_value = not server_settings.whisper_enabled
    await settings_manager.set_whisper_enabled(guild.id, new_value)
    await ctx.respond(f"{'Enabled' if new_value else 'Disabled'} whispering")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("percentage", "Percent chance to be overheard", type=int)
@lightbulb.command("set-whisper-percentage", "Set how likely it is for a person to be overheard when whispering")
@lightbulb.implements(commands.SlashCommand)
async def set_whisper_percentage(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting whisper percentage...", flags=hikari.MessageFlag.LOADING)
    percentage = ctx.options['percentage']
    guild = await get_guild(ctx)
    await settings_manager.set_whisper_percentage(guild.id, percentage)
    await ctx.respond(f"Percentage set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("seconds", "Seconds to set cooldown to (0 means no cooldown, which is default)", type=int)
@lightbulb.command("set-whisper-cooldown", "How many seconds a player has to wait between whipsering")
@lightbulb.implements(commands.SlashCommand)
async def set_whisper_cooldown(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting cooldown...", flags=hikari.MessageFlag.LOADING)
    seconds = ctx.options['seconds']
    guild = await get_guild(ctx)
    await settings_manager.set_whisper_cooldown_seconds(guild.id, seconds)
    await ctx.respond(f"Cooldown set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.command("toggle-peeking", "Turn on/off the ability for players to peek")
@lightbulb.implements(commands.SlashCommand)
async def toggle_peeking(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Toggling peeking...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    server_settings = settings_manager.get_settings(guild.id)
    new_value = not server_settings.peek_enabled
    await settings_manager.set_peek_enabled(guild.id, new_value)
    await ctx.respond(f"{'Enabled' if new_value else 'Disabled'} peeking")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("percentage", "Percent chance to be seen while peeking", type=int)
@lightbulb.command("set-peek-percentage", "Set how likely it is for a person to be seen while peeking")
@lightbulb.implements(commands.SlashCommand)
async def set_peek_percentage(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting peeking percentage...", flags=hikari.MessageFlag.LOADING)
    percentage = ctx.options['percentage']
    guild = await get_guild(ctx)
    await settings_manager.set_peek_percentage(guild.id, percentage)
    await ctx.respond(f"Percentage set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("seconds", "Seconds to set cooldown to (0 means no cooldown, which is default)", type=int)
@lightbulb.command("set-peek-cooldown", "How many seconds a player has to wait between peeking")
@lightbulb.implements(commands.SlashCommand)
async def set_peek_cooldown(ctx: lightbulb.SlashContext) -> None:
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Setting cooldown...", flags=hikari.MessageFlag.LOADING)
    seconds = ctx.options['seconds']
    guild = await get_guild(ctx)
    await settings_manager.set_peek_cooldown_seconds(guild.id, seconds)
    await ctx.respond(f"Cooldown set")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("map-name", "Name of the map the player will be removed from", type=str)
@lightbulb.command("prepopulate-roles", "Create all roles for a map without needing to go there, useful for setting up for a season")
@lightbulb.implements(commands.SlashCommand)
async def prepopulate_roles(ctx: lightbulb.SlashContext) -> None:
    map_name = ctx.options["map-name"].lower()
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Prepopulating roles tracking...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    map = await mapEnforcer.ensure_type(atlas.get_map(guild.id, map_name), ctx, "Cannot find map with the chosen name")
    for location in map.locations:
        await ensure_location_role(ctx, guild, map_name, location)
    await ctx.respond("Roles pre-populated")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("location-name", "Name of the location to add to the map", type=str)
@lightbulb.option("map-name", "Name of the map the location will be added to", type=str)
@lightbulb.command("add-location", "Add the named location to the given map")
@lightbulb.implements(commands.SlashCommand)
async def add_location(ctx: lightbulb.SlashContext) -> None:
    map_name = ctx.options["map-name"].lower()
    location_name = ctx.options["location-name"].lower()
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding location...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    result_map = await atlas.add_location(guild.id, map_name, location_name)
    if result_map is None:
        await ctx.respond(f"Failed to add {location_name} to {map_name}, this could be because the map doesn't exist, or the location already exists in the map")
        return
    category = await ensure_category_exists(guild, f"{result_map.name}-spectator")
    await ensure_spectator_channel(ctx, guild, category, result_map, location_name)
    await ctx.respond(f"Added {location_name} to {map_name}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("location-name", "Name of the location to remove from the map", type=str)
@lightbulb.option("map-name", "Name of the map the location will be removed from", type=str)
@lightbulb.command("remove-location", "Remove the named location from the given map")
@lightbulb.implements(commands.SlashCommand)
async def remove_location(ctx: lightbulb.SlashContext) -> None:
    map_name = ctx.options["map-name"].lower()
    location_name = ctx.options["location-name"].lower()
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Removing location...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    result_map = await atlas.remove_location(guild.id, map_name, location_name)
    server_settings = settings_manager.get_settings(guild.id)
    if result_map is None:
        await ctx.respond(f"Failed to remove {location_name} from {map_name}, this could be because the map doesn't exist or because the location doesn't exist in it")
        return
    async with result_map.cond:
        location_channels = get_all_location_channels_for_map(guild, result_map.name)
        for location_channel in location_channels:
            if location_channel.name and f"-{location_name}" not in location_channel.name:
                continue
            default_location = result_map.locations[0]
            nullable_player = await get_player_from_location(ctx.bot, guild, location_channel)
            if nullable_player is None:
                continue
            player: hikari.Member = nullable_player
            try:
                await location_channel.edit(name=get_player_location_name(player, default_location))
            except hikari.RateLimitedError as e:
                await ctx.respond(f"{get_sanitized_player_name(player)} moving too quickly for discord rate limits, get them to move in {e.retry_after} seconds")
            nullable_spectator_to_text_channel = find_spectator_channel(guild, result_map, default_location)
            if nullable_spectator_to_text_channel is not None:
                await nullable_spectator_to_text_channel.send(f"{player.display_name} came from {location_name}")
            if server_settings.should_track_roles:
                await set_new_location_role(ctx, player, guild, result_map.name, default_location)    
    await ctx.respond(f"Removed {location_name} from {map_name}")

async def prod_yell(ctx: lightbulb.SlashContext, guild: hikari.Guild, member: hikari.Member):
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Yelling for you...", flags=hikari.MessageFlag.EPHEMERAL)
    error_message = "Can't find which map you want to yell in, run the command in a player's channel"
    category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
    category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
    map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
    server_maps = atlas.get_maps_in_server(guild.id)
    filtered_maps = list(filter(lambda map: map.name == map_name, server_maps))
    if len(filtered_maps) != 1:
        return await ctx.respond("Can't find which map you want to yell in, contact Keegan, code prod_yell:10")
    map_to_use = filtered_maps[0]
    location_channels = get_all_location_channels_for_map(guild, map_to_use.name)
    locations_yelled_in_for_specs = []
    async_tasks = []
    for location_channel in location_channels:
        location = get_location_channels_location(location_channel)
        message = f"{member.display_name} yelled {ctx.options['message']}"
        if location is not None:
            nullable_spectator_channel = find_spectator_channel(guild, map_to_use, location)
            if nullable_spectator_channel is not None and location not in locations_yelled_in_for_specs:
                specator_channel = nullable_spectator_channel
                async_tasks.append(asyncio.create_task(specator_channel.send(message, mentions_everyone=False)))
                locations_yelled_in_for_specs.append(location)
        if isinstance(location_channel, hikari.TextableGuildChannel):
            async_tasks.append(asyncio.create_task(location_channel.send(message, mentions_everyone=False)))
    async_tasks.append(asyncio.create_task(ctx.respond(f"You yelled {ctx.options['message']}")))
    await asyncio.gather(*async_tasks)


@plugin.command
@lightbulb.option("message", "The message you want to yell to all locations", type=str)
@lightbulb.command("yell", "Yell a particular message to all locations, will announce where you are")
@lightbulb.implements(commands.SlashCommand)
async def yell(ctx: lightbulb.SlashContext) -> None:
    guild = await get_guild(ctx)
    player = await memberEnforcer.ensure_type(ctx.member, ctx, "Somehow couldn't find the player associated with who performed the command, contact the admins")
    maps_player_is_in = get_maps_player_is_in(guild, player)
    settings = settings_manager.get_settings(guild.id)
    if not maps_player_is_in:
        if settings.admin_role_id in player.role_ids:
            await prod_yell(ctx, guild, player)
            return
        await ctx.respond("Cannot yell when you're not in a map")
        return
    if not settings.yell_enabled:
        if settings.admin_role_id in player.role_ids:
            await prod_yell(ctx, guild, player)
            return
        await ctx.respond("Yelling is currently disabled")
        return
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        error_message = "Since you are in two maps, we need you to use the yell command in the map you want to yell in"
        category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
        category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
        map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
        if map_name not in map(lambda m: m.name, maps_player_is_in):
            if settings.admin_role_id in player.role_ids:
                await prod_yell(ctx, guild, player)
                return
            await ctx.respond(error_message)
            return
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    if not map_to_use.talking_enabled:
        await ctx.respond(f"Talking is turned off in {map_to_use.name}")
        return
    if settings.yell_cooldown_seconds > 0:
        if player.id in map_to_use.yell_cooldowns:
            last_movement_time: datetime.datetime = map_to_use.yell_cooldowns[player.id]
            next_possible_movement_time = last_movement_time + datetime.timedelta(seconds=settings.yell_cooldown_seconds)
            diff = next_possible_movement_time - datetime.datetime.now()
            if diff.total_seconds() > 0:
                await ctx.respond(f"Yelling in this map is still on cooldown for {diff.total_seconds()} seconds")
                return
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Yelling...", flags=hikari.MessageFlag.LOADING)
    active_channel = await guildChannelEnforcer.ensure_type(get_active_channel_for_player_in_map(guild, player, map_to_use), ctx, "Can't find player's active channel in the map")
    active_location = await stringEnforcer.ensure_type(get_location_channels_location(active_channel), ctx, "Can't find active location")
    location_channels = get_all_location_channels_for_map(guild, map_to_use.name)
    locations_yelled_in_for_specs = []
    async_tasks = []
    for location_channel in location_channels:
        location = await stringEnforcer.ensure_type(get_location_channels_location(location_channel), ctx, f"Can't find location for {location_channel.id}")
        message = f"{player.display_name} yelled {ctx.options['message']}{' from ' + active_location if location.lower() != active_location.lower() else ''}"
        nullable_spectator_channel = find_spectator_channel(guild, map_to_use, location)
        if nullable_spectator_channel is not None and location not in locations_yelled_in_for_specs:
            specator_channel = nullable_spectator_channel
            async_tasks.append(asyncio.create_task(specator_channel.send(message, mentions_everyone=False)))
            locations_yelled_in_for_specs.append(location)
        if location_channel.id != active_channel.id and isinstance(location_channel, hikari.TextableGuildChannel):
            async_tasks.append(asyncio.create_task(location_channel.send(message, mentions_everyone=False)))
    map_to_use.reset_yell_cooldown(player.id)
    channel = guild.get_channel(ctx.channel_id) 
    if channel is not None:
        await log_action_to_flint(ctx, "yell", player, channel)
    async_tasks.append(asyncio.create_task(ctx.respond(f"You yelled {ctx.options['message']}")))
    await asyncio.gather(*async_tasks)

@plugin.command
@lightbulb.option("message", "The message you want to whisper", type=str)
@lightbulb.option("player", "The message you want to whisper to", type=hikari.Member)
@lightbulb.command("whisper", "Whisper to a player, you may be overheard by the others in the location without knowing.")
@lightbulb.implements(commands.SlashCommand)
async def whisper(ctx: lightbulb.SlashContext) -> None:
    guild = await get_guild(ctx)
    player = await memberEnforcer.ensure_type(ctx.member, ctx, "Somehow couldn't find the player associated with who performed the command, contact the admins")
    target = await memberEnforcer.ensure_type(ctx.options['player'], ctx, "Invalid target")
    if player.id == target.id:
        await ctx.respond("You cannot whisper to yourself")
        return
    maps_player_is_in = get_maps_player_is_in(guild, player)
    maps_target_is_in = get_maps_player_is_in(guild, target)
    settings = settings_manager.get_settings(guild.id)
    if not maps_player_is_in:
        await ctx.respond("Cannot whisper when you're not in a map")
        return
    if not settings.whisper_enabled:
        await ctx.respond("Whispering is currently disabled")
        return
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        error_message = "Since you are in two maps, we need you to use the whisper command in the map you want to yell in"
        category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
        category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
        map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
        if map_name not in map(lambda m: m.name, maps_player_is_in):
            if settings.admin_role_id in player.role_ids:
                await prod_yell(ctx, guild, player)
                return
            await ctx.respond(error_message)
            return
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    if not map_to_use.talking_enabled:
        await ctx.respond(f"Talking is turned off in {map_to_use.name}")
        return
    if map_to_use not in maps_target_is_in:
        await ctx.respond(f"Target is not in {map_to_use.name}")
        return
    if settings.whisper_cooldown_seconds > 0:
        if player.id in map_to_use.whisper_cooldowns:
            last_movement_time: datetime.datetime = map_to_use.whisper_cooldowns[player.id]
            next_possible_movement_time = last_movement_time + datetime.timedelta(seconds=settings.whisper_cooldown_seconds)
            diff = next_possible_movement_time - datetime.datetime.now()
            if diff.total_seconds() > 0:
                await ctx.respond(f"Whispering in this map is still on cooldown for {diff.total_seconds()} seconds")
                return
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Whispering...", flags=hikari.MessageFlag.LOADING)
    active_channel = await guildChannelEnforcer.ensure_type(get_active_channel_for_player_in_map(guild, player, map_to_use), ctx, "Can't find player's active channel in the map")
    target_active_channel = await textableGuildChannelEnforcer.ensure_type(get_active_channel_for_player_in_map(guild, target, map_to_use), ctx, "Can't find targets's active channel in the map")
    active_location = await stringEnforcer.ensure_type(get_location_channels_location(active_channel), ctx, "Can't find where you are somehow, contact an admin")
    target_active_location = get_location_channels_location(target_active_channel)
    if active_location != target_active_location:
        await ctx.respond(f"You must be in the same location as {target.mention} to whisper to them.")
        return
    await target_active_channel.send(f"{player.mention} ({player.display_name}) whispered to you:\n\n{ctx.options['message']}")
    was_overheard = settings.whisper_percentage > 0 and random.randint(1, 100) <= settings.whisper_percentage
    if was_overheard:
        nullable_category = get_category_of_channel(guild, active_channel.id)  
        if nullable_category is None:
            return
        map_category: hikari.GuildChannel = nullable_category
        chat_channels = get_channels_in_category(guild, map_category)
        for chat_channel in chat_channels:
            if chat_channel == active_channel or chat_channel == target_active_channel or not isinstance(chat_channel, hikari.TextableGuildChannel):
                continue
            chat_text_channel: hikari.TextableGuildChannel = chat_channel
            chat_channel_location = get_location_channels_location(chat_text_channel)
            if chat_channel_location == active_location:
                await chat_channel.send(f"You overheard {player.mention} ({player.display_name}) whisper to {target.mention} ({target.display_name}):\n\n{ctx.options['message']}")
    nullable_spectator_text_channel = find_spectator_channel(guild, map_to_use, active_location)
    if nullable_spectator_text_channel is None:
        return
    spectator_text_channel: hikari.TextableGuildChannel = nullable_spectator_text_channel
    overheard_text = " (and overheard by everyone else)" if was_overheard else ""
    await spectator_text_channel.send(f"{player.mention} ({player.display_name}) whispered{overheard_text} to {target.mention} ({target.display_name}):\n\n{ctx.options['message']}")
    map_to_use.reset_whisper_cooldown(player.id)
    channel = guild.get_channel(ctx.channel_id) 
    if channel is not None:
        await log_action_to_flint(ctx, "whisper", player, channel)
    await ctx.respond(f"You whispered to {target.mention} ({target.display_name}) :\n\n{ctx.options['message']}")
    
@plugin.command
@lightbulb.option("location-name", "The location you want to peek at", type=str)
@lightbulb.command("peek", "Peek in a location to see who's there without moving, with a chance the people there see you peeking")
@lightbulb.implements(commands.SlashCommand)
async def peek(ctx: lightbulb.SlashContext) -> None:
    guild = await get_guild(ctx)
    settings = settings_manager.get_settings(guild.id)
    player = await memberEnforcer.ensure_type(ctx.member, ctx, "Somehow couldn't find the player associated with who performed the command, contact the admins")
    maps_player_is_in = get_maps_player_is_in(guild, player)
    if not maps_player_is_in:
        await ctx.respond("You're not in a map")
        return
    if not settings.peek_enabled:
        await ctx.respond("Peeking is currently disabled")
        return
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        error_message = "Since you are in two maps, we need you to use the command in the map you want check on"
        category = await guildChannelEnforcer.ensure_type(get_category_of_channel(guild, ctx.channel_id), ctx, error_message)
        category_name = await stringEnforcer.ensure_type(category.name, ctx, error_message)
        map_name = await stringEnforcer.ensure_type(get_map_name_from_category(category_name), ctx, error_message)
        if map_name not in map(lambda m: m.name, maps_player_is_in):
            await ctx.respond(error_message)
            return
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    active_channel = await guildChannelEnforcer.ensure_type(
        get_active_channel_for_player_in_map(guild, player, map_to_use), ctx, "Could not find a channel you are active in for your location, if this is an error contact the admins")
    category = await guildChannelEnforcer.ensure_type(
        get_category_of_channel(guild, active_channel.id), ctx, "Could not find category of active channel, contact the admins")
    current_location = await stringEnforcer.ensure_type(get_location_channels_location(active_channel), ctx, "Could not determine location from your active channel, contact the admins")
    target_location = ctx.options['location-name'].lower()
    if current_location == target_location:
        await ctx.respond(f"You don't need to peek at a location you're already in.")
        return
    if target_location not in map_to_use.locations:
        await ctx.respond(f"Invalid location: {target_location}. Not in the map")
        return
    if settings.peek_cooldown_seconds > 0:
        if player.id in map_to_use.peek_cooldowns:
            last_peek_time: datetime.datetime = map_to_use.peek_cooldowns[player.id]
            next_possible_peek_time = last_peek_time + datetime.timedelta(seconds=settings.peek_cooldown_seconds)
            diff = next_possible_peek_time - datetime.datetime.now()
            if diff.total_seconds() > 0:
                await ctx.respond(f"Peeking in this map is still on cooldown for {diff.total_seconds()} seconds")
                return
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Peeking...", flags=hikari.MessageFlag.LOADING)
    was_seen = settings.peek_percentage > 0 and random.randint(1, 100) <= settings.peek_percentage
    if was_seen:
        nullable_category = get_category_of_channel(guild, active_channel.id)  
        if nullable_category is None:
            return
        map_category: hikari.GuildChannel = nullable_category
        chat_channels = get_channels_in_category(guild, map_category)
        for chat_channel in chat_channels:
            if chat_channel == active_channel or not isinstance(chat_channel, hikari.GuildTextChannel):
                continue
            chat_text_channel: hikari.GuildTextChannel = chat_channel
            chat_channel_location = get_location_channels_location(chat_text_channel)
            if chat_channel_location == target_location:
                await chat_channel.send(f"You saw {player.mention} ({player.display_name}) peek in to {target_location}")
    map_to_use.reset_peek_cooldown(player.id)
    channel = guild.get_channel(ctx.channel_id) 
    if channel is not None:
        await log_action_to_flint(ctx, "peek", player, channel)
    map_channels = get_channels_in_category(guild, category)
    location_players = await get_players_in_location(ctx.bot, guild, map_channels, target_location)
    if len(location_players) == 0:
        await ctx.respond(f"No one is in {target_location}")
        return
    if len(location_players) == 1:
        p = location_players[0]
        await ctx.respond(f"{p.mention} ({p.display_name}) is in {target_location}")
        return
    players_string = ', '.join(map(lambda p: f"{p.mention} ({p.display_name})", location_players))
    await ctx.respond(f"{players_string} are in {target_location}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("role", "Role a player must have to visit the location", type=hikari.Role)
@lightbulb.option("location-name", "Name of location to attach the role to", type=str)
@lightbulb.option("map-name", "Name of the map the location will have a role attached to", type=str)
@lightbulb.command("add-role-to-location", "Add a role a player must have to enter a particular location")
@lightbulb.implements(commands.SlashCommand)
async def add_role_to_location(ctx: lightbulb.SlashContext) -> None:
    map_name = ctx.options["map-name"].lower()
    location_name = ctx.options["location-name"].lower()
    role = ctx.options["role"]
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding role to location...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    possible_map = await atlas.add_role(guild.id, map_name, location_name, role.id)
    if possible_map is None:
        await ctx.respond("Could not attach the role to the map and location - do they both exist?")
        return
    await ctx.respond(f"Attached {role.mention} to {location_name} in {map_name}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("location-name", "Name of location to remove required roles from", type=str)
@lightbulb.option("map-name", "Name of the map the location will have no more roles attached to", type=str)
@lightbulb.command("remove-roles-from-location", "Remove all attached roles from a particular location")
@lightbulb.implements(commands.SlashCommand)
async def remove_roles_from_location(ctx: lightbulb.SlashContext) -> None:
    map_name = ctx.options["map-name"].lower()
    location_name = ctx.options["location-name"].lower()
    role = ctx.options["role"]
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding role to location...", flags=hikari.MessageFlag.LOADING)
    guild = await get_guild(ctx)
    possible_map = await atlas.remove_roles(guild.id, map_name, location_name)
    if possible_map is None:
        await ctx.respond("Could not remove the roles to the map and location - do they both exist?")
        return
    await ctx.respond(f"Removed roles from {location_name} in {map_name}")

@plugin.listener(hikari.MessageCreateEvent, bind=True) # type: ignore[misc]
async def mirror_messages(plugin: lightbulb.Plugin, event: hikari.MessageCreateEvent):
    bot = plugin.bot
    bot_user = bot.get_me()
    if event.is_webhook or (bot_user is None or event.author_id == bot_user.id):
        return
    if event.message.guild_id is None:
        return
    if event.message.author.id == 1121647528757178418 and not (event.message.content and event.message.content.startswith("You rolled")): # flint
        return
    nullable_guild = bot.cache.get_available_guild(event.message.guild_id)
    if nullable_guild is None:
        return
    guild: hikari.Guild = nullable_guild
    nullable_channel =  bot.cache.get_guild_channel(event.message.channel_id)
    if nullable_channel is None:
        return
    channel: hikari.GuildChannel = nullable_channel
    nullable_category = get_category_of_channel(guild, channel.id)  
    if nullable_category is None:
        return
    category: hikari.GuildChannel = nullable_category
    nullable_category_name = category.name
    if nullable_category_name is None or "-spectator" in nullable_category_name:
        return
    category_name: str = nullable_category_name
    nullable_map_name = get_map_name_from_category(category_name)
    if nullable_map_name is None:
        return
    map_name: str = nullable_map_name
    nullable_fetched_map = atlas.get_map(guild.id, map_name)
    if nullable_fetched_map is None:
        return
    fetched_map: Map = nullable_fetched_map
    if not fetched_map.talking_enabled:
        return await event.message.respond("Talking here is off right now.")
    nullable_location = get_location_channels_location(channel)
    if nullable_location is None:
        return
    location: str = nullable_location
    chat_channels = get_channels_in_category(guild, category)
    server_settings = settings_manager.get_settings(guild.id)
    for chat_channel in chat_channels:
        if chat_channel == channel or not isinstance(chat_channel, hikari.GuildTextChannel):
            continue
        chat_text_channel: hikari.GuildTextChannel = chat_channel
        chat_channel_location = get_location_channels_location(chat_text_channel)
        if chat_channel_location == location:
            webhooks = await bot.rest.fetch_channel_webhooks(chat_text_channel)
            display_name: hikari.UndefinedOr[str] = event.message.member.display_name if event.message.member is not None else hikari.UNDEFINED
            async_tasks = []
            for webhook in webhooks:
                if not(webhook.name == WEBHOOK_NAME) or not isinstance(webhook, hikari.ExecutableWebhook):
                    continue
                async_tasks.append(asyncio.create_task(execute_mirrored_webhook(plugin.bot, webhook, display_name, event.message, chat_text_channel)))
            await asyncio.gather(*async_tasks)

    location_players = await get_players_in_location(bot, guild, chat_channels, location)
    other_players_in_channel = list(filter(lambda p: event.message.member is None or p.id != event.message.member.id, location_players))
    nullable_spectator_text_channel = find_spectator_channel(guild, fetched_map, location)
    if nullable_spectator_text_channel is None:
        return
    spectator_text_channel: hikari.GuildTextChannel = nullable_spectator_text_channel
    spectator_webhooks = await bot.rest.fetch_channel_webhooks(spectator_text_channel)
    display_name = "{} (to {})".format(
        event.message.member.display_name if event.message.member is not None else "???", 
        ", ".join(map(lambda x: x.display_name, other_players_in_channel)) if other_players_in_channel else "nobody else")
    if len(display_name) >= MAX_DISPLAY_NAME_LENGTH:
        display_name = display_name[:MAX_DISPLAY_NAME_LENGTH - 4] + "...)"
    if (not server_settings.sync_commands_and_bots_to_spectators) and message_is_bot_or_commandlike(event.message):
        return
    for spectator_webhook in spectator_webhooks:
        if not (spectator_webhook.name == WEBHOOK_NAME and isinstance(spectator_webhook, hikari.ExecutableWebhook)):
            continue
        await execute_mirrored_webhook(plugin.bot, spectator_webhook, display_name, event.message, spectator_text_channel)

async def check_for_edited_message_in_channel_and_edit(bot: hikari.GatewayBot, player: hikari.UndefinedNoneOr[hikari.Member], chat_channel: hikari.GuildTextChannel, location: str, old_message: hikari.UndefinedNoneOr[str], new_message: hikari.UndefinedNoneOr[str]) -> None:
    chat_text_channel: hikari.GuildTextChannel = chat_channel
    chat_channel_location = get_location_channels_location(chat_text_channel)
    if chat_channel_location == location:
        webhooks = await bot.rest.fetch_channel_webhooks(chat_text_channel)
        display_name: hikari.UndefinedOr[str] = player.display_name if player is not None and player is not hikari.UNDEFINED else hikari.UNDEFINED
        for webhook in webhooks:
            if not(webhook.name == WEBHOOK_NAME) or not isinstance(webhook, hikari.ExecutableWebhook):
                continue
            found_message = False
            if old_message:
                found_message = await find_message_in_channel(bot, chat_text_channel, old_message)
            if found_message and found_message.content:
                if found_message.content.startswith("*In reply to"):
                    new_content = "\n".join(found_message.content.split("\n")[:2] + ([new_message] if new_message else ["*Message deleted*"]))
                await webhook.edit_message(found_message.id, content=new_message)    

@plugin.listener(hikari.GuildMessageUpdateEvent, bind=True) # type: ignore[misc]
async def mirror_edits(plugin: lightbulb.Plugin, event: hikari.GuildMessageUpdateEvent):
    bot = plugin.bot
    bot_user = bot.get_me()
    if event.is_webhook or (bot_user is None or event.author_id == bot_user.id):
        return
    if not event.author or not event.old_message:
        return 
    if event.message.guild_id is None:
        return
    if event.message.author and event.message.author.id == 1121647528757178418 and not (event.message.content and event.message.content.startswith("You rolled")): # flint
        return
    nullable_guild = bot.cache.get_available_guild(event.message.guild_id)
    if nullable_guild is None:
        return
    guild: hikari.Guild = nullable_guild
    nullable_channel =  bot.cache.get_guild_channel(event.message.channel_id)
    if nullable_channel is None:
        return
    channel: hikari.GuildChannel = nullable_channel
    nullable_category = get_category_of_channel(guild, channel.id)  
    if nullable_category is None:
        return
    category: hikari.GuildChannel = nullable_category
    nullable_category_name = category.name
    if nullable_category_name is None or "-spectator" in nullable_category_name:
        return
    category_name: str = nullable_category_name
    nullable_map_name = get_map_name_from_category(category_name)
    if nullable_map_name is None:
        return
    map_name: str = nullable_map_name
    nullable_fetched_map = atlas.get_map(guild.id, map_name)
    if nullable_fetched_map is None:
        return
    fetched_map: Map = nullable_fetched_map
    if not fetched_map.talking_enabled:
        return await event.message.respond("Talking here is off right now.")
    nullable_location = get_location_channels_location(channel)
    if nullable_location is None:
        return
    location: str = nullable_location
    chat_channels = get_channels_in_category(guild, category)
    server_settings = settings_manager.get_settings(guild.id)
    player = event.message.member
    async_tasks = []
    for chat_channel in chat_channels:
        if chat_channel == channel or not isinstance(chat_channel, hikari.GuildTextChannel):
            continue
        async_tasks.append(asyncio.create_task(check_for_edited_message_in_channel_and_edit(
            plugin.bot, 
            player, 
            chat_channel, 
            location, 
            event.old_message.content, 
            event.content)))
    await asyncio.gather(*async_tasks)
    location_players = await get_players_in_location(bot, guild, chat_channels, location)
    other_players_in_channel = list(filter(lambda p: player is None or player is hikari.UNDEFINED or p.id != player.id, location_players))
    nullable_spectator_text_channel = find_spectator_channel(guild, fetched_map, location)
    if nullable_spectator_text_channel is None:
        return
    spectator_text_channel: hikari.GuildTextChannel = nullable_spectator_text_channel
    spectator_webhooks = await bot.rest.fetch_channel_webhooks(spectator_text_channel)
    display_name = "{} (to {})".format(
        player.display_name if player is not None and player is not hikari.UNDEFINED else "???", 
        ", ".join(map(lambda x: x.display_name, other_players_in_channel)) if other_players_in_channel else "nobody else")
    if len(display_name) >= MAX_DISPLAY_NAME_LENGTH:
        display_name = display_name[:MAX_DISPLAY_NAME_LENGTH - 4] + "...)"
    if (not server_settings.sync_commands_and_bots_to_spectators) and message_is_bot_or_commandlike(event.message):
        return
    for spectator_webhook in spectator_webhooks:
        if not (spectator_webhook.name == WEBHOOK_NAME and isinstance(spectator_webhook, hikari.ExecutableWebhook)):
            continue
        found_message = False
        if event.old_message.content:
            found_message = await find_message_in_channel(plugin.bot, spectator_text_channel, event.old_message.content)
        if found_message and found_message.content:
            new_content = event.content
            if found_message.content.startswith("*In reply to"):
                new_content = "\n".join(found_message.content.split("\n")[:2] + ([new_content] if new_content else ["*Message deleted*"]))
            await spectator_webhook.edit_message(found_message.id, content=new_content)

@plugin.listener(hikari.StartedEvent)
async def setup_states(event: hikari.StartedEvent):
    await atlas.load_from_db()
    await settings_manager.load_from_db()
