import asyncio

from kleinanzeigen_bot import publish
import kleinanzeigen_bot.utils.cli as cli
from kleinanzeigen_bot.utils.config import load_config

parser = cli.create_parser()

if __name__ == "__main__":
    args = parser.parse_args()

    config = load_config(args.config)

    match args.command:
        case "publish": asyncio.run(publish.publish_ads(config))

