"""Create or update a Control Panel operator account.

Usage:

    python -m app.scripts.create_operator --email ops@example.com --name "Nama Operator"
    python -m app.scripts.create_operator --email ops@example.com --name "Nama" --reset-password

The password is read from stdin (prompted, not echoed) or from the
`OPERATOR_PASSWORD` environment variable for non-interactive provisioning. It is
never a command-line argument: argv lands in shell history and in `ps` output on
a shared machine.

There is no self-service sign-up endpoint on purpose — see
`app/api/v1/endpoints/auth.py`. Whoever can run this command already has the
database credentials.
"""

import argparse
import asyncio
import getpass
import logging
import os
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services import auth

logger = logging.getLogger("app.scripts.create_operator")

# Not a password policy, a floor. Real policy belongs with the account
# management screens (Phase 3), which do not exist yet.
MIN_PASSWORD_LENGTH = 8


def read_password(confirm: bool = True) -> str:
    from_env = os.environ.get("OPERATOR_PASSWORD")
    if from_env:
        return from_env

    password = getpass.getpass("Password: ")
    if confirm and password != getpass.getpass("Repeat password: "):
        raise SystemExit("passwords do not match")
    return password


async def run(email: str, name: str, password: str, reset: bool) -> int:
    settings = get_settings()

    if reset:
        if await auth.set_password(email, password, settings):
            logger.info("operator password reset", extra={"email": email})
            return 0
        logger.error("no operator with that email", extra={"email": email})
        return 1

    try:
        operator = await auth.create_operator(email, name, password, settings)
    except ValueError as error:
        # Existing account is a normal outcome of re-running provisioning, not a
        # crash — but it must not silently overwrite the password either.
        logger.error("%s (use --reset-password to change it)", error)
        return 1

    logger.info("operator created", extra={"operator_id": operator.id, "email": operator.email})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a Control Panel operator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="", help="display name; required when creating")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="change an existing account's password instead of creating one",
    )
    args = parser.parse_args()

    configure_logging(get_settings().log_level)

    if not args.reset_password and not args.name.strip():
        raise SystemExit("--name is required when creating an operator")

    password = read_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"password must be at least {MIN_PASSWORD_LENGTH} characters")

    sys.exit(asyncio.run(run(args.email, args.name, password, args.reset_password)))


if __name__ == "__main__":
    main()
