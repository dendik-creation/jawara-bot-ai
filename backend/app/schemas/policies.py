"""Wire contract for Security Policies (09_Security/02_Security_Policies.md).

`condition`'s required shape depends on `scope` (a runtime value), so its
structural validation lives in `app.services.policies._validate_policy_condition`
— the service raises `ValueError`, the route maps it to 400 — rather than
here. This schema only checks what's true regardless of `scope`.

The PATCH body's lifecycle-verb field is named `operation`, not `action` —
a policy's own domain field is already called `action` (ALLOW/WARN/BLOCK/
ALERT/ESCALATE), so reusing `action` for the lifecycle verb would collide.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

PolicyScope = Literal["DEFAULT", "CATEGORY_THRESHOLD", "USER_SPECIFIC"]
PolicyAction = Literal["ALLOW", "WARN", "BLOCK", "ALERT", "ESCALATE"]
PolicyStatus = Literal["DRAFT", "ACTIVE", "DISABLED", "ARCHIVED"]
PolicyOperationValue = Literal["UPDATE", "ACTIVATE", "DISABLE", "ARCHIVE"]


class PolicyCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    scope: PolicyScope
    condition: dict[str, Any]
    action: PolicyAction
    priority: int = 100


class PolicyActionRequest(BaseModel):
    operation: PolicyOperationValue
    # Only used by UPDATE; scope is immutable and not accepted here.
    name: str | None = None
    condition: dict[str, Any] | None = None
    action: PolicyAction | None = None
    priority: int | None = None
