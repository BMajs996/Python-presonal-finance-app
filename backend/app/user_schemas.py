"""Validated contact and credential input for user accounts."""

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

PhoneNumber = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{6,14}$", max_length=16)]


def valid_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Invalid Unicode text") from None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Control characters are not allowed")
    return value


def valid_token(value: SecretStr) -> SecretStr:
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", value.get_secret_value()) is None:
        raise ValueError("Invalid account link")
    return value


AccountToken = Annotated[SecretStr, Field(min_length=43, max_length=43), AfterValidator(valid_token)]


class RegistrationContacts(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    email: EmailStr = Field(max_length=254)
    phone: PhoneNumber

    @field_validator("email", "phone", mode="before")
    @classmethod
    def trim_contacts(cls, value):
        return value.strip() if isinstance(value, str) else value

    @property
    def email_key(self) -> str:
        # Application identity is case-insensitive; no provider-specific dot/plus rewriting.
        return str(self.email).casefold()


class RegistrationRequest(RegistrationContacts):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    display_name: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=15, max_length=1024)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return valid_text(value)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    token: AccountToken
    password: SecretStr = Field(min_length=15, max_length=1024)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    password: SecretStr = Field(min_length=15, max_length=1024)


class ProfileUpdate(RegistrationContacts):
    display_name: str = Field(min_length=1, max_length=100)
    current_password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("display_name")
    @classmethod
    def validate_name(cls, value):
        return RegistrationRequest.validate_name(value)
