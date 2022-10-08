import hikari
import lightbulb

from lightbulb import commands

plugin = lightbulb.Plugin("MapPlugin")

@plugin.command
@lightbulb.add_checks(lightbulb.checks.has_guild_permissions(hikari.Permissions.MANAGE_GUILD))
@lightbulb.option("locations", "Comma separated list of locations (eg. 'forest, beach'), that people can move to (first is default)", type=str)
@lightbulb.option("map-name", "Name the map will have, will be a prefix for all map-related channels", type=str)
@lightbulb.command("createmap", "Creates a map with the given name, and the locations (comma-separated)")
@lightbulb.implements(commands.SlashCommand)
async def create_map(ctx: lightbulb.SlashContext):
    map_name = ctx.options['map-name']
    locations = map(lambda location: location.strip(), ctx.options['locations'].split(','))
    if ' ' in map_name:
        return await ctx.respond("map_name: `{}` cannot have a space in it".format(map_name))
    for location in locations:
        if ' ' in location:
            return await ctx.respond("location name: `{}` cannot have a space in it".format(location))
    return await ctx.respond("{}, {}".format(map_name, locations))