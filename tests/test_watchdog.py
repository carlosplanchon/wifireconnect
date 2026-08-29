"""Tests for the watchdog policy: hysteresis, cooldown, dry run, and how
recovery talks to iwd. The diagnose, iwd, and ifpeek.watch boundaries are
mocked."""

from wifireconnect import watchdog as mod
from wifireconnect.diagnose import Diagnosis
from wifireconnect.diagnose import Fault
from wifireconnect.watchdog import Watchdog


def _diag(fault, essid=None, gateway=None):
    return Diagnosis(fault, "wlan0", "detail", essid, gateway)


class _Iwd:
    """ Records recovery calls; `state` is what station_state reports. """

    def __init__(self, state="disconnected"):
        self.state = state
        self.calls = []

    def install(self, monkeypatch):
        monkeypatch.setattr(mod.iwd, "station_state", self._station_state)
        monkeypatch.setattr(mod.iwd, "disconnect", self._disconnect)
        monkeypatch.setattr(mod.iwd, "connect", self._connect)
        return self

    def actions(self):
        """ The mutating calls only (station_state is just a read). """
        return [call for call in self.calls if call[0] != "state"]

    def _station_state(self, interface):
        self.calls.append(("state", interface))
        return self.state

    def _disconnect(self, interface):
        self.calls.append(("disconnect", interface))

    def _connect(self, interface, ssid=None):
        self.calls.append(("connect", interface, ssid))
        return ssid or "SomeNet"


def _feed(monkeypatch, diagnoses):
    supply = iter(diagnoses)
    monkeypatch.setattr(
        mod, "diagnose",
        lambda interface, timeout=None, targets=None: next(supply))


class TestHysteresis:
    def test_recovers_only_after_n_consecutive_failures(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)] * 3)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        dog.check()
        dog.check()
        assert backend.actions() == []  # not yet
        dog.check()
        assert ("connect", "wlan0", None) in backend.actions()

    def test_a_healthy_check_resets_the_counter(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [
            _diag(Fault.NOT_ASSOCIATED), _diag(Fault.NOT_ASSOCIATED),
            _diag(Fault.HEALTHY, essid="MyNet"),
            _diag(Fault.NOT_ASSOCIATED), _diag(Fault.NOT_ASSOCIATED),
        ])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(5):
            dog.check()
        assert backend.actions() == []  # never 3 in a row

    def test_recovery_targets_the_last_ssid_seen_healthy(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.HEALTHY, essid="MyNet")]
              + [_diag(Fault.NOT_ASSOCIATED)] * 3)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(4):
            dog.check()
        assert ("connect", "wlan0", "MyNet") in backend.actions()

    def test_an_explicit_ssid_wins(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.HEALTHY, essid="MyNet")]
              + [_diag(Fault.NOT_ASSOCIATED)] * 3)
        dog = Watchdog(
            interface="wlan0", ssid="Forced", failures_before_recovery=3)
        for _ in range(4):
            dog.check()
        assert ("connect", "wlan0", "Forced") in backend.actions()


class TestNonRecoverableFaults:
    def test_upstream_never_triggers_recovery(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.UPSTREAM)] * 10)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(10):
            dog.check()
        assert backend.actions() == []

    def test_no_address_is_observed_only(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.NO_ADDRESS)] * 5)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(5):
            dog.check()
        assert backend.actions() == []


class TestRecoveryBehavior:
    def _fail_until_recovery(self, monkeypatch, backend, fault):
        _feed(monkeypatch, [_diag(fault, gateway="192.168.1.1")] * 3)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(3):
            dog.check()
        return dog

    def test_zombie_kicks_then_reconnects(self, monkeypatch):
        backend = _Iwd(state="connected").install(monkeypatch)
        self._fail_until_recovery(monkeypatch, backend, Fault.ZOMBIE)
        actions = backend.actions()
        assert actions.index(("disconnect", "wlan0")) \
            < actions.index(("connect", "wlan0", None))

    def test_not_associated_skips_the_kick(self, monkeypatch):
        backend = _Iwd(state="disconnected").install(monkeypatch)
        self._fail_until_recovery(monkeypatch, backend, Fault.NOT_ASSOCIATED)
        assert ("disconnect", "wlan0") not in backend.actions()
        assert ("connect", "wlan0", None) in backend.actions()

    def test_iwd_already_working_is_left_alone(self, monkeypatch):
        backend = _Iwd(state="connecting").install(monkeypatch)
        self._fail_until_recovery(monkeypatch, backend, Fault.NOT_ASSOCIATED)
        assert backend.actions() == []

    def test_recovery_errors_are_swallowed(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)

        def boom(interface, ssid=None):
            raise mod.iwd.IwdError("no station")

        monkeypatch.setattr(mod.iwd, "connect", boom)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)] * 3)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(3):
            dog.check()  # must not raise

    def test_dry_run_touches_nothing_but_still_cools_down(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)] * 3)
        dog = Watchdog(
            interface="wlan0", failures_before_recovery=3, dry_run=True)
        for _ in range(3):
            dog.check()
        assert backend.calls == []
        assert dog._cooldown_until > mod.monotonic()


class TestCooldown:
    def test_checks_are_suppressed_during_cooldown(self, monkeypatch):
        _Iwd().install(monkeypatch)
        count = {"checks": 0}

        def counting_diagnose(interface, timeout=None, targets=None):
            count["checks"] += 1
            return _diag(Fault.NOT_ASSOCIATED)

        monkeypatch.setattr(mod, "diagnose", counting_diagnose)
        dog = Watchdog(
            interface="wlan0", failures_before_recovery=1, cooldown=60.0)
        dog.check()  # one failure -> recovery -> cooldown starts
        assert count["checks"] == 1
        assert dog.check() is None  # suppressed: the event storm is swallowed
        assert count["checks"] == 1


class TestRun:
    def test_run_checks_on_start_then_per_event_and_tick(self, monkeypatch):
        monkeypatch.setattr(
            mod.ifpeek, "watch",
            lambda interface=None, timeout=None: iter([None, object()]))
        checks = []
        monkeypatch.setattr(
            Watchdog, "check", lambda self: checks.append(1))
        Watchdog(interface="wlan0").run()
        assert len(checks) == 3  # initial + idle tick + event
