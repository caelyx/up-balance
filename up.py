#!/usr/bin/env python3
"""Print the balances of all accounts returned by the Up API."""

import os
import re
import sys
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import TextIO
from urllib.parse import urlsplit

import requests

try:
    from config import APIKEY as CONFIG_API_KEY
except ModuleNotFoundError as exc:
    if exc.name != "config":
        raise
    CONFIG_API_KEY = ""


ACCOUNTS_URL = "https://api.up.com.au/api/v1/accounts"
REQUEST_TIMEOUT = (3.05, 15)
Balance = tuple[str, Decimal]
MONEY_PATTERN = re.compile(r"-?\d+(?:\.\d{1,2})?\Z")


class UpBalanceError(Exception):
    """An expected error that can be presented directly to a CLI user."""


def is_trusted_api_url(url: str) -> bool:
    """Return whether a URL can safely receive the Up bearer token."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "api.up.com.au"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
    )


def load_api_key(config_key: str = CONFIG_API_KEY) -> str:
    """Load the API token, allowing an environment variable to override config.py."""
    api_key = os.environ.get("UP_API_KEY", config_key).strip()
    if not api_key or api_key == "YOUR_APIKEY_HERE":
        raise UpBalanceError(
            "No API token configured. Set UP_API_KEY or copy "
            "config.py.template to config.py and add your token."
        )
    return api_key


def fetch_accounts(api_key: str, session=None) -> list:
    """Fetch every page of accounts from the Up API."""
    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {api_key}"}
    url = ACCOUNTS_URL
    visited_urls = set()
    accounts = []

    while url:
        if url in visited_urls:
            raise UpBalanceError("The API returned a repeating pagination link.")
        if not is_trusted_api_url(url):
            raise UpBalanceError("The API returned an untrusted pagination link.")
        visited_urls.add(url)

        response = None
        try:
            response = http.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.Timeout as exc:
            raise UpBalanceError(
                "The request to Up timed out. Please try again."
            ) from exc
        except requests.HTTPError as exc:
            error_response = exc.response if exc.response is not None else response
            status = getattr(error_response, "status_code", None)
            if status in (401, 403):
                message = (
                    f"API authentication failed (HTTP {status}). Check your token."
                )
            else:
                suffix = f" (HTTP {status})" if status else ""
                message = f"The Up API returned an error{suffix}."
            raise UpBalanceError(message) from exc
        except requests.RequestException as exc:
            raise UpBalanceError(f"Could not connect to the Up API: {exc}") from exc

        try:
            payload = response.json()
        except (ValueError, requests.JSONDecodeError) as exc:
            raise UpBalanceError("The Up API did not return valid JSON.") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise UpBalanceError("The API response is missing a valid 'data' list.")
        accounts.extend(payload["data"])

        links = payload.get("links", {})
        if links is None:
            links = {}
        if not isinstance(links, dict):
            raise UpBalanceError("The API response contains invalid pagination links.")
        url = links.get("next")
        if url is not None and not isinstance(url, str):
            raise UpBalanceError("The API response contains an invalid next-page link.")

    return accounts


def extract_balances(accounts: Iterable[dict]) -> list[Balance]:
    """Extract account display names and exact decimal balances."""
    balances = []
    for account in accounts:
        if not isinstance(account, dict):
            raise UpBalanceError("The API returned an invalid account resource.")
        if account.get("type") != "accounts":
            continue
        try:
            name = account["attributes"]["displayName"]
            raw_value = account["attributes"]["balance"]["value"]
            if not isinstance(raw_value, str) or not MONEY_PATTERN.fullmatch(raw_value):
                raise TypeError
            value = Decimal(raw_value)
            if not isinstance(name, str) or not name:
                raise ValueError
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            account_id = account.get("id", "unknown")
            raise UpBalanceError(
                f"The account {account_id!r} has invalid balance data."
            ) from exc
        balances.append((name, value))
    return balances


def total_balance(balances: Iterable[Balance]) -> Decimal:
    return sum((value for _, value in balances), start=Decimal(0))


def print_report(balances: Iterable[Balance], output: TextIO = sys.stdout) -> None:
    balances = list(balances)
    if not balances:
        print("No accounts found.", file=output)
        return

    for name, value in balances:
        print(f"{value:8.2f} {name}", file=output)
    print("--------", file=output)
    print(f"{total_balance(balances):8.2f}", file=output)


def main(
    api_key: str | None = None,
    output: TextIO = sys.stdout,
    error: TextIO = sys.stderr,
) -> int:
    try:
        token = api_key or load_api_key()
        accounts = fetch_accounts(token)
        balances = extract_balances(accounts)
        print_report(balances, output=output)
    except UpBalanceError as exc:
        print(f"Error: {exc}", file=error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
