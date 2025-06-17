from pydantic import Field


def OPTIONAL():
    return Field(default = None)
