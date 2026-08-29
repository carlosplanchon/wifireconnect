"""Tests for the layered diagnosis. The ifpeek and probe boundaries are
mocked, one fault class per test."""

from importlib import import_module

from wifireconnect.diagnose import Fault
from wifireconnect.diagnose import diagnose

# The diagnose() function shadows the module of the same name on the
# package, so reach the module itself for monkeypatching.
mod = import_module("wifireconnect.diagnose")


def _env(monkeypatch, operstate="UP", carrier=True, essid="MyNet",
         ipv4=("192.168.1.15",), ipv6=("fe80::1",), default_iface="wlan0",
         internet=True, gateway="192.168.1.1", gateway_alive=True):
    """ Install a fake network world for diagnose() to look at. """
    monkeypatch.setattr(mod.ifpeek, "interface_operstate", lambda i: operstate)
    monkeypatch.setattr(mod.ifpeek, "interface_has_carrier", lambda i: carrier)
    monkeypatch.setattr(mod.ifpeek, "access_point_essid", lambda i: essid)
    monkeypatch.setattr(
        mod.ifpeek, "interface_ipv4_addresses", lambda i: list(ipv4))
    monkeypatch.setattr(
        mod.ifpeek, "interface_ipv6_addresses", lambda i: list(ipv6))
    monkeypatch.setattr(mod.ifpeek, "default_interface", lambda: default_iface)
    monkeypatch.setattr(mod.ifpeek, "default_gateway_ipv4", lambda: gateway)
    monkeypatch.setattr(
        mod.probe, "internet_is_reachable",
        lambda targets=None, timeout=None: internet)
    monkeypatch.setattr(
        mod.probe, "gateway_is_alive", lambda g, timeout=None: gateway_alive)


class TestDiagnose:
    def test_healthy(self, monkeypatch):
        _env(monkeypatch)
        diagnosis = diagnose("wlan0")
        assert diagnosis.fault is Fault.HEALTHY
        assert diagnosis.essid == "MyNet"

    def test_no_interface(self, monkeypatch):
        _env(monkeypatch, operstate=None)
        assert diagnose("nope0").fault is Fault.NO_INTERFACE

    def test_associating_while_dormant(self, monkeypatch):
        # The in-progress association state: wait, never interfere.
        _env(monkeypatch, operstate="DORMANT")
        assert diagnose("wlan0").fault is Fault.ASSOCIATING

    def test_not_associated(self, monkeypatch):
        _env(monkeypatch, operstate="DOWN", carrier=False, essid=None)
        diagnosis = diagnose("wlan0")
        assert diagnosis.fault is Fault.NOT_ASSOCIATED
        assert "DOWN" in diagnosis.detail

    def test_link_local_only_is_no_address(self, monkeypatch):
        # A lone fe80:: does not make a configured interface.
        _env(monkeypatch, ipv4=(), ipv6=("fe80::1",))
        assert diagnose("wlan0").fault is Fault.NO_ADDRESS

    def test_global_ipv6_counts_as_an_address(self, monkeypatch):
        _env(monkeypatch, ipv4=(), ipv6=("2800::1", "fe80::1"))
        assert diagnose("wlan0").fault is Fault.HEALTHY

    def test_no_route(self, monkeypatch):
        _env(monkeypatch, default_iface="eth0")
        assert diagnose("wlan0").fault is Fault.NO_ROUTE

    def test_zombie_when_gateway_is_dead(self, monkeypatch):
        _env(monkeypatch, internet=False, gateway_alive=False)
        diagnosis = diagnose("wlan0")
        assert diagnosis.fault is Fault.ZOMBIE
        assert diagnosis.gateway == "192.168.1.1"

    def test_upstream_when_gateway_answers(self, monkeypatch):
        _env(monkeypatch, internet=False, gateway_alive=True)
        assert diagnose("wlan0").fault is Fault.UPSTREAM

    def test_upstream_without_an_ipv4_gateway_to_probe(self, monkeypatch):
        _env(monkeypatch, internet=False, gateway=None)
        diagnosis = diagnose("wlan0")
        assert diagnosis.fault is Fault.UPSTREAM
        assert "no IPv4 gateway" in diagnosis.detail

    def test_recoverable_faults(self):
        assert Fault.NOT_ASSOCIATED in mod.RECOVERABLE_FAULTS
        assert Fault.ZOMBIE in mod.RECOVERABLE_FAULTS
        assert Fault.UPSTREAM not in mod.RECOVERABLE_FAULTS
        assert Fault.NO_ADDRESS not in mod.RECOVERABLE_FAULTS
