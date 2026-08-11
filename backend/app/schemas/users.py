"""Wire contract for end-user block/unblock (08_Dashboard/07_Users_and_Risk.md §3)."""

from typing import Literal

from pydantic import BaseModel, Field

UserActionValue = Literal["BLOCK", "UNBLOCK"]


class UserActionRequest(BaseModel):
    action: UserActionValue
    # Required both ways — "revocable" (unblocking) is itself framed as a
    # security decision in the spec, not a no-op undo.
    reason: str = Field(min_length=1)
