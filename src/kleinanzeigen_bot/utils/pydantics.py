# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
from gettext import gettext as _
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails
from typing_extensions import Self

class ContextualValidationError(ValidationError):
    context:Any


class ContextualModel(BaseModel):
    @classmethod
    def model_validate(
        cls,
        obj:Any,
        *,
        strict:bool | None = None,
        from_attributes:bool | None = None,
        context:Any | None = None,
        by_alias:bool | None = None,
        by_name:bool | None = None,
    ) -> Self:
        """
        Proxy to BaseModel.model_validate, but on error re‐raise as
        ContextualValidationError including the passed context.
        """
        try:
            return super().model_validate(
                obj,
                strict = strict,
                from_attributes = from_attributes,
                context = context,
                by_alias = by_alias,
                by_name = by_name,
            )
        except ValidationError as ex:
            new_ex = ContextualValidationError.from_exception_data(
                title = ex.title,
                line_errors = cast(list[InitErrorDetails], ex.errors()),
            )
            new_ex.context = context
            raise new_ex from ex

