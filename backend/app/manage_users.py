"""Trusted-host administration; generated links are credentials, not log messages."""

import argparse
from urllib.parse import quote

from .core.config import settings
from .database_factory import open_database
from .services.auth_service import initialize_auth
from .services.user_account_service import UserAccountService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("reset", "disable", "enable", "list", "revoke-all"))
    parser.add_argument("target", nargs="?")
    args = parser.parse_args()
    if args.action not in {"list", "revoke-all"} and not args.target:
        parser.error("Specify the existing username")
    database = open_database(settings)
    try:
        initialize_auth(database)
        service = UserAccountService(database)
        if args.action == "reset":
            token = service.issue_code(args.action, args.target)
            print("Share this single-use link through a trusted private channel:")
            print(settings.cors_origin_list[0] + "/reset-password#token=" + quote(token, safe=""))
        elif args.action == "revoke-all":
            service.revoke_all()
            print("All sessions and outstanding account links revoked.")
        elif args.action == "list":
            with database.connection() as connection:
                for row in connection.execute("SELECT id,username,active,is_admin FROM users ORDER BY id"):
                    print(
                        f"{row['id']}\t{row['username'] or '(not configured)'}"
                        f"\tactive={row['active']}\tadmin={row['is_admin']}"
                    )
        else:
            service.set_active(args.target, args.action == "enable")
            print("Account updated; previous sessions and recovery links revoked.")
    finally:
        database.close()


if __name__ == "__main__":
    main()
