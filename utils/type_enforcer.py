from typing_extensions import reveal_type
import lightbulb

from typing import Any, Generic, TypeVar, Optional

T = TypeVar("T")

class TypeEnforcementError(Exception):
    pass

class TypeEnforcer(Generic[T]):
    async def ensure_type(self, nullable_obj: Optional[T], ctx: lightbulb.SlashContext, message: str) -> T:
        if nullable_obj is None:
            await ctx.respond(message)
            raise TypeEnforcementError(message)
        obj: T = nullable_obj
        return obj