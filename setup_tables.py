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

async def create_table():
    async with aiosqlite.connect(consts.SQLITE_DB) as db:
        await db.execute(CREATE_LOCATIONS_QUERY)
        await db.execute(CREATE_SETTINGS_QUERY)
        await db.commit()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    coroutine = create_table()
    loop.run_until_complete(coroutine)