import io
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

import requests

import up


def account(account_id, name, value, resource_type="accounts"):
    return {
        "type": resource_type,
        "id": account_id,
        "attributes": {
            "displayName": name,
            "balance": {"value": value},
        },
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.responses.pop(0)


class FetchAccountsTests(unittest.TestCase):
    def test_fetches_accounts_with_authentication_and_timeout(self):
        session = FakeSession([FakeResponse({"data": [], "links": {"next": None}})])

        self.assertEqual(up.fetch_accounts("secret", session=session), [])

        url, kwargs = session.calls[0]
        self.assertEqual(url, "https://api.up.com.au/api/v1/accounts")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer secret"})
        self.assertEqual(kwargs["timeout"], (3.05, 15))

    def test_follows_pagination(self):
        next_url = "https://api.up.com.au/api/v1/accounts?page[after]=cursor"
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "data": [account("1", "Everyday", "10.00")],
                        "links": {"next": next_url},
                    }
                ),
                FakeResponse(
                    {
                        "data": [account("2", "Savings", "20.00")],
                        "links": {"next": None},
                    }
                ),
            ]
        )

        result = up.fetch_accounts("secret", session=session)

        self.assertEqual([item["id"] for item in result], ["1", "2"])
        self.assertEqual(
            [call[0] for call in session.calls], [up.ACCOUNTS_URL, next_url]
        )

    def test_turns_http_errors_into_a_clear_domain_error(self):
        session = FakeSession([FakeResponse({}, status_code=401)])

        with self.assertRaisesRegex(up.UpBalanceError, "authentication|401"):
            up.fetch_accounts("secret", session=session)

    def test_turns_timeout_into_a_clear_domain_error(self):
        session = FakeSession(error=requests.Timeout("too slow"))

        with self.assertRaisesRegex(up.UpBalanceError, "timed out"):
            up.fetch_accounts("secret", session=session)

    def test_turns_connection_errors_into_a_clear_domain_error(self):
        session = FakeSession(error=requests.ConnectionError("offline"))

        with self.assertRaisesRegex(up.UpBalanceError, "connect.*Up API"):
            up.fetch_accounts("secret", session=session)

    def test_reports_non_authentication_http_errors(self):
        session = FakeSession([FakeResponse({}, status_code=503)])

        with self.assertRaisesRegex(up.UpBalanceError, "HTTP 503"):
            up.fetch_accounts("secret", session=session)

    def test_handles_http_errors_raised_directly_by_the_session(self):
        error = requests.HTTPError(response=FakeResponse({}, status_code=429))
        session = FakeSession(error=error)

        with self.assertRaisesRegex(up.UpBalanceError, "HTTP 429"):
            up.fetch_accounts("secret", session=session)

    def test_rejects_malformed_json_and_missing_data(self):
        malformed_json = FakeSession([FakeResponse(ValueError("bad JSON"))])
        missing_data = FakeSession([FakeResponse({"links": {"next": None}})])

        with self.assertRaisesRegex(up.UpBalanceError, "valid JSON"):
            up.fetch_accounts("secret", session=malformed_json)
        with self.assertRaisesRegex(up.UpBalanceError, "missing.*data"):
            up.fetch_accounts("secret", session=missing_data)

    def test_rejects_invalid_pagination_links(self):
        invalid_links = FakeSession([FakeResponse({"data": [], "links": []})])

        with self.assertRaisesRegex(up.UpBalanceError, "pagination links"):
            up.fetch_accounts("secret", session=invalid_links)

    def test_rejects_repeating_pagination_links(self):
        session = FakeSession(
            [FakeResponse({"data": [], "links": {"next": up.ACCOUNTS_URL}})]
        )

        with self.assertRaisesRegex(up.UpBalanceError, "repeating pagination"):
            up.fetch_accounts("secret", session=session)

    def test_rejects_pagination_to_an_untrusted_origin(self):
        session = FakeSession(
            [
                FakeResponse(
                    {
                        "data": [],
                        "links": {"next": "https://example.com/steal-token"},
                    }
                )
            ]
        )

        with self.assertRaisesRegex(up.UpBalanceError, "untrusted pagination"):
            up.fetch_accounts("secret", session=session)
        self.assertEqual(len(session.calls), 1)


