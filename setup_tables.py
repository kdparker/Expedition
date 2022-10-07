from types import coroutine
import aiosqlite
import asyncio

from utils import consts

# could probably be using a timefield but schmeep
CREATE_TABLE_QUERY = """
CREATE TABLE IF NOT EXISTS server_settings (
    server_id INT PRIMARY KEY NOT NULL
)
"""

async def create_table():
    async with aiosqlite.connect(consts.SQLITE_DB) as db:
        await db.execute(CREATE_TABLE_QUERY)
        await db.commit()

loop = asyncio.get_event_loop()
coroutine = create_table()
loop.run_until_complete(coroutine)