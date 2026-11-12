"""API keys live in the OS keychain (Windows Credential Manager, macOS Keychain, Secret Service on Linux) via
`keyring`. They're never written to config files, logs or the database."""

import keyring

SERVICE = "flowtype"


def get_key(provider: str) -> str | None:
    return keyring.get_password(SERVICE, f"{provider}_api_key")


def set_key(provider: str, value: str) -> None:
    keyring.set_password(SERVICE, f"{provider}_api_key", value.strip())


def delete_key(provider: str) -> None:
    try:
        keyring.delete_password(SERVICE, f"{provider}_api_key")
    except keyring.errors.PasswordDeleteError:
        pass


def require_key(provider: str) -> str:
    key = get_key(provider)
    if not key:
        raise SystemExit(f"No {provider} API key in the keychain. Run:  python -m flowtype set-key {provider}")
    return key
