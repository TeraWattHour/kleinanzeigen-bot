import argparse
import sys

__all__ = ['create_parser']

def create_parser():
    parser = argparse.ArgumentParser(
        prog=f'{sys.executable} {sys.argv[0]}',
        description='Manage and interact with ads via various commands.'
    )
    parser.add_argument(
        '--config',
        default='./config.json',
        help='Path to the config JSON file (DEFAULT: ./config.json)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enables verbose output - only useful when troubleshooting issues'
    )

    subparsers = parser.add_subparsers(dest='command', required=True, help='Available commands')

    # publish
    publish_parser = subparsers.add_parser('publish', help='(re-)publishes ads')
    publish_parser.add_argument(
        '--ads',
        default='due',
        help=(
            "Specifies which ads to (re-)publish (DEFAULT: due)\n"
            "* all: (re-)publish all ads ignoring republication_interval\n"
            "* due: publish new and due ads\n"
            "* new: only publish new ads\n"
            "* changed: only publish modified ads\n"
            "* <id(s)>: e.g. --ads=1,2,3\n"
            "* Combinations: --ads=changed,due"
        )
    )
    publish_parser.add_argument(
        '--force',
        action='store_true',
        help="Alias for '--ads=all'"
    )
    publish_parser.add_argument(
        '--keep-old',
        action='store_true',
        help="Don't delete old ads on republication"
    )

    # verify
    subparsers.add_parser('verify', help='Verifies the configuration files')

    # delete
    subparsers.add_parser('delete', help='Deletes ads')

    # download
    download_parser = subparsers.add_parser('download', help='Downloads one or multiple ads')
    download_parser.add_argument(
        '--ads',
        default='new',
        help=(
            "Specifies which ads to download (DEFAULT: new)\n"
            "* all: download all ads from your profile\n"
            "* new: download ads not yet saved locally\n"
            "* <id(s)>: e.g. --ads=1,2,3"
        )
    )
    download_parser.add_argument(
        '--force',
        action='store_true',
        help="Alias for '--ads=all'"
    )

    # update-content-hash
    subparsers.add_parser(
        'update-content-hash',
        help=(
            "Recalculates each ad’s content_hash based on the current ad_defaults;\n"
            "use this after changing config.yaml/ad_defaults to avoid every ad being marked 'changed' and republished"
        )
    )

    return parser