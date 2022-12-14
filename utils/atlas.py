from __future__ import annotations

import aiosqlite
import asyncio
import datetime

from typing import Optional

from utils import consts

class Map:
    def __init__(self, name: str, locations: list[str]) -> None:
        self.name = name
        self.locations = locations
        self.cooldowns: dict[int, datetime.datetime] = {}
        self.cond = asyncio.Condition()

    def __str__(self) -> str:
        return str(self.locations)

    def reset_cooldown(self, player_id: int) -> datetime.datetime:
        self.cooldowns[player_id] = datetime.datetime.now()

class ServerAtlas:
    def __init__(self) -> None:
        self._maps: dict[str, Map] = {}

    def add_map(self, map_name: str, locations: list[str]) -> Map:
        added_map = Map(map_name.lower(), locations)
        self._maps[map_name.lower()] = added_map
        return added_map

    def get_map(self, map_name: str) -> Optional[Map]:
        return self._maps.get(map_name.lower(), None)

    def __str__(self) -> str:
        output = []
        for map_name, map in self._maps.items():
            output.append(f"{map_name}: {map}")
        return ", ".join(output)

class Atlas:
    def __init__(self) -> None:
        self._server_atlases: dict[int, ServerAtlas] = {}
    
    def _add_map(self, server_id: int, map_name: str, locations: list[str]) -> Map:
        server_atlas = self._server_atlases.get(server_id, ServerAtlas())
        added_map = server_atlas.add_map(map_name, locations)
        self._server_atlases[server_id] = server_atlas
        return added_map

    def get_map(self, server_id: int, map_name: str) -> Optional[Map]:
        server_atlas = self._server_atlases.get(server_id, None)
        return server_atlas.get_map(map_name) if server_atlas is not None else None

    def get_maps_in_server(self, server_id: int) -> list[Map]:
        server_atlas = self._server_atlases.get(server_id, None)
        return server_atlas._maps.values() if server_atlas is not None else []

    async def add_location(self, server_id: int, map_name: str, location_name: str) -> Optional[Map]:
        server_atlas = self._server_atlases.get(server_id, None)
        if server_atlas is None:
            return None
        fetched_map = server_atlas.get_map(map_name.lower())
        if fetched_map is None:
            return None
        if location_name in fetched_map.locations:
            return None
        fetched_map.locations.append(location_name)
        await self._save_map(server_id, fetched_map)
        return fetched_map

    async def remove_location(self, server_id: int, map_name: str, location_name: str) -> Optional[Map]:
        server_atlas = self._server_atlases.get(server_id, None)
        if server_atlas is None:
            return None
        fetched_map = server_atlas.get_map(map_name.lower())
        if fetched_map is None:
            return None
        if location_name not in fetched_map.locations:
            return None
        fetched_map.locations.remove(location_name.lower())
        await self._save_map(server_id, fetched_map)
        return fetched_map
            
    def __str__(self) -> str:
        output = []
        for server_id, server_atlas in self._server_atlases.items():
            output.append(f"{server_id}: [{server_atlas}]")
        return "\n".join(output)

    async def load_from_db(self) -> Atlas:
        async with aiosqlite.connect(consts.SQLITE_DB) as db:
            SERVER_ID = 0
            MAP_NAME = 1
            LOCATIONS = 2
            async with db.execute("SELECT server_id, map_name, locations FROM locations") as cursor:
                async for row in cursor:
                    server_id = row[SERVER_ID]
                    map_name = row[MAP_NAME]
                    locations = row[LOCATIONS].split(',')
                    self._add_map(server_id, map_name, locations)
        return self

    async def create_map(self, server_id: int, map_name: str, locations: list[str]) -> Map:
        map_name = map_name.lower()
        locations = list(map(lambda location: location.lower(), locations))
        added_map = self._add_map(server_id, map_name, locations)
        await self._save_map(server_id, added_map)
        return added_map

    async def _save_map(self, server_id: int, map_to_save: Map):
        map_name = map_to_save.name.lower()
        locations = map_to_save.locations
        async with map_to_save.cond, aiosqlite.connect(consts.SQLITE_DB) as db:
            await db.execute(f"INSERT OR REPLACE INTO locations (server_id, map_name, locations) VALUES ({server_id}, '{map_name}', '{','.join(locations)}')")
            await db.commit()
