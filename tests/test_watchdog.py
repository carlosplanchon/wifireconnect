"""Tests for the watchdog policy: hysteresis, cooldown, dry run, the look
before touching (fresh scan, signal threshold), and how recovery talks to
iwd. The diagnose, iwd, and ifpeek boundaries are mocked."""

import logging

import ifpeek

from wifireconnect import watchdog as mod
from wifireconnect.diagnose import Diagnosis
from wifireconnect.diagnose import Fault
from wifireconnect.watchdog import Sight
from wifireconnect.watchdog import Watchdog


def _diag(fault, essid=None, gateway=None):
    return Diagnosis(fault, "wlan0", "detail", essid, gateway)


def _ap(ssid, bssid="aa:bb:cc:dd:ee:ff", frequency=5180, signal_dbm=-47):
    return ifpeek.AccessPoint(
        ssid, bssid, frequency, signal_dbm, 100, "psk", False)


# What a fresh scan sees by default: every network the tests may target.
_IN_SIGHT = [_ap("SomeNet"), _ap("MyNet", "11:22:33:44:55:66", 2412, -60),
             _ap("Forced", "22:33:44:55:66:77", 2437, -70)]
_READS = ("state", "scan", "known", "link")


class _Iwd:
    """ Records recovery calls; `state` is what station_state reports,
    `in_sight` what a fresh scan returns, `known` what iwd knows. """

    def __init__(self, state="disconnected", in_sight=None, known=None):
        self.state = state
        self.in_sight = list(_IN_SIGHT) if in_sight is None else list(in_sight)
        self.known = ["SomeNet", "MyNet", "Forced"] if known is None else list(known)
        self.calls = []

    def install(self, monkeypatch):
        monkeypatch.setattr(mod.iwd, "station_state", self._station_state)
        monkeypatch.setattr(mod.iwd, "disconnect", self._disconnect)
        monkeypatch.setattr(mod.iwd, "connect", self._connect)
        monkeypatch.setattr(mod.iwd, "known_networks_in_sight", self._known)
        monkeypatch.setattr(mod.ifpeek, "scan_access_points", self._scan)
        # The associated BSS, as _link() reads it (no scan).
        monkeypatch.setattr(mod.ifpeek, "access_point_mac_address", self._mac)
        monkeypatch.setattr(mod.ifpeek, "access_point_frequency", lambda i: 5180)
        monkeypatch.setattr(mod.ifpeek, "access_point_signal_dbm", lambda i: -47)
        return self

    def actions(self):
        """ The mutating calls only (state, scan, known and link are reads). """
        return [call for call in self.calls if call[0] not in _READS]

    def scans(self):
        return [call for call in self.calls if call[0] == "scan"]

    def _station_state(self, interface):
        self.calls.append(("state", interface))
        return self.state

    def _scan(self, interface=None, fresh=False):
        self.calls.append(("scan", interface, fresh))
        return list(self.in_sight)

    def _known(self, interface):
        self.calls.append(("known", interface))
        return list(self.known)

    def _mac(self, interface):
        self.calls.append(("link", interface))
        return "aa:bb:cc:dd:ee:ff" if self.state == "connected" else None

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


