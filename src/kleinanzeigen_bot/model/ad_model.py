# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
from __future__ import annotations

import hashlib, json  # isort: skip
from datetime import datetime  # noqa: TC003 Move import into a type-checking block
from typing import Annotated, Any, Dict, Final, List, Literal, Mapping, Optional, Sequence

from pydantic import AfterValidator, Field, field_validator, model_validator
from typing_extensions import Self

from kleinanzeigen_bot.model import OPTIONAL
from kleinanzeigen_bot.model.config_model import AdDefaults  # noqa: TC001 Move application import into a type-checking block
from kleinanzeigen_bot.utils import dicts
from kleinanzeigen_bot.utils.misc import parse_datetime, parse_decimal
from kleinanzeigen_bot.utils.pydantics import ContextualModel


def _ISO_DATETIME(default:datetime | None = None) -> Any:
    return Field(
        default = default,
        description = "ISO-8601 timestamp with optional timezone (e.g. 2024-12-25T00:00:00 or 2024-12-25T00:00:00Z)",
        json_schema_extra = {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "string",
                    "pattern": (
                        r"^\d{4}-\d{2}-\d{2}T"  # date + 'T'
                        r"\d{2}:\d{2}:\d{2}"  # hh:mm:ss
                        r"(?:\.\d{1,6})?"  # optional .micro
                        r"(?:Z|[+-]\d{2}:\d{2})?$"  # optional Z or ±HH:MM
                    ),
                },
            ],
        },
    )

def _validate_shipping_option_item(v:str) -> str:
    if not v.strip():
        raise ValueError("must be non-empty and non-blank")
    return v

ShippingOption = Annotated[str, AfterValidator(_validate_shipping_option_item)]


class AdPartial(ContextualModel):
    title: str = Field(..., min_length=10)
    description: str = Field(..., max_length=4000)
    images: List[str]
    price: int
    category: str | None = OPTIONAL()
    
    special_attributes: Dict[str, str] | None = OPTIONAL()
    price_type: Literal["FIXED", "NEGOTIABLE", "GIVE_AWAY", "NOT_APPLICABLE"] | None = OPTIONAL()
    shipping_type: Literal["PICKUP", "SHIPPING", "NOT_APPLICABLE"] | None = OPTIONAL()
    shipping_costs: float | None = OPTIONAL()
    shipping_options: List[ShippingOption] | None = OPTIONAL()
    sell_directly: bool | None = OPTIONAL()
    republication_interval: int | None = OPTIONAL()

    id:int | None = OPTIONAL()
    created_on:datetime | None = _ISO_DATETIME()
    updated_on:datetime | None = _ISO_DATETIME()

    @field_validator("created_on", "updated_on", mode = "before")
    @classmethod
    def _parse_dates(cls, v:Any) -> Any:
        return parse_datetime(v)

    @field_validator("shipping_costs", mode = "before")
    @classmethod
    def _parse_shipping_costs(cls, v:float | int | str) -> Any:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return round(parse_decimal(v), 2)

    @model_validator(mode = "before")
    @classmethod
    def _validate_price_and_price_type(cls, values:Dict[str, Any]) -> Dict[str, Any]:
        price_type = values.get("price_type")
        price = values.get("price")
        if price_type == "GIVE_AWAY" and price is not None:
            raise ValueError("price must not be specified when price_type is GIVE_AWAY")
        if price_type == "FIXED" and price is None:
            raise ValueError("price is required when price_type is FIXED")
        return values

    def to_ad(self, ad_defaults: AdDefaults) -> Ad:
        """
        Returns a complete, validated Ad by merging this partial with values from ad_defaults.

        Any field that is `None` or `""` is filled from `ad_defaults` when it's not a list.

        Raises `ValidationError` when, after merging with `ad_defaults`, not all fields required by `Ad` are populated.
        """
        ad_cfg = self.model_dump()
        dicts.apply_defaults(
            target = ad_cfg,
            defaults = ad_defaults.model_dump(),
            ignore = lambda k, _: k == "description",  # ignore legacy global description config
            override = lambda _, v: not isinstance(v, list) and v in {None, ""}  # noqa: PLC1901 can be simplified
        )
        return Ad.model_validate(ad_cfg)
    

# pyright: reportGeneralTypeIssues=false, reportIncompatibleVariableOverride=false
class Ad(AdPartial):
    category: str
    price_type: Literal["FIXED", "NEGOTIABLE", "GIVE_AWAY", "NOT_APPLICABLE"]
    shipping_type: Literal["PICKUP", "SHIPPING", "NOT_APPLICABLE"]
    
    special_attributes: Dict[str, str] | None = OPTIONAL()
    shipping_costs: float | None = OPTIONAL()
    shipping_options: List[ShippingOption] | None = OPTIONAL()
    sell_directly: bool | None = OPTIONAL()
    republication_interval: int | None = OPTIONAL()

    id:int | None = OPTIONAL()
    created_on:datetime | None = _ISO_DATETIME()
    updated_on:datetime | None = _ISO_DATETIME()
    