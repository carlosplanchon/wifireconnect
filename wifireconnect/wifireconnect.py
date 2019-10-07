#!/usr/bin/env python3

from time import sleep
from subprocess import run, DEVNULL, PIPE

from pingparsing import PingParsing
from pingparsing import PingTransmitter

from typing import Any, Dict, Optional

DEFAULT_TARGET = "httpbin.com"
DEFAULT_SLEEP_BETWEEN = 10
DEFAULT_TEST_COUNT = 2


def print_verbose(string: str, verbose: bool = True):
    """
    Verbosity print.

    :param string: str: String to print.
    :param verbose: bool: Enable or disable verbosity.
        (Default value = True)

    """
    if verbose:
        print(string)


def test_connection_by_ping(
    page: str = DEFAULT_TARGET,
    count: int = DEFAULT_TEST_COUNT,
        ) -> Dict[Any, Any]:
    """
    Ping the desired host and return the results.
    :param page: str: Page to target on the test.
        (Default value = DEFAULT_TARGET)
    :param count: int: Number of attemps on the test.
        (Default value = DEFAULT_TEST_COUNT)

    """
    ping_parser = PingParsing()
    transmitter = PingTransmitter()
    transmitter.destination = page
    transmitter.count = 2
    result = transmitter.ping()

    return ping_parser.parse(result).as_dict()


def connect_to_wifi(essid: str, password: Optional[str]) -> bool:
    """
    It tries to connect to an AP using nmcli.

    :param essid: str: AP's ESSID.
    :param password: Optional[str]: AP's password.

    """
    if essid and password:
        completed_process = run(
            f'nmcli device wifi connect "{essid}" password "{password}"',
            shell=True,
            stdout=PIPE,
            stderr=DEVNULL
            )
        if completed_process.stdout == b"":
            result = True
        else:
            result = False
    elif essid:
        completed_process = run(
            f'nmcli conn up "{essid}"',
            shell=True,
            stdout=PIPE,
            stderr=DEVNULL
            )
        if b"successfully" in completed_process.stdout:
            result = True
        else:
            result = False
    else:
        result = False
    return result


def loop_test_and_reconnect(
    essid: str,
    password: Optional[str] = None,
    sleep_between: int = DEFAULT_SLEEP_BETWEEN,
    test_target: str = DEFAULT_TARGET,
    verbose: bool = False,
    test_count: int = DEFAULT_TEST_COUNT
        ):
    """
    Run a connectivity test and try to reconnect if test failed.

    :param essid: str: AP's ESSID.
    :param password: Optional[str]: AP's password (Default value = None)
    :param sleep_between: int: Time between connectivity tests.
        (Default value = DEFAULT_SLEEP_BETWEEN)
    :param test_target: str: Page used to do the connectivity test.
        (Default value = DEFAULT_TARGET)
    :param verbose: bool: Verbosity (Default value = False)
    :param test_count: int: Number of attemps on the test.
        (Default value = DEFAULT_TEST_COUNT)

    See your networks with "nmcli conn" (on the shell).
    """
    while True:
        try:
            connection_test_result = test_connection_by_ping(
                page=test_target,
                count=test_count
                )
            connected = True
        except Exception:
            print_verbose(string="·! Connection test failed.", verbose=verbose)
            connected = False

        if connected:
            print_verbose(
                string="· Connection test ran successfully.", verbose=verbose)
        else:
            print_verbose(string="- Trying to connect.", verbose=verbose)
            connected = connect_to_wifi(
                essid=essid,
                password=password
                )
        sleep(sleep_between)
