#!/usr/bin/env python3

"""
The watchdog loop: observe with ifpeek, classify with diagnose, recover
through iwd.

Design rules:

- Hybrid trigger: netlink events (via ``ifpeek.watch``) fire an immediate
  check, and a heartbeat covers the failures that produce no local event
  (upstream outage, zombie association).
- Hysteresis: N consecutive checks blaming the association (a recoverable
  fault) are required before acting. A healthy or non-recoverable check
  breaks the streak, so upstream outages never accumulate credit towards
  a kick.
- Cooldown: after acting, checks are suppressed for a while. This also
  swallows the netlink event storm the recovery itself produces.
- Never fight iwd: if the station is "connecting" or "roaming", iwd is
  already on it. ASSOCIATING and UPSTREAM faults never trigger recovery,
  and neither do NO_ADDRESS or NO_ROUTE (those belong to the DHCP client
  or the routing setup, and resetting the association does not own them).
- The target network is remembered while healthy (last known good SSID),
  because once the link is down ifpeek cannot tell you what it was.
- Look before touching: recovery starts with a fresh scan (ifpeek asks iwd
  to scan). If the target is not in sight, nothing is done; a zombie
  association is still an association, and dropping it to reconnect to a
  network that is gone leaves you with nothing. Optionally, a target that is
  in sight but too weak is left alone too (``min_signal_dbm``).
- Say what the radio sees: recoverable failures log the associated BSS
  (BSSID, frequency, dBm; cheap nl80211 reads, no scan) and recovery logs
  the target's strongest BSS, so a log tells a channel change or a weak
  link from a stuck association.
"""

import logging

from dataclasses import dataclass, field
from time import monotonic
from typing import NamedTuple, Optional

import ifpeek

from wifireconnect import iwd
from wifireconnect import probe
from wifireconnect.diagnose import RECOVERABLE_FAULTS
from wifireconnect.diagnose import Diagnosis
from wifireconnect.diagnose import Fault
from wifireconnect.diagnose import diagnose

log = logging.getLogger("wifireconnect")

DEFAULT_HEARTBEAT = 30.0
DEFAULT_FAILURES = 3
DEFAULT_COOLDOWN = 60.0


class Sight(NamedTuple):
    """ What a fresh scan said about the recovery target. """
    scanned: bool                              # False: no scan, nothing is known
    access_point: Optional[ifpeek.AccessPoint]  # the target's strongest BSS, or None


def _describe(access_point: Optional[ifpeek.AccessPoint]) -> str:
    """ 'bssid aa:bb:cc:dd:ee:ff, 5180 MHz, -47 dBm' with '?' for unknowns. """
    if access_point is None:
        return "no access point"
    frequency = (
        f"{access_point.frequency} MHz" if access_point.frequency is not None else "? MHz")
    signal = (
        f"{access_point.signal_dbm} dBm" if access_point.signal_dbm is not None else "? dBm")
    return f"bssid {access_point.bssid or '?'}, {frequency}, {signal}"


