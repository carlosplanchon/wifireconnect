#!/usr/bin/env python3

"""
Layered diagnosis of a Wi-Fi interface's connectivity: ifpeek observations
(carrier, addresses, routes) plus the active probes in wifireconnect.probe.

The classification exists mostly to decide when NOT to act. Resetting a
healthy association because the ISP is down does not fix anything; it just
adds flapping. Only NOT_ASSOCIATED and ZOMBIE are recoverable by touching
the Wi-Fi association.
"""

from enum import Enum
from typing import NamedTuple

import ifpeek

from wifireconnect import probe


class Fault(Enum):
    """ What is wrong with the connection, from L2 upwards. """
    HEALTHY = "healthy"                # internet reachable: do nothing
    NO_INTERFACE = "no-interface"      # the interface does not exist
    ASSOCIATING = "associating"        # association in progress: wait
    NOT_ASSOCIATED = "not-associated"  # no carrier: (re)connect
    NO_ADDRESS = "no-address"          # associated but no usable IP (DHCP)
    NO_ROUTE = "no-route"              # IP but no default route through it
    ZOMBIE = "zombie"                  # stack looks fine, gateway is dead
    UPSTREAM = "upstream"              # gateway alive, internet dead


# The faults where resetting the association can actually help.
RECOVERABLE_FAULTS = frozenset({Fault.NOT_ASSOCIATED, Fault.ZOMBIE})


class Diagnosis(NamedTuple):
    """ The result of one diagnose() pass. """
    fault: Fault
    interface: str
    detail: str
    essid: str | None = None
    gateway: str | None = None


def _usable_addresses(interface: str) -> list[str]:
    """ IPv4 plus global IPv6 addresses (a link-local fe80:: alone does not
    make a configured interface). """
    ipv6 = [
        address
        for address in ifpeek.interface_ipv6_addresses(interface)
        if not address.lower().startswith("fe80")
    ]
    return ifpeek.interface_ipv4_addresses(interface) + ipv6


def diagnose(
    interface: str,
    timeout: float = probe.DEFAULT_TIMEOUT,
    targets: tuple = probe.DEFAULT_INTERNET_TARGETS,
) -> Diagnosis:
    """
    Classify the connectivity of `interface`, from L2 upwards: existence,
    association, address, default route, internet, and (to tell a zombie
    association from an upstream outage) the default gateway.

    :param interface: str: Wi-Fi interface to diagnose.
    :param timeout: float: Seconds to wait for each probe answer.
    :param targets: tuple: (host, port) pairs for the internet probe.

    """
    operstate = ifpeek.interface_operstate(interface)
    if operstate is None:
        return Diagnosis(
            Fault.NO_INTERFACE, interface, "interface not found")
    if operstate == "DORMANT":
        return Diagnosis(
            Fault.ASSOCIATING, interface,
            "association in progress (operstate DORMANT)")

    essid = ifpeek.access_point_essid(interface)
    if ifpeek.interface_has_carrier(interface) is not True:
        return Diagnosis(
            Fault.NOT_ASSOCIATED, interface,
            f"no carrier (operstate {operstate})", essid)

    if not _usable_addresses(interface):
        return Diagnosis(
            Fault.NO_ADDRESS, interface,
            "associated but no usable IP address (DHCP problem?)", essid)

    if ifpeek.default_interface() != interface:
        return Diagnosis(
            Fault.NO_ROUTE, interface,
            "no default route through this interface", essid)

    if probe.internet_is_reachable(targets=targets, timeout=timeout):
        return Diagnosis(
            Fault.HEALTHY, interface, "internet reachable", essid)

    gateway = ifpeek.default_gateway_ipv4()
    if gateway is not None and not probe.gateway_is_alive(
            gateway, timeout=timeout):
        return Diagnosis(
            Fault.ZOMBIE, interface,
            f"internet down and gateway {gateway} does not answer: "
            "dead association", essid, gateway)

    if gateway is not None:
        detail = "internet down but the gateway answers: upstream problem"
    else:
        detail = "internet down, no IPv4 gateway to probe: assuming upstream"
    return Diagnosis(Fault.UPSTREAM, interface, detail, essid, gateway)
