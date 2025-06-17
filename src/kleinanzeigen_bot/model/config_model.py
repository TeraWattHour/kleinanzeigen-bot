# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
from __future__ import annotations
import copy
from typing import Any, List, Literal
from pydantic import Field

from kleinanzeigen_bot.model.ad_model import OPTIONAL, ShippingOption
from kleinanzeigen_bot.utils import dicts
from kleinanzeigen_bot.utils.pydantics import ContextualModel

class AdDefaults(ContextualModel):
    price_type: Literal["FIXED", "NEGOTIABLE", "GIVE_AWAY", "NOT_APPLICABLE"] = "NEGOTIABLE"
    shipping_type: Literal["PICKUP", "SHIPPING", "NOT_APPLICABLE"] = "SHIPPING"
    
    category: str | None = OPTIONAL()
    special_attributes: dict[str, str] | None = OPTIONAL()
    shipping_costs: float | None = OPTIONAL()
    shipping_options: List[ShippingOption] | None = OPTIONAL()
    sell_directly: bool | None = OPTIONAL()
    
class Config(ContextualModel):
    ad_files: List[str] = Field(default=["./**/ad_*.{json,yml,yaml}"], min_items=1) # type: ignore

    ad_defaults: AdDefaults = Field(
        default_factory=AdDefaults,
        description="Default values for ads, can be overwritten in each ad configuration file"
    )

    browser_socket: str = Field(default="127.0.0.1:9222", description="remote debugging socket address to bind to, e.g. '127.0.0.1:9222'")
    username: str

    def with_values(self, values:dict[str, Any]) -> Config:
        return Config.model_validate(dicts.apply_defaults(copy.deepcopy(values), defaults = self.model_dump()))
