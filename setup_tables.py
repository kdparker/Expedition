from types import coroutine
import aiosqlite
import asyncio

from utils import consts

# could probably be using a timefield but schmeep
CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS locations (
    server_id INT PRIMARY KEY NOT NULL,
    map_name TEXT NOT NULL,
    locations TEXT NOT NULL
)
"""

async def create_table():
    async with aiosqlite.connect(consts.SQLITE_DB) as db:
        await db.execute(CREATE_TABLE_QUERY)
        await db.commit()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    coroutine = create_table()
    loop.run_until_complete(coroutine)