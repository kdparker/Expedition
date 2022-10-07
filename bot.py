import hikari
import lightbulb
import os
import sqlite3

from lightbulb import commands


with open('secrets/client', 'r') as client_file:
    token = client_file.read().strip()

bot = lightbulb.BotApp(
    token=token,
    intents=hikari.Intents.ALL, 
    default_enabled_guilds=(),
    logs={
        "version": 1,
        "incremental": True,
        "loggers": {
            "hikari": {"level": "INFO"},
            "lightbulb": {"level": "DEBUG"},
        },
    },
    prefix="=",
)

@bot.listen(lightbulb.CommandErrorEvent)
async def on_error(event: lightbulb.CommandErrorEvent) -> None:
    if isinstance(event.exception, lightbulb.CommandInvocationError):
        raise event.exception

    if isinstance(event.exception, lightbulb.errors.CommandNotFound):
        return

    # Unwrap the exception to get the original cause
    exception = event.exception.__cause__ or event.exception

    raise exception

bot.run()
