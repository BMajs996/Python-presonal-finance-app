from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .domain.money import money_contract

DecimalString = Annotated[str, Field(pattern=r"^-?(0|[1-9][0-9]*)\.[0-9]{2}$")]


class MoneyContract(BaseModel):
    version: Literal["decimal-v1"]
    currency: str
    values: dict[str, DecimalString | list[DecimalString]]


class CentsMoneyResponse(BaseModel):
    money: MoneyContract | None = None

    @model_validator(mode="before")
    @classmethod
    def attach_exact_money(cls, data):
        if isinstance(data, dict) and data.get("currency") is not None:
            values = {
                key.removesuffix("_cents"): value
                for key, value in data.items()
                if key.endswith("_cents") and isinstance(value, int)
            }
            data = {**data, "money": money_contract(data["currency"], **values)}
        return data
