#!/usr/bin/env python3

from typing import Optional
import typer

from wifireconnect.wifireconnect import loop_test_and_reconnect
from wifireconnect.wifireconnect import DEFAULT_TARGET
from wifireconnect.wifireconnect import DEFAULT_SLEEP_BETWEEN
from wifireconnect.wifireconnect import DEFAULT_TEST_COUNT


app = typer.Typer(
    help="Run a connectivity test on a network connection (using ping) every 's' seconds "
    "and try to reconnect if that test fails. (See your networks with 'nmcli conn')"
)


@app.command()
def cli(
    essid: str = typer.Option(
        ...,
        "--essid", "-e",
        help="AP's ESSID."
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password", "-p",
        help="AP's password."
    ),
    target: str = typer.Option(
        DEFAULT_TARGET,
        "--target", "-t",
        help=f"Target webpage for connectivity test."
    ),
    sleep_between: int = typer.Option(
        DEFAULT_SLEEP_BETWEEN,
        "--sleep", "-s",
        help="Time between connectivity tests in seconds."
    ),
    count: int = typer.Option(
        DEFAULT_TEST_COUNT,
        "--count", "-c",
        help="Number of attempts to ping target on the connectivity test."
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output."
    )
):
    """Run continuous connectivity monitoring and auto-reconnection."""
    loop_test_and_reconnect(
        essid=essid,
        password=password,
        sleep_between=sleep_between,
        test_target=target,
        verbose=verbose,
        test_count=count
    )


def main():
    """Entry point for console script."""
    app()


if __name__ == "__main__":
    app()
