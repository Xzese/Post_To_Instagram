"""Explicit publishing and read-only recovery commands."""

import argparse
from dataclasses import asdict
import json
import sys
from dotenv import load_dotenv
from . import (
    PublishingError,
    PublishOutcomeUnknown,
    cleanup_operation,
    publish_image,
    reconcile_operation,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish JPEGs with persistent duplicate safeguards."
    )
    parser.add_argument(
        "--env-file", help="Explicit dotenv file; no file is loaded by default."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("image")
    publish.add_argument("--caption", default="")
    publish.add_argument("--operation-key")
    publish.add_argument(
        "--resume",
        action="store_true",
        help="Resume only before an uncertain remote mutation.",
    )
    for name in ["reconcile", "cleanup"]:
        command = commands.add_parser(name)
        command.add_argument("operation_id")
    args = parser.parse_args(argv)
    if args.env_file:
        load_dotenv(args.env_file, override=False)
    try:
        if args.command == "publish":
            result = publish_image(
                args.image,
                args.caption,
                operation_key=args.operation_key,
                resume=args.resume,
            )
        elif args.command == "reconcile":
            result = reconcile_operation(args.operation_id)
        else:
            cleanup_operation(args.operation_id)
            print(
                json.dumps(
                    {"operation_id": args.operation_id, "image_cleanup": "confirmed"}
                )
            )
            return 0
        print(json.dumps(asdict(result)))
        return 0
    except PublishingError as error:
        message = {"error": str(error)}
        for name in ["operation_id", "creation_id", "phase"]:
            value = getattr(error, name, None)
            if value is not None:
                message[name] = value
        print(json.dumps(message), file=sys.stderr)
        return 2 if isinstance(error, PublishOutcomeUnknown) else 1


if __name__ == "__main__":
    raise SystemExit(main())
