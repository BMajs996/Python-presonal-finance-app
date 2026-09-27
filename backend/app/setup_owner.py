"""Configure/reset the one owner using hidden terminal prompts."""

from getpass import getpass
from pathlib import Path

from argon2 import PasswordHasher
from dotenv import set_key

PASSWORDS = PasswordHasher()


def main():
    password = getpass("New owner password (at least 15 characters): ")
    if not 15 <= len(password) <= 1024:
        raise SystemExit("Password must contain 15 to 1024 characters")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    path = Path(".env")
    # Create with restrictive permissions; never print the password or encoded hash.
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    set_key(str(path), "OWNER_PASSWORD_HASH", PASSWORDS.hash(password))
    print("Owner password configured. Restart the app; existing sessions will be invalidated.")


if __name__ == "__main__":
    main()