class BalanceTests(unittest.TestCase):
    def test_preserves_duplicate_display_names(self):
        result = up.extract_balances(
            [
                account("1", "Savings", "10.00"),
                account("2", "Savings", "20.00"),
            ]
        )

        self.assertEqual(
            result,
            [
                ("Savings", Decimal("10.00")),
                ("Savings", Decimal("20.00")),
            ],
        )

    def test_uses_exact_decimal_arithmetic(self):
        balances = up.extract_balances(
            [
                account("1", "A", "0.10"),
                account("2", "B", "0.20"),
                account("3", "C", "0.30"),
            ]
        )

        self.assertEqual(up.total_balance(balances), Decimal("0.60"))

    def test_accepts_values_that_are_whole_numbers_of_cents(self):
        balances = up.extract_balances(
            [
                account("1", "Whole dollars", "10"),
                account("2", "Tenths", "10.1"),
                account("3", "Cents", "10.12"),
                account("4", "Negative", "-0.01"),
            ]
        )

        self.assertEqual(
            [value for _, value in balances],
            [Decimal(10), Decimal("10.1"), Decimal("10.12"), Decimal("-0.01")],
        )

    def test_rejects_invalid_currency_strings_and_json_numbers(self):
        for invalid_value in (
            "0.001",
            "1.2300",
            "1e2",
            "+1.00",
            ".50",
            "1.",
            "NaN",
            "Infinity",
            "-Infinity",
            12.34,
        ):
            with (
                self.subTest(value=invalid_value),
                self.assertRaisesRegex(up.UpBalanceError, "invalid balance"),
            ):
                up.extract_balances([account("bad", "Invalid", invalid_value)])

    def test_rejects_an_invalid_account_shape(self):
        with self.assertRaisesRegex(up.UpBalanceError, "account.*invalid"):
            up.extract_balances([{"type": "accounts", "id": "broken"}])

    def test_ignores_non_account_resources(self):
        self.assertEqual(
            up.extract_balances([account("1", "Other", "1.00", "other")]),
            [],
        )

    def test_rejects_malformed_resource_entries(self):
        for malformed in (None, [], "account"):
            with (
                self.subTest(resource=malformed),
                self.assertRaisesRegex(up.UpBalanceError, "invalid account resource"),
            ):
                up.extract_balances([malformed])


class OutputAndCliTests(unittest.TestCase):
    def test_report_preserves_the_existing_output_format(self):
        output = io.StringIO()

        up.print_report(
            [("Up Account", Decimal("90.00")), ("💰 Savings", Decimal("276.24"))],
            output=output,
        )

        self.assertEqual(
            output.getvalue(),
            "   90.00 Up Account\n  276.24 💰 Savings\n--------\n  366.24\n",
        )

    def test_empty_accounts_are_reported_explicitly(self):
        output = io.StringIO()

        up.print_report([], output=output)

        self.assertEqual(output.getvalue(), "No accounts found.\n")

    def test_cli_reports_failures_to_stderr_and_returns_nonzero(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(
            up, "fetch_accounts", side_effect=up.UpBalanceError("API unavailable")
        ):
            status = up.main(api_key="secret", output=stdout, error=stderr)

        self.assertEqual(status, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "Error: API unavailable\n")

    def test_environment_token_takes_precedence_over_config(self):
        with patch.dict(os.environ, {"UP_API_KEY": "from-environment"}):
            self.assertEqual(
                up.load_api_key(config_key="from-config"), "from-environment"
            )

    def test_missing_token_has_actionable_error(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(up.UpBalanceError, "UP_API_KEY|config.py"),
        ):
            up.load_api_key(config_key="")


if __name__ == "__main__":
    unittest.main()
