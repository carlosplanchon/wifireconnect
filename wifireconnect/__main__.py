#!/usr/bin/env python3

"""
CLI for wifireconnect: a small Linux network watchdog that diagnoses
connectivity failures and recovers Wi-Fi connections through iwd.
"""

import logging

from typing import Optional

import typer

import ifpeek

from wifireconnect.diagnose import Fault
from wifireconnect.diagnose import diagnose
from wifireconnect.watchdog import DEFAULT_COOLDOWN
from wifireconnect.watchdog import DEFAULT_FAILURES
from wifireconnect.watchdog import DEFAULT_HEARTBEAT
from wifireconnect.watchdog import Watchdog
from wifireconnect import probe

app = typer.Typer(
    help="A small Linux network watchdog: it diagnoses connectivity "
    "failures (carrier, address, route, gateway, upstream) and recovers "
    "Wi-Fi connections through iwd. iwd keeps the credentials; no password "
    "is ever passed here.",
    no_args_is_help=True,
)


def _pick_interface(interface: Optional[str]) -> str:
    """ The given interface, or the first Wi-Fi interface on the system. """
    if interface is not None:
        return interface
    wifi_interfaces = ifpeek.get_wifi_interfaces()
    if not wifi_interfaces:
        raise typer.BadParameter(
            "no Wi-Fi interface found; pass --interface")
    return wifi_interfaces[0]


def _setup_logging(verbose: bool) -> None:
    # Root stays at INFO: pyroute2's DEBUG output dumps raw netlink
    # messages and would bury our own log lines.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if verbose:
        logging.getLogger("wifireconnect").setLevel(logging.DEBUG)


@app.command()
def run(
    interface: Optional[str] = typer.Option(
        None, "--interface", "-i",
        help="Wi-Fi interface to watch (default: the first one found)."),
    ssid: Optional[str] = typer.Option(
        None, "--ssid", "-s",
        help="Known network to reconnect to (default: the last network "
        "seen healthy, else iwd's best known network)."),
    heartbeat: float = typer.Option(
        DEFAULT_HEARTBEAT, "--heartbeat", "-H",
        help="Seconds between health checks when no event arrives."),
    failures: int = typer.Option(
        DEFAULT_FAILURES, "--failures", "-f",
        help="Consecutive failed checks required before recovering."),
    cooldown: float = typer.Option(
        DEFAULT_COOLDOWN, "--cooldown", "-c",
        help="Seconds to hold off after a recovery attempt."),
    timeout: float = typer.Option(
        probe.DEFAULT_TIMEOUT, "--timeout", "-t",
        help="Seconds to wait for each probe answer."),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Diagnose and log, but never touch the association."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable debug output."),
):
    """Run the watchdog: netlink events plus a heartbeat trigger health
    checks, and repeated failures recover the Wi-Fi through iwd."""
    _setup_logging(verbose)
    watchdog = Watchdog(
        interface=_pick_interface(interface),
        ssid=ssid,
        heartbeat=heartbeat,
        failures_before_recovery=failures,
        cooldown=cooldown,
        probe_timeout=timeout,
        dry_run=dry_run,
    )
    try:
        watchdog.run()
    except KeyboardInterrupt:
        logging.getLogger("wifireconnect").info("stopped")


@app.command()
def check(
    interface: Optional[str] = typer.Option(
        None, "--interface", "-i",
        help="Wi-Fi interface to diagnose (default: the first one found)."),
    timeout: float = typer.Option(
        probe.DEFAULT_TIMEOUT, "--timeout", "-t",
        help="Seconds to wait for each probe answer."),
):
    """One-shot diagnosis. Exit code: 0 healthy, 1 unhealthy, 2 no such
    interface."""
    diagnosis = diagnose(_pick_interface(interface), timeout=timeout)
    essid = f" (essid: {diagnosis.essid})" if diagnosis.essid else ""
    typer.echo(
        f"{diagnosis.interface}: {diagnosis.fault.value}: "
        f"{diagnosis.detail}{essid}"
    )
    if diagnosis.fault is Fault.HEALTHY:
        raise typer.Exit(0)
    raise typer.Exit(2 if diagnosis.fault is Fault.NO_INTERFACE else 1)


def main():
    """Entry point for console script."""
    app()


if __name__ == "__main__":
    app()
