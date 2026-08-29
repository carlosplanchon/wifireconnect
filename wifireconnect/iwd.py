#!/usr/bin/env python3

"""
Minimal iwd client for recovery actions (net.connman.iwd over D-Bus, via
jeepney).

This is the mutating side that deliberately does not live in ifpeek:
``Station.Disconnect()`` and ``Network.Connect()``. iwd owns the credentials
(its known networks), so no password ever goes through here; reconnection
only works for networks iwd already knows.

The caller must be allowed on iwd's D-Bus: root, or a member of the
``wheel`` or ``network`` group (see iwd's D-Bus policy).
"""

from typing import Any, Optional

from jeepney import DBusAddress, MessageType, new_method_call
from jeepney.io.blocking import open_dbus_connection

_IWD = "net.connman.iwd"

# Station.State values while iwd is already working on the association;
# a watchdog must not interfere with these.
BUSY_STATES = frozenset({"connecting", "roaming"})


class IwdError(RuntimeError):
    """ A D-Bus conversation with iwd failed. """


# --- D-Bus plumbing (same shape as ifpeek.scan; duplicated on purpose,
# --- ifpeek must stay read-only) ---------------------------------------------

def _open():  # pragma: no cover - pure I/O boundary, mocked in tests
    """ Open a connection to the system bus. """
    return open_dbus_connection(bus="SYSTEM")


def _call(conn, msg) -> Any:
    """ Send `msg` and return its reply body, raising IwdError on a D-Bus
    error reply (jeepney returns an error *message* rather than raising). """
    reply = conn.send_and_get_reply(msg)
    if reply.header.message_type == MessageType.error:
        detail = reply.body[0] if reply.body else "unknown D-Bus error"
        raise IwdError(f"iwd call failed: {detail}")
    return reply.body


def _prop(props, name: str, default=None) -> Any:
    """ Read a value from a jeepney {name: (signature, value)} property dict. """
    value = props.get(name)
    return value[1] if value is not None else default


def _get_managed_objects(conn) -> dict:
    manager = DBusAddress(
        "/", bus_name=_IWD, interface="org.freedesktop.DBus.ObjectManager"
    )
    return _call(conn, new_method_call(manager, "GetManagedObjects"))[0]


def _get_ordered_networks(conn, station_path: str) -> list:
    """ In-range networks for a station, strongest signal first. """
    station = DBusAddress(
        station_path, bus_name=_IWD, interface=f"{_IWD}.Station")
    return _call(conn, new_method_call(station, "GetOrderedNetworks"))[0]


def _disconnect_station(conn, station_path: str) -> None:
    station = DBusAddress(
        station_path, bus_name=_IWD, interface=f"{_IWD}.Station")
    _call(conn, new_method_call(station, "Disconnect"))


def _connect_network(conn, network_path: str) -> None:
    """ Ask iwd to connect. iwd replies when the attempt settles, so this
    blocks for the duration of the association. """
    network = DBusAddress(
        network_path, bus_name=_IWD, interface=f"{_IWD}.Network")
    _call(conn, new_method_call(network, "Connect"))


# --- object model helpers ----------------------------------------------------

def _find_station_path(objects: dict, interface: str) -> str:
    """ The D-Bus path of the station backing `interface`, or IwdError. """
    for path, interfaces in objects.items():
        if f"{_IWD}.Station" not in interfaces:
            continue
        device = interfaces.get(f"{_IWD}.Device", {})
        if _prop(device, "Name") == interface:
            return path
    raise IwdError(
        f"no iwd station for interface '{interface}' "
        "(is iwd running and managing it?)"
    )


def _select_network(
    objects: dict, ordered: list, ssid: Optional[str]
) -> Optional[str]:
    """ Pick the network to connect to from the in-range `ordered` list:
    the one named `ssid`, or the strongest known network when ssid is None. """
    for network_path, _signal in ordered:
        network = objects.get(network_path, {}).get(f"{_IWD}.Network", {})
        if ssid is not None:
            if _prop(network, "Name") == ssid:
                return network_path
        elif _prop(network, "KnownNetwork") is not None:
            return network_path
    return None


# --- public API --------------------------------------------------------------

def station_state(interface: str) -> str:
    """
    iwd's view of the interface: "connected", "disconnected", "connecting",
    "roaming" or "disconnecting".

    :param interface: str: Wi-Fi interface name.

    """
    conn = _open()
    try:
        objects = _get_managed_objects(conn)
        station_path = _find_station_path(objects, interface)
        station = objects[station_path][f"{_IWD}.Station"]
        return _prop(station, "State", "unknown")
    finally:
        conn.close()


def disconnect(interface: str) -> None:
    """
    Drop the current association on `interface`.

    :param interface: str: Wi-Fi interface name.

    """
    conn = _open()
    try:
        objects = _get_managed_objects(conn)
        _disconnect_station(conn, _find_station_path(objects, interface))
    finally:
        conn.close()


def connect(interface: str, ssid: Optional[str] = None) -> str:
    """
    Connect `interface` to a network iwd knows: the one named `ssid`, or the
    strongest known network in sight when `ssid` is None. Returns the name of
    the network the connection was requested to. Blocks until the attempt
    settles (iwd replies then).

    :param interface: str: Wi-Fi interface name.
    :param ssid: str: Target network name (optional).

    """
    conn = _open()
    try:
        objects = _get_managed_objects(conn)
        station_path = _find_station_path(objects, interface)
        ordered = _get_ordered_networks(conn, station_path)
        network_path = _select_network(objects, ordered, ssid)
        if network_path is None:
            wanted = f"network '{ssid}'" if ssid is not None else "a known network"
            raise IwdError(f"{wanted} is not in sight of '{interface}'")
        _connect_network(conn, network_path)
        network = objects[network_path][f"{_IWD}.Network"]
        return _prop(network, "Name", "?")
    finally:
        conn.close()
