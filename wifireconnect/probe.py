#!/usr/bin/env python3

"""
Active reachability probes (plain TCP, standard library only).

Sending traffic is deliberately wifireconnect's job, not ifpeek's: ifpeek
only observes local state, these helpers generate packets to test it.

A completed TCP handshake and a connection refusal (an RST came back) both
prove the peer is reachable; only a timeout or a network error means there
is no evidence of life.
"""

from enum import Enum
from socket import create_connection

DEFAULT_TIMEOUT = 3.0

# Anycast resolvers with a public TCP service: no DNS needed to reach them.
DEFAULT_INTERNET_TARGETS = (("1.1.1.1", 443), ("8.8.8.8", 443))

# TCP ports commonly answered by home gateways (DNS, web admin). A refusal
# from a closed port proves the gateway is alive just as well as an open
# one; only silence on every port counts as dead.
GATEWAY_PROBE_PORTS = (53, 80, 443)


class ProbeResult(Enum):
    """ Outcome of a TCP reachability probe. """
    OK = "ok"                    # handshake completed
    REFUSED = "refused"          # RST came back: the host is alive
    UNREACHABLE = "unreachable"  # timeout or network error


def tcp_probe(
    host: str, port: int, timeout: float = DEFAULT_TIMEOUT
) -> ProbeResult:
    """
    Try a TCP connection to host:port and report what came back.

    :param host: str: Host to probe (IP address or name).
    :param port: int: TCP port to probe.
    :param timeout: float: Seconds to wait for an answer.

    """
    try:
        with create_connection((host, port), timeout=timeout):
            return ProbeResult.OK
    except ConnectionRefusedError:
        return ProbeResult.REFUSED
    except OSError:
        return ProbeResult.UNREACHABLE


def host_is_alive(
    host: str, port: int, timeout: float = DEFAULT_TIMEOUT
) -> bool:
    """
    True if the host answered at all (handshake or refusal).

    :param host: str: Host to probe (IP address or name).
    :param port: int: TCP port to probe.
    :param timeout: float: Seconds to wait for an answer.

    """
    return tcp_probe(host, port, timeout=timeout) is not ProbeResult.UNREACHABLE


def internet_is_reachable(
    targets: tuple = DEFAULT_INTERNET_TARGETS,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """
    True if any of the probe targets answers.

    :param targets: tuple: (host, port) pairs to try, in order.
    :param timeout: float: Seconds to wait for each answer.

    """
    return any(host_is_alive(host, port, timeout=timeout) for host, port in targets)


def gateway_is_alive(gateway: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """
    Probe the default gateway on a few commonly answered ports (53, 80,
    443). With a healthy local stack, a gateway that answers nothing at all
    points at a dead (zombie) association; a gateway that answers while the
    internet does not points upstream.

    Caveat: a gateway that silently drops all of these probes still looks
    dead to this check.

    :param gateway: str: Gateway IP address.
    :param timeout: float: Seconds to wait for each answer.

    """
    return any(
        host_is_alive(gateway, port, timeout=timeout)
        for port in GATEWAY_PROBE_PORTS
    )
