# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
import copy, json, os  # isort: skip
from collections import defaultdict
from collections.abc import Callable
from gettext import gettext as _
from importlib.resources import read_text as get_resource_as_string
from pathlib import Path
from types import ModuleType
from typing import Any, Final, TypeVar

from ruamel.yaml import YAML

# https://mypy.readthedocs.io/en/stable/generics.html#generic-functions
K = TypeVar("K")
V = TypeVar("V")


def apply_defaults(
    target:dict[Any, Any],
    defaults:dict[Any, Any],
    ignore:Callable[[Any, Any], bool] = lambda _k, _v: False,
    override:Callable[[Any, Any], bool] = lambda _k, _v: False
) -> dict[Any, Any]:
    """
    >>> apply_defaults({}, {'a': 'b'})
    {'a': 'b'}
    >>> apply_defaults({'a': 'b'}, {'a': 'c'})
    {'a': 'b'}
    >>> apply_defaults({'a': ''}, {'a': 'b'})
    {'a': ''}
    >>> apply_defaults({}, {'a': 'b'}, ignore = lambda k, _: k == 'a')
    {}
    >>> apply_defaults({'a': ''}, {'a': 'b'}, override = lambda _, v: v == '')
    {'a': 'b'}
    >>> apply_defaults({'a': None}, {'a': 'b'}, override = lambda _, v: v == '')
    {'a': None}
    >>> apply_defaults({'a': {'x': 1}}, {'a': {'x': 0, 'y': 2}})
    {'a': {'x': 1, 'y': 2}}
    >>> apply_defaults({'a': {'b': False}}, {'a': { 'b': True}})
    {'a': {'b': False}}
    """
    for key, default_value in defaults.items():
        if key in target:
            if isinstance(target[key], dict) and isinstance(default_value, dict):
                apply_defaults(
                    target = target[key],
                    defaults = default_value,
                    ignore = ignore,
                    override = override
                )
            elif override(key, target[key]):  # force overwrite if override says so
                target[key] = copy.deepcopy(default_value)
        elif not ignore(key, default_value):  # only set if not explicitly ignored
            target[key] = copy.deepcopy(default_value)
    return target


