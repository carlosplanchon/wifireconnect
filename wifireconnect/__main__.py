#!/usr/bin/env python3

from wifireconnect.wifireconnect import loop_test_and_reconnect
from wifireconnect.wifireconnect import DEFAULT_TARGET
from wifireconnect.wifireconnect import DEFAULT_SLEEP_BETWEEN
from wifireconnect.wifireconnect import DEFAULT_TEST_COUNT

from argparse import ArgumentParser


def main():
    parser = ArgumentParser(
        description="Run a connectivity test on a network connection"
        "(using ping) every a 's' time and try to reconnect if that test fail.\n"
        "(See your networks with 'nmcli conn')"
        )
    # Argparse logic.
    parser.add_argument(
            "-v", "--verbose",
            help="Verbosity.",
            action="store_true",
            dest="verbose",
            default=False
        )
    parser.add_argument(
            "-t", "--target",
            type=str,
            help=f"Target webpage. Default {DEFAULT_TARGET}.",
            dest="target",
            default=DEFAULT_TARGET
        )
    parser.add_argument(
            "-s", "--sleep",
            type=int,
            help="Time between connectivity tests."
            f" Default: {DEFAULT_SLEEP_BETWEEN}",
            dest="sleep_between",
            default=DEFAULT_SLEEP_BETWEEN
        )
    parser.add_argument(
            "-c", "--count",
            type=int,
            help="Num of attemps to ping target on the connectivity test."
            f" Default: {DEFAULT_TEST_COUNT}",
            dest="count",
            default=DEFAULT_TEST_COUNT
        )
    parser.add_argument(
            "-e", "--essid",
            type=str,
            help="AP's ESSID.",
            dest="essid",
        )
    parser.add_argument(
            "-p", "--password",
            type=str,
            help="AP's password.",
            dest="password",
            default=None
        )
    args = parser.parse_args()

    loop_test_and_reconnect(
        essid=args.essid,
        password=args.password,
        sleep_between=args.sleep_between,
        test_target=args.target,
        verbose=args.verbose,
        test_count=args.count
            )
