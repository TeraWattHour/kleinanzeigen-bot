import json
from kleinanzeigen_bot.model.config_model import Config


def load_config(path: str) -> Config:
    with open(path, 'r') as f:
        data = json.load(f)
        return Config.model_validate(data, strict=True)
        