class TestStreakSemantics:
    """ The threshold means "N checks in a row blaming the association",
    so non-recoverable failures must not feed or survive in the streak. """

    def test_upstream_failures_do_not_feed_the_streak(self, monkeypatch):
        # Two upstream failures plus one zombie reading must not trigger
        # recovery on a single association-blaming observation.
        backend = _Iwd(state="connected").install(monkeypatch)
        _feed(monkeypatch, [
            _diag(Fault.UPSTREAM), _diag(Fault.UPSTREAM),
            _diag(Fault.ZOMBIE, gateway="192.168.1.1"),
        ])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(3):
            dog.check()
        assert backend.actions() == []

    def test_a_non_recoverable_check_resets_the_streak(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [
            _diag(Fault.NOT_ASSOCIATED), _diag(Fault.NOT_ASSOCIATED),
            _diag(Fault.UPSTREAM),
            _diag(Fault.NOT_ASSOCIATED), _diag(Fault.NOT_ASSOCIATED),
        ])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(5):
            dog.check()
        assert backend.actions() == []  # never 3 recoverable in a row

    def test_mixed_recoverable_faults_share_the_streak(self, monkeypatch):
        # NOT_ASSOCIATED and ZOMBIE both blame the association, so they
        # count towards the same streak.
        backend = _Iwd(state="connected").install(monkeypatch)
        _feed(monkeypatch, [
            _diag(Fault.ZOMBIE, gateway="192.168.1.1"),
            _diag(Fault.NOT_ASSOCIATED),
            _diag(Fault.ZOMBIE, gateway="192.168.1.1"),
        ])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        for _ in range(3):
            dog.check()
        assert ("connect", "wlan0", None) in backend.actions()


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
        # Nothing but the link reads that every failed check logs: no scan,
        # no iwd state, no action.
        assert [call for call in backend.calls if call[0] != "link"] == []
        assert dog._cooldown_until > mod.monotonic()


