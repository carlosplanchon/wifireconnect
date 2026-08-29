"""Tests for the iwd recovery client. The D-Bus boundary is mocked at the
module's seams (same approach as ifpeek's scan tests)."""

import pytest

from jeepney import HeaderFields
from jeepney import MessageType

from wifireconnect import iwd


class _Header:
    def __init__(self, message_type):
        self.message_type = message_type


class _Reply:
    def __init__(self, body, message_type=MessageType.method_return):
        self.body = body
        self.header = _Header(message_type)


class _Conn:
    def __init__(self, replies=None):
        self._replies = list(replies or [])
        self.sent = []
        self.closed = False

    def send_and_get_reply(self, msg):
        self.sent.append(msg)
        return self._replies.pop(0) if self._replies else _Reply(())

    def close(self):
        self.closed = True


_OBJECTS = {
    "/net/connman/iwd/0/3": {
        "net.connman.iwd.Station": {"State": ("s", "connected")},
        "net.connman.iwd.Device": {"Name": ("s", "wlan0")},
    },
    "/net/connman/iwd/0/3/aaaa_psk": {
        "net.connman.iwd.Network": {
            "Name": ("s", "Rupia-5GHz"),
            "KnownNetwork": ("o", "/net/connman/iwd/aaaa_psk"),
        },
    },
    "/net/connman/iwd/0/3/bbbb_psk": {
        "net.connman.iwd.Network": {"Name": ("s", "Stranger")},  # not known
    },
}
# Strongest first: the unknown network outranks the known one on signal.
_ORDERED = [
    ("/net/connman/iwd/0/3/bbbb_psk", -2000),
    ("/net/connman/iwd/0/3/aaaa_psk", -4700),
]


def _patch(monkeypatch, objects=_OBJECTS, ordered=_ORDERED):
    conn = _Conn()
    monkeypatch.setattr(iwd, "_open", lambda: conn)
    monkeypatch.setattr(iwd, "_get_managed_objects", lambda c: objects)
    monkeypatch.setattr(iwd, "_get_ordered_networks", lambda c, p: ordered)
    return conn


class TestStationState:
    def test_state(self, monkeypatch):
        conn = _patch(monkeypatch)
        assert iwd.station_state("wlan0") == "connected"
        assert conn.closed is True

    def test_missing_interface_raises(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(iwd.IwdError, match="wlan9"):
            iwd.station_state("wlan9")


class TestConnect:
    def test_connects_to_the_strongest_known_network(self, monkeypatch):
        _patch(monkeypatch)
        connected = []
        monkeypatch.setattr(
            iwd, "_connect_network", lambda c, p: connected.append(p))
        assert iwd.connect("wlan0") == "Rupia-5GHz"
        # The stronger but unknown network must be skipped.
        assert connected == ["/net/connman/iwd/0/3/aaaa_psk"]

    def test_connects_to_the_named_network(self, monkeypatch):
        _patch(monkeypatch)
        connected = []
        monkeypatch.setattr(
            iwd, "_connect_network", lambda c, p: connected.append(p))
        assert iwd.connect("wlan0", ssid="Stranger") == "Stranger"
        assert connected == ["/net/connman/iwd/0/3/bbbb_psk"]

    def test_named_network_not_in_sight(self, monkeypatch):
        _patch(monkeypatch)
        with pytest.raises(iwd.IwdError, match="Nowhere"):
            iwd.connect("wlan0", ssid="Nowhere")

    def test_no_known_network_in_sight(self, monkeypatch):
        objects = {
            path: interfaces for path, interfaces in _OBJECTS.items()
            if "aaaa" not in path
        }
        ordered = [entry for entry in _ORDERED if "bbbb" in entry[0]]
        _patch(monkeypatch, objects=objects, ordered=ordered)
        with pytest.raises(iwd.IwdError, match="known network"):
            iwd.connect("wlan0")


class TestDisconnect:
    def test_disconnects_the_right_station(self, monkeypatch):
        _patch(monkeypatch)
        dropped = []
        monkeypatch.setattr(
            iwd, "_disconnect_station", lambda c, p: dropped.append(p))
        iwd.disconnect("wlan0")
        assert dropped == ["/net/connman/iwd/0/3"]


class TestPlumbing:
    def test_call_raises_on_dbus_error(self):
        conn = _Conn([_Reply(("boom",), MessageType.error)])
        with pytest.raises(iwd.IwdError, match="boom"):
            iwd._call(conn, None)

    def test_call_returns_the_reply_body(self):
        conn = _Conn([_Reply(("ok",))])
        assert iwd._call(conn, None) == ("ok",)

    def test_thin_senders_build_the_right_calls(self):
        conn = _Conn([_Reply(({},)), _Reply(([],)), _Reply(()), _Reply(())])
        iwd._get_managed_objects(conn)
        iwd._get_ordered_networks(conn, "/station")
        iwd._disconnect_station(conn, "/station")
        iwd._connect_network(conn, "/network")
        members = [
            msg.header.fields[HeaderFields.member] for msg in conn.sent]
        assert members == [
            "GetManagedObjects", "GetOrderedNetworks",
            "Disconnect", "Connect",
        ]
        paths = [msg.header.fields[HeaderFields.path] for msg in conn.sent]
        assert paths == ["/", "/station", "/station", "/network"]

    def test_prop(self):
        assert iwd._prop({"Name": ("s", "x")}, "Name") == "x"
        assert iwd._prop({}, "Name", "default") == "default"
