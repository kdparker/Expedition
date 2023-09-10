from types import coroutine
import aiosqlite
import asyncio

from utils import consts

# could probably be using a timefield but schmeep
CREATE_LOCATIONS_QUERY = """
CREATE TABLE IF NOT EXISTS locations (
    server_id INT NOT NULL,
    map_name TEXT NOT NULL,
    locations TEXT NOT NULL,
    PRIMARY KEY (server_id, map_name)
);
"""

CREATE_SETTINGS_QUERY = """
CREATE TABLE IF NOT EXISTS server_settings(
    server_id INT NOT NULL,
    spectator_role_id INT,
    admin_role_id INT,
    should_track_roles INT,
    PRIMARY KEY (server_id)
);
"""

ADD_COOLDOWN_SETTINGS_QUERY = """
ALTER TABLE server_settings ADD COLUMN cooldown_minutes INT DEFAULT 5;
"""

ADD_MIRROR_BOTS_AND_COMMANDS_TO_SPECS_SETTING_QUERY = """
ALTER TABLE server_settings ADD COLUMN sync_commands_and_bots_to_spectators INT DEFAULT 1;
"""

CREATE_ROLE_REQUIREMENTS_QUERY = """
CREATE TABLE IF NOT EXISTS role_requirements(
    server_id INT NOT NULL,
    map TEXT NOT NULL,
    location TEXT NOT NULL,
    role_id INT NOT NULL,
    PRIMARY KEY (server_id, map, location, role_id)
);
"""

ADD_TALKING_ENABLED_LOCATION_SETTING = """
ALTER TABLE locations ADD COLUMN talking_enabled INT NOT NULL DEFAULT 1;
"""

ADD_YELL_ENABLED_SERVER_SETTING = """
ALTER TABLE server_settings ADD COLUMN yell_enabled INT NOT NULL DEFAULT 1;
"""

ADD_YELL_COOLDOWN_SECONDS_SERVER_SETTING = """
ALTER TABLE server_settings ADD COLUMN yell_cooldown_seconds INT NOT NULL DEFAULT 0;
"""

ADD_WHISPER_ENABLED_SERVER_SETTING = """
ALTER TABLE server_settings ADD COLUMN whisper_enabled INT NOT NULL DEFAULT 1;
"""

ADD_WHISPER_PERCENTAGE_SERVER_SETTING = """
ALTER TABLE server_settings ADD COLUMN whisper_percentage INT NOT NULL DEFAULT 10;
"""

async def create_table():
    async with aiosqlite.connect(consts.SQLITE_DB) as db:
        await db.execute(CREATE_LOCATIONS_QUERY)
        await db.execute(CREATE_SETTINGS_QUERY)
        await db.execute(CREATE_ROLE_REQUIREMENTS_QUERY)
        try:
            await db.execute(ADD_COOLDOWN_SETTINGS_QUERY)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_MIRROR_BOTS_AND_COMMANDS_TO_SPECS_SETTING_QUERY)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_TALKING_ENABLED_LOCATION_SETTING)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_YELL_ENABLED_SERVER_SETTING)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_YELL_COOLDOWN_SECONDS_SERVER_SETTING)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_WHISPER_ENABLED_SERVER_SETTING)
        except Exception as e:
            print(e)
        try:
            await db.execute(ADD_WHISPER_PERCENTAGE_SERVER_SETTING)
        except Exception as e:
            print(e)
        await db.commit()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    coroutine = create_table()
    loop.run_until_complete(coroutine)