class TestLookBeforeTouching:
    def _fail_until_recovery(self, monkeypatch, fault=Fault.NOT_ASSOCIATED, **kwargs):
        _feed(monkeypatch, [_diag(fault, gateway="192.168.1.1")] * 3)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3, **kwargs)
        for _ in range(3):
            dog.check()
        return dog

    def test_recovery_starts_with_a_fresh_scan(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        self._fail_until_recovery(monkeypatch)
        assert backend.scans() == [("scan", "wlan0", True)]
        assert ("connect", "wlan0", None) in backend.actions()

    def test_checks_before_recovery_do_not_scan(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)] * 2)
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        dog.check()
        dog.check()
        assert backend.scans() == []

    def test_target_out_of_sight_leaves_the_association_alone(self, monkeypatch, caplog):
        backend = _Iwd(state="connected", in_sight=[_ap("Stranger")]).install(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            dog = self._fail_until_recovery(monkeypatch, Fault.ZOMBIE, ssid="MyNet")
        assert backend.actions() == []  # no kick, no connect
        assert dog._cooldown_until > mod.monotonic()
        assert "MyNet is not in sight of wlan0" in caplog.text

    def test_no_target_needs_a_known_network_in_sight(self, monkeypatch):
        backend = _Iwd(in_sight=[_ap("Stranger")], known=[]).install(monkeypatch)
        self._fail_until_recovery(monkeypatch)
        assert backend.actions() == []
        assert ("known", "wlan0") in backend.calls

    def test_no_target_recovers_when_a_known_network_is_in_sight(self, monkeypatch, caplog):
        backend = _Iwd(in_sight=[_ap("Stranger"), _ap("MyNet", "11:22:33:44:55:66", 2412, -60)],
                       known=["MyNet"]).install(monkeypatch)
        with caplog.at_level(logging.INFO, logger="wifireconnect"):
            self._fail_until_recovery(monkeypatch)
        assert ("connect", "wlan0", None) in backend.actions()
        assert "MyNet in sight of wlan0: bssid 11:22:33:44:55:66, 2412 MHz, -60 dBm" in caplog.text

    def test_scan_failure_recovers_blind(self, monkeypatch, caplog):
        backend = _Iwd().install(monkeypatch)

        def boom(interface=None, fresh=False):
            raise RuntimeError("no daemon")

        monkeypatch.setattr(mod.ifpeek, "scan_access_points", boom)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            self._fail_until_recovery(monkeypatch, ssid="MyNet")
        assert ("connect", "wlan0", "MyNet") in backend.actions()
        assert "fresh scan on wlan0 failed (no daemon)" in caplog.text

    def test_known_networks_failure_recovers_blind(self, monkeypatch, caplog):
        backend = _Iwd().install(monkeypatch)

        def boom(interface):
            raise mod.iwd.IwdError("no station")

        monkeypatch.setattr(mod.iwd, "known_networks_in_sight", boom)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            self._fail_until_recovery(monkeypatch)
        assert ("connect", "wlan0", None) in backend.actions()
        assert "could not list iwd's known networks" in caplog.text

    def test_min_signal_is_off_by_default(self, monkeypatch):
        backend = _Iwd(in_sight=[_ap("MyNet", signal_dbm=-92)]).install(monkeypatch)
        self._fail_until_recovery(monkeypatch, ssid="MyNet")
        assert ("connect", "wlan0", "MyNet") in backend.actions()

    def test_min_signal_leaves_a_weak_target_alone(self, monkeypatch, caplog):
        backend = _Iwd(in_sight=[_ap("MyNet", signal_dbm=-92)]).install(monkeypatch)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            self._fail_until_recovery(monkeypatch, ssid="MyNet", min_signal_dbm=-85)
        assert backend.actions() == []
        assert "MyNet is too weak (-92 dBm < -85 dBm)" in caplog.text

    def test_min_signal_lets_a_strong_enough_target_through(self, monkeypatch):
        backend = _Iwd(in_sight=[_ap("MyNet", signal_dbm=-80)]).install(monkeypatch)
        self._fail_until_recovery(monkeypatch, ssid="MyNet", min_signal_dbm=-85)
        assert ("connect", "wlan0", "MyNet") in backend.actions()

    def test_min_signal_ignores_an_unknown_signal(self, monkeypatch):
        backend = _Iwd(in_sight=[_ap("MyNet", signal_dbm=None)]).install(monkeypatch)
        self._fail_until_recovery(monkeypatch, ssid="MyNet", min_signal_dbm=-85)
        assert ("connect", "wlan0", "MyNet") in backend.actions()

    def test_dry_run_does_not_scan(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        self._fail_until_recovery(monkeypatch, dry_run=True)
        assert backend.scans() == []

    def test_sight_and_describe(self):
        assert Sight(False, None).scanned is False
        assert mod._describe(None) == "no access point"
        assert mod._describe(_ap("X", None, None, None)) == "bssid ?, ? MHz, ? dBm"
        assert mod._describe(_ap("X")) == "bssid aa:bb:cc:dd:ee:ff, 5180 MHz, -47 dBm"


class TestLinkInLogs:
    def test_failed_checks_log_the_associated_bss(self, monkeypatch, caplog):
        _Iwd(state="connected").install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.ZOMBIE, gateway="192.168.1.1")])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            dog.check()
        assert "link: bssid aa:bb:cc:dd:ee:ff, 5180 MHz, -47 dBm" in caplog.text

    def test_not_associated_is_said_so(self, monkeypatch, caplog):
        _Iwd(state="disconnected").install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            dog.check()
        assert "link: not associated" in caplog.text

    def test_link_read_errors_do_not_break_the_check(self, monkeypatch, caplog):
        _Iwd(state="connected").install(monkeypatch)

        def boom(interface):
            raise OSError("nl80211 down")

        monkeypatch.setattr(mod.ifpeek, "access_point_mac_address", boom)
        _feed(monkeypatch, [_diag(Fault.NOT_ASSOCIATED)])
        dog = Watchdog(interface="wlan0", failures_before_recovery=3)
        with caplog.at_level(logging.WARNING, logger="wifireconnect"):
            dog.check()
        assert "link: unknown (nl80211 down)" in caplog.text

    def test_non_recoverable_checks_do_not_read_the_link(self, monkeypatch):
        backend = _Iwd().install(monkeypatch)
        _feed(monkeypatch, [_diag(Fault.UPSTREAM)])
        Watchdog(interface="wlan0").check()
        assert ("link", "wlan0") not in backend.calls


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
