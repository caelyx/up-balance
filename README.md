# up-balance

Check the balance of every Up account from the terminal.

The utility reads all pages returned by the
[Up read-only API](https://developer.up.com.au/), prints each account balance,
and prints a grand total. Python 3.10 or newer is supported.

## Installation

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Create an API token at [api.up.com.au](https://api.up.com.au/). Then either
provide it for the current shell:

```sh
export UP_API_KEY='your-token-here'
```

or copy the local configuration template and edit the copy:

```sh
cp config.py.template config.py
```

`config.py` is ignored by Git. The `UP_API_KEY` environment variable takes
precedence when both methods are present. Treat the token as a secret and
revoke it if it is exposed.

## Usage

```sh
./up.py
```

Example output:

```
   90.00 Up Account
  276.24 💰 Savings
--------
  366.24
```

Authentication, connection, malformed-response, and timeout failures are
reported on standard error and produce a nonzero exit status.

## Tests

Install the development requirements, then run the tests and style checks:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check up.py tests
ruff format --check up.py tests
```