@dataclass
class Watchdog:
    """ A connectivity watchdog for one Wi-Fi interface. """

    interface: str
    ssid: Optional[str] = None      # explicit target; None = last seen / iwd's pick
    heartbeat: float = DEFAULT_HEARTBEAT
    failures_before_recovery: int = DEFAULT_FAILURES
    cooldown: float = DEFAULT_COOLDOWN
    probe_timeout: float = probe.DEFAULT_TIMEOUT
    targets: tuple = probe.DEFAULT_INTERNET_TARGETS
    dry_run: bool = False
    min_signal_dbm: Optional[int] = None  # leave a target weaker than this alone; None = off

    _failures: int = field(default=0, init=False)
    _last_fault: Optional[Fault] = field(default=None, init=False)
    _cooldown_until: float = field(default=0.0, init=False)
    _last_good_ssid: Optional[str] = field(default=None, init=False)

    def run(self) -> None:
        """ Check now, then keep checking on every netlink event for the
        interface and on every heartbeat tick. Blocks forever. """
        log.info(
            "watching %s (heartbeat %.0fs, %d failures to recover, "
            "cooldown %.0fs%s)",
            self.interface, self.heartbeat, self.failures_before_recovery,
            self.cooldown, ", dry run" if self.dry_run else "",
        )
        self.check()
        for event in ifpeek.watch(
                interface=self.interface, timeout=self.heartbeat):
            if event is not None:
                log.debug("netlink event: %s", event)
            self.check()

    def check(self) -> Optional[Diagnosis]:
        """ Run one diagnose pass and react to it. Returns the diagnosis,
        or None while in cooldown. """
        remaining = self._cooldown_until - monotonic()
        if remaining > 0:
            log.debug("in cooldown for %.0fs more, skipping check", remaining)
            return None
        diagnosis = diagnose(
            self.interface, timeout=self.probe_timeout, targets=self.targets)
        self._handle(diagnosis)
        return diagnosis

    def _handle(self, diagnosis: Diagnosis) -> None:
        previous, self._last_fault = self._last_fault, diagnosis.fault

        if diagnosis.fault is Fault.HEALTHY:
            if previous is not None and previous is not Fault.HEALTHY:
                log.info("healthy again (was %s)", previous.value)
            self._failures = 0
            if diagnosis.essid is not None:
                self._last_good_ssid = diagnosis.essid
            log.debug("healthy: %s", diagnosis.detail)
            return

        if diagnosis.fault not in RECOVERABLE_FAULTS:
            # Not the association's fault: observe only, and break the
            # streak so the threshold keeps meaning "N checks in a row
            # blaming the association".
            self._failures = 0
            log.warning(
                "check failed: %s: %s (not recoverable by resetting the "
                "association, observing only)",
                diagnosis.fault.value, diagnosis.detail,
            )
            return

        self._failures += 1
        log.warning(
            "check failed (%d/%d): %s: %s; link: %s",
            self._failures, self.failures_before_recovery,
            diagnosis.fault.value, diagnosis.detail, self._link(),
        )
        if self._failures >= self.failures_before_recovery:
            self._recover(diagnosis)

    def _link(self) -> str:
        """ The associated BSS as nl80211 sees it right now (no scan). """
        try:
            bssid = ifpeek.access_point_mac_address(self.interface)
            if bssid is None:
                return "not associated"
            return _describe(ifpeek.AccessPoint(
                ssid="", bssid=bssid,
                frequency=ifpeek.access_point_frequency(self.interface),
                signal_dbm=ifpeek.access_point_signal_dbm(self.interface),
                signal_percent=0, security="", connected=True,
            ))
        except Exception as error:
            return f"unknown ({error})"

    def _look_for(self, target: Optional[str]) -> Sight:
        """ Ask for a fresh scan and find the target's strongest BSS, or the
        strongest BSS of any network iwd knows when there is no target. """
        try:
            access_points = ifpeek.scan_access_points(self.interface, fresh=True)
        except Exception as error:
            log.warning(
                "fresh scan on %s failed (%s), recovering without looking",
                self.interface, error,
            )
            return Sight(False, None)
        if target is None:
            try:
                wanted = set(iwd.known_networks_in_sight(self.interface))
            except Exception as error:
                log.warning(
                    "could not list iwd's known networks (%s), recovering "
                    "without looking", error,
                )
                return Sight(False, None)
        else:
            wanted = {target}
        # ifpeek returns the strongest signal first.
        for access_point in access_points:
            if access_point.ssid in wanted:
                return Sight(True, access_point)
        return Sight(True, None)

    def _recover(self, diagnosis: Diagnosis) -> None:
        target = self.ssid or self._last_good_ssid
        self._failures = 0
        self._cooldown_until = monotonic() + self.cooldown

        if self.dry_run:
            log.warning(
                "dry run: would recover %s now (fault %s, target %s)",
                self.interface, diagnosis.fault.value, target or "iwd's choice",
            )
            return

        sight = self._look_for(target)
        if sight.scanned:
            wanted = target or "a known network"
            if sight.access_point is None:
                log.warning(
                    "%s is not in sight of %s after a fresh scan: leaving the "
                    "association alone", wanted, self.interface,
                )
                return
            log.info(
                "%s in sight of %s: %s", sight.access_point.ssid, self.interface,
                _describe(sight.access_point),
            )
            signal = sight.access_point.signal_dbm
            if (self.min_signal_dbm is not None and signal is not None
                    and signal < self.min_signal_dbm):
                log.warning(
                    "%s is too weak (%d dBm < %d dBm) for a reconnect to help: "
                    "leaving the association alone",
                    sight.access_point.ssid, signal, self.min_signal_dbm,
                )
                return

        try:
            state = iwd.station_state(self.interface)
            if state in iwd.BUSY_STATES:
                log.info(
                    "iwd is already %s on %s, not interfering",
                    state, self.interface,
                )
                return
            if diagnosis.fault is Fault.ZOMBIE or state == "connected":
                log.warning("kicking the association on %s", self.interface)
                iwd.disconnect(self.interface)
            name = iwd.connect(self.interface, ssid=target)
            log.warning("reconnected %s to %s", self.interface, name)
        except Exception as error:
            log.error("recovery through iwd failed: %s", error)
