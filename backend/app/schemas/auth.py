"""Wire contract for operator authentication."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    # No max length on purpose: the hash folds any length to 44 bytes
    # (app/core/passwords.py), so a long passphrase is not punished. The minimum
    # is a floor against obviously empty input, not a password policy.
    password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8)
    new_password: str = Field(min_length=8)


class OperatorOut(BaseModel):
    id: str
    email: str
    full_name: str
    last_login_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    operator: OperatorOut
