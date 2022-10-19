import hikari
import lightbulb

from lightbulb import commands
from typing import Optional

from utils.atlas import Atlas, Map
from utils.consts import READ_DENIES, READ_PERMISSIONS, WRITE_DENIES, WRITE_PERMISSIONS

plugin = lightbulb.Plugin("MapPlugin")

atlas = Atlas()

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
        type=hikari.channels.PermissionOverwriteType.ROLE,
        deny=(hikari.Permissions.VIEW_CHANNEL)
    )

async def ensure_category_exists(guild: hikari.Guild, channel_name: str) -> hikari.GuildChannel:
    for channel_id, channel in guild.get_channels().items():
        if channel.name == channel_name and (channel.type == hikari.channels.ChannelType.GUILD_CATEGORY):
            return channel
    private_perms = await get_private_perms(guild)
    return await guild.create_category(channel_name, permission_overwrites = [private_perms])

async def get_guild(ctx: lightbulb.SlashContext) -> hikari.Guild:
    nullable_guild = ctx.get_guild()
    if nullable_guild is None:
        await ctx.respond("For some reason the bot could not which server the command came from")
        raise ValueError("For some reason can't get guild for commands")
    guild: hikari.Guild = nullable_guild
    return guild

async def get_map(ctx: lightbulb.SlashContext, guild: hikari.Guild, map_name: str) -> Map:
    nullable_map = atlas.get_map(guild.id, map_name)
    if nullable_map is None:
        await ctx.respond(f"Could not find map under name {map_name}")
        raise ValueError(f"Can't find map name {map_name}")
    fetched_map: Map = nullable_map
    return fetched_map

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
    return player.display_name.split()[0].lower()
    
def get_player_location_name(player:hikari.Member, location: str) -> str:
    return f"{get_sanitized_player_name(player)}-{location.lower()}"

async def ensure_location_channel(guild: hikari.Guild, player: hikari.Member, category: hikari.GuildChannel, map_of_location: Map, location: str, player_in: bool) -> hikari.GuildChannel:
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
    return await guild.create_text_channel(channel_name, permission_overwrites=[private_perms, user_perms], category=category.id)

def get_player_location_channels(guild: hikari.Guild, player: hikari.Member, map_name: str) -> list[hikari.GuildChannel]:
    map_chat_category_ids: list[int] = []
    for channel_id, channel in guild.get_channels().items():
        if channel.name is not None and f"{map_name}-channels-" in channel.name and (channel.type == hikari.channels.ChannelType.GUILD_CATEGORY):
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

def get_active_channel_for_player_in_map(guild: hikari.Guild, player: hikari.Member, map_to_use: Map) -> Optional[hikari.GuildChannel]:
    player_location_channels = get_player_location_channels(guild, player, map_to_use.name)
    for player_location_channel in player_location_channels:
        if player.id in player_location_channel.permission_overwrites and player_location_channel.permission_overwrites[player.id].allow.SEND_MESSAGES:
            return player_location_channel
    return None

def get_player_location_channel_in_map(guild: hikari.Guild, player: hikari.Member, map_to_use: Map, location: str) -> Optional[hikari.GuildChannel]:
    player_location_channels = get_player_location_channels(guild, player, map_to_use.name)
    location_channel_name = get_player_location_name(player, location)
    filtered_player_location_channels = list(filter(lambda m: m.name == location_channel_name, player_location_channels))
    return filtered_player_location_channels[0] if filtered_player_location_channels else None

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

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("locations", "Comma separated list of locations (eg. 'forest, beach'), that people can move to (first is default)", type=str)
@lightbulb.option("map-name", "Name the map will have, will be a prefix for all map-related channels", type=str)
@lightbulb.command("createmap", "Creates a map with the given name, and the locations (comma-separated)")
@lightbulb.implements(commands.SlashCommand)
async def create_map(ctx: lightbulb.SlashContext):
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding map...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    map_name = ctx.options['map-name']
    locations = list(map(lambda location: location.strip(), ctx.options['locations'].split(',')))
    if ' ' in map_name:
        return await ctx.respond("map_name: `{}` cannot have a space in it".format(map_name))
    for location in locations:
        if ' ' in location:
            return await ctx.respond("location name: `{}` cannot have a space in it".format(location))

    created_map = await atlas.create_map(guild.id, map_name, locations)
    async with created_map.cond:
        await ensure_category_exists(guild, f"{map_name}-channels-0")
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_UPDATE, f"Map {map_name} created with locations: `{locations}`")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("player", "Member you want to add to the given map", type=hikari.Member)
@lightbulb.option("map-name", "Name of the map the player will be added to, must already exist", type=str)
@lightbulb.command("addplayer", "Adds the given member to the given map, placing them in the map's default location")
@lightbulb.implements(commands.SlashCommand)
async def add_player(ctx: lightbulb.SlashContext):
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Adding player to map...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    player = ctx.options['player']
    fetched_map = await get_map(ctx, guild, ctx.options['map-name'])
    async with fetched_map.cond:
        category_for_chats = await get_category_for_chats(guild, fetched_map.name, len(fetched_map.locations))
        for i, location in enumerate(fetched_map.locations):
            await ensure_location_channel(guild, player, category_for_chats, fetched_map, location, i == 0)
        await ctx.respond(f"{get_sanitized_player_name(player)} added to {fetched_map.name} at {fetched_map.locations[0]}")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("player", "Member you want to remove from the given map", type=hikari.Member)
