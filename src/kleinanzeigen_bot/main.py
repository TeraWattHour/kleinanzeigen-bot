# SPDX-FileCopyrightText: © Sebastian Thomschke and contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-ArtifactOfProjectHomePage: https://github.com/Second-Hand-Friends/kleinanzeigen-bot/
# import textwrap
import asyncio
import sys, time

from kleinanzeigen_bot import publish
import kleinanzeigen_bot.utils.cli as cli
from kleinanzeigen_bot.utils.config import load_config
# from gettext import gettext as _

# import kleinanzeigen_bot
# from kleinanzeigen_bot.utils.exceptions import CaptchaEncountered
# from kleinanzeigen_bot.utils.misc import format_timedelta

# --------------------------------------------------------------------------- #
# Main loop: run bot → if captcha → sleep → restart
# --------------------------------------------------------------------------- #


parser = cli.create_parser()

if __name__ == "__main__":
    args = parser.parse_args()

    config = load_config(args.config)

    match args.command:
        case "publish": asyncio.run(publish.publish_ads(config))

# while True:
#     try:
#         kleinanzeigen_bot.main(sys.argv)  # runs & returns when finished
#         sys.exit(0)  # not using `break` to prevent process closing issues
#     except CaptchaEncountered as ex:
#         delay = ex.restart_delay
#         print(_("[INFO] Captcha detected. Sleeping %s before restart...") % format_timedelta(delay))
#         time.sleep(delay.total_seconds())
#         # loop continues and starts a fresh run

