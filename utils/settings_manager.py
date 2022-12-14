from __future__ import annotations

import aiosqlite
import asyncio

from dataclasses import dataclass
from typing import Optional

from utils import consts

@dataclass
class ServerSettings:
    server_id: int
    spectator_role_id: Optional[int] = None
    admin_role_id: Optional[int] = None
    should_track_roles: bool = False
    cooldown_minutes: int = 5
    sync_commands_and_bots_to_spectators: bool = True
    
class SettingsManager:
    def __init__(self) -> None:
        self._settings_dict: dict[int, ServerSettings] = {}

    def get_settings(self, server_id: int) -> ServerSettings:
        return self._settings_dict.get(server_id, ServerSettings(server_id))

    async def set_spectator_role_id(self, server_id: int, spectator_role_id: int) -> ServerSettings:
        server_settings = self._settings_dict.get(server_id, ServerSettings(server_id))
        server_settings.spectator_role_id = spectator_role_id
        self._settings_dict[server_id] = server_settings
        await self._update_settings(server_settings)
        return server_settings

    async def set_admin_role_id(self, server_id: int, admin_role_id: int) -> ServerSettings:
        server_settings = self._settings_dict.get(server_id, ServerSettings(server_id))
        server_settings.admin_role_id = admin_role_id
        self._settings_dict[server_id] = server_settings
        await self._update_settings(server_settings)
        return server_settings

    async def set_should_track_roles(self, server_id: int, should_track_roles: bool) -> ServerSettings:
        server_settings = self._settings_dict.get(server_id, ServerSettings(server_id))
        server_settings.should_track_roles = should_track_roles
        self._settings_dict[server_id] = server_settings
        await self._update_settings(server_settings)
        return server_settings

    async def set_cooldown_minutes(self, server_id: int, cooldown_minutes: int) -> ServerSettings:
        server_settings = self._settings_dict.get(server_id, ServerSettings(server_id))
        server_settings.cooldown_minutes = cooldown_minutes
        self._settings_dict[server_id] = server_settings
        await self._update_settings(server_settings)
        return server_settings

    async def set_sync_commands_and_bots_to_spectators(self, server_id: int, sync_commands_and_bots_to_spectators: bool) -> ServerSettings:
        server_settings = self._settings_dict.get(server_id, ServerSettings(server_id))
        server_settings.sync_commands_and_bots_to_spectators = sync_commands_and_bots_to_spectators
        self._settings_dict[server_id] = server_settings
        await self._update_settings(server_settings)
        return server_settings

    async def load_from_db(self) -> SettingsManager:
        async with aiosqlite.connect(consts.SQLITE_DB) as db:
            SERVER_ID = 0
            SPECTATOR_ROLE_ID = 1
            ADMIN_ROLE_ID = 2
            SHOULD_TRACK_ROLES = 3
            COOLDOWN_MINUTES = 4
            SYNC_COMMANDS = 5
            async with db.execute("SELECT server_id, spectator_role_id, admin_role_id, should_track_roles, cooldown_minutes, sync_commands_and_bots_to_spectators FROM server_settings") as cursor:
                async for row in cursor:
                    server_id = row[SERVER_ID]
                    spectator_role_id = row[SPECTATOR_ROLE_ID]
                    admin_role_id = row[ADMIN_ROLE_ID]
                    should_track_roles = True if row[SHOULD_TRACK_ROLES] else False
                    cooldown_minutes = row[COOLDOWN_MINUTES]
                    sync_commands_and_bots_to_spectators = True if row[SYNC_COMMANDS] else False
                    server_settings = ServerSettings(server_id, spectator_role_id, admin_role_id, should_track_roles, cooldown_minutes, sync_commands_and_bots_to_spectators)
                    self._settings_dict[server_id] = server_settings
        return self

    async def _update_settings(self, server_settings: ServerSettings):
        async with aiosqlite.connect(consts.SQLITE_DB) as db:
            server_id = str(server_settings.server_id)
            spectator_role_id = str(server_settings.spectator_role_id) if server_settings.spectator_role_id else "NULL"
            admin_role_id = str(server_settings.admin_role_id) if server_settings.admin_role_id else "NULL"
            should_track_roles = "1" if server_settings.should_track_roles else "0"
            cooldown_minutes = str(server_settings.cooldown_minutes)
            sync_commands_and_bots_to_spectators = "1" if server_settings.sync_commands_and_bots_to_spectators else "0"
            await db.execute(
                f"""INSERT OR REPLACE INTO server_settings (server_id, spectator_role_id, admin_role_id, should_track_roles, cooldown_minutes, sync_commands_and_bots_to_spectators) VALUES 
                ({server_id}, {spectator_role_id}, {admin_role_id}, {should_track_roles}, {cooldown_minutes}, {sync_commands_and_bots_to_spectators})""")
            await db.commit()