@lightbulb.option("map-name", "Name of the map the player will be removed from", type=str)
@lightbulb.command("removeplayer", 'Removes the given member from the given map, deleting "their" channels')
@lightbulb.implements(commands.SlashCommand)
async def remove_player(ctx: lightbulb.SlashContext):
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Removing player from map...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    player = ctx.options['player']
    fetched_map = await get_map(ctx, guild, ctx.options['map-name'])
    async with fetched_map.cond:
        for channel in get_player_location_channels(guild, player, fetched_map.name):
            await channel.delete()
    return await ctx.respond(f"{get_sanitized_player_name(player)} removed from {fetched_map.name}")

@plugin.command
@lightbulb.option("location", "Where you want to go", type=str)
@lightbulb.command("move", "Moves to the given location, based on your current map")
@lightbulb.implements(commands.SlashCommand)
async def move(ctx: lightbulb.SlashContext):
    await ctx.respond(hikari.interactions.ResponseType.DEFERRED_MESSAGE_CREATE, "Removing player from map...", flags=hikari.MessageFlag.EPHEMERAL)
    guild = await get_guild(ctx)
    nullable_player = ctx.member
    if nullable_player is None:
        return await ctx.respond("Must be performed within a server")
    player: hikari.Member = nullable_player
    location = ctx.options['location'].lower()
    maps_player_is_in = get_maps_player_is_in(guild, player)
    if not maps_player_is_in:
        return await ctx.respond("Cannot move when you're not in a map")
    map_to_use = maps_player_is_in[0]
    if len(maps_player_is_in) >= 2:
        nullable_category = get_category_of_channel(guild, ctx.channel_id)
        if nullable_category is None or nullable_category.name is None:
            return await ctx.respond("Since you are in two maps, we need you to use the move command in the map you want to move in")
        category_name: str = nullable_category.name
        map_name = get_map_name_from_category(category_name)
        if map_name is None or map_name not in map(lambda m: m.name, maps_player_is_in):
            return await ctx.respond("Since you are in two maps, we need you to use the move command in the map you want to move in")
        map_to_use = list(filter(lambda m: m.name == map_name, maps_player_is_in))[0]
    async with map_to_use.cond:
        if location not in map_to_use.locations:
            return await ctx.respond(f"{location} is not in the map you are moving in")
        nullable_active_channel = get_active_channel_for_player_in_map(guild, player, map_to_use)
        if nullable_active_channel is None:
            return await ctx.respond("Can't find your active channel for some reason, please contact admins")
        active_channel: hikari.GuildChannel = nullable_active_channel
        nullable_location_channel = get_player_location_channel_in_map(guild, player, map_to_use, location)
        if nullable_location_channel is None:
            return await ctx.respond(f"Cant find the channel for {location} for some reason, please contact admins")
        location_channel: hikari.GuildChannel = nullable_location_channel
        if active_channel == location_channel:
            return await ctx.respond(f"Already in {location}")
        await make_channel_readable_for_player(active_channel, player)
        await make_channel_writeable_for_player(location_channel, player)
        return await ctx.respond(f"You have moved to {location_channel.mention}")

    

@plugin.listener(hikari.StartedEvent)
async def setup_states(event: hikari.StartedEvent):
    await atlas.load_from_db()