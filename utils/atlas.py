import asyncio

from typing import Optional

class Map:
    def __init__(self, locations: list[str]) -> None:
        self.locations = locations
        self.cond = asyncio.Condition()

    def __str__(self) -> str:
        return str(self.locations)

class ServerAtlas:
    def __init__(self) -> None:
        self._maps: dict[str, Map] = {}

    def add_map(self, map_name: str, locations: list[str]) -> None:
        self._maps[map_name] = Map(locations)

    def get_map(self, map_name: str) -> Optional[Map]:
        return self._maps.get(map_name, None)

    def __str__(self) -> str:
        output = []
        for map_name, map in self._maps.items():
            output.append(f"{map_name}: {map}")
        return ", ".join(output)

class Atlas:
    def __init__(self) -> None:
        self._server_atlases: dict[int, ServerAtlas] = {}
    
    def add_map(self, server_id: int, map_name: str, locations: list[str]):
        server_atlas = self._server_atlases.get(server_id, ServerAtlas())
        server_atlas.add_map(map_name, locations)
        self._server_atlases[server_id] = server_atlas

    def get_map(self, server_id: int, map_name: str) -> Optional[Map]:
        server_atlas = self._server_atlases.get(server_id, None)
        return server_atlas.get_map(map_name) if server_atlas is not None else None

    def __str__(self) -> str:
        output = []
        for server_id, server_atlas in self._server_atlases.items():
            output.append(f"{server_id}: [{server_atlas}]")
        return "\n".join(output)
