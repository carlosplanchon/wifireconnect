"""Tests for the CLI. The diagnose / Watchdog / ifpeek boundaries are
mocked; commands run through typer's CliRunner."""

from typer.testing import CliRunner

from wifireconnect import __main__ as mod
from wifireconnect.diagnose import Diagnosis
from wifireconnect.diagnose import Fault

runner = CliRunner()


def _diag(fault):
    return Diagnosis(fault, "wlan0", "some detail", "MyNet")


class TestCheck:
    def _patch(self, monkeypatch, fault):
        monkeypatch.setattr(
            mod, "diagnose", lambda interface, timeout=None: _diag(fault))
        monkeypatch.setattr(
            mod.ifpeek, "get_wifi_interfaces", lambda: ["wlan0"])

    def test_healthy_exits_zero(self, monkeypatch):
        self._patch(monkeypatch, Fault.HEALTHY)
        result = runner.invoke(mod.app, ["check"])
        assert result.exit_code == 0
        assert "healthy" in result.output
        assert "MyNet" in result.output

    def test_unhealthy_exits_one(self, monkeypatch):
        self._patch(monkeypatch, Fault.ZOMBIE)
        assert runner.invoke(mod.app, ["check"]).exit_code == 1

    def test_missing_interface_exits_two(self, monkeypatch):
        self._patch(monkeypatch, Fault.NO_INTERFACE)
        result = runner.invoke(mod.app, ["check", "--interface", "nope0"])
        assert result.exit_code == 2

    def test_no_wifi_interface_at_all_fails(self, monkeypatch):
        monkeypatch.setattr(mod.ifpeek, "get_wifi_interfaces", lambda: [])
        result = runner.invoke(mod.app, ["check"])
        assert result.exit_code != 0


class TestRunCommand:
    def test_builds_and_runs_the_watchdog(self, monkeypatch):
        created = {}

        class FakeWatchdog:
            def __init__(self, **kwargs):
                created.update(kwargs)

            def run(self):
                created["ran"] = True

        monkeypatch.setattr(mod, "Watchdog", FakeWatchdog)
        monkeypatch.setattr(
            mod.ifpeek, "get_wifi_interfaces", lambda: ["wlan0"])
        result = runner.invoke(
            mod.app, ["run", "--dry-run", "--ssid", "MyNet"])
        assert result.exit_code == 0
        assert created["ran"] is True
        assert created["interface"] == "wlan0"
        assert created["ssid"] == "MyNet"
        assert created["dry_run"] is True

    def test_keyboard_interrupt_exits_cleanly(self, monkeypatch):
        class InterruptedWatchdog:
            def __init__(self, **kwargs):
                pass

            def run(self):
                raise KeyboardInterrupt

        monkeypatch.setattr(mod, "Watchdog", InterruptedWatchdog)
        result = runner.invoke(mod.app, ["run", "--interface", "wlan0"])
        assert result.exit_code == 0

    def test_explicit_interface_is_used_verbatim(self, monkeypatch):
        created = {}

        class FakeWatchdog:
            def __init__(self, **kwargs):
                created.update(kwargs)

            def run(self):
                pass

        monkeypatch.setattr(mod, "Watchdog", FakeWatchdog)
        result = runner.invoke(mod.app, ["run", "--interface", "wlan1"])
        assert result.exit_code == 0
        assert created["interface"] == "wlan1"
