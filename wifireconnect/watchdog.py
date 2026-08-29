#!/usr/bin/env python3

"""
The watchdog loop: observe with ifpeek, classify with diagnose, recover
through iwd.

Design rules:

- Hybrid trigger: netlink events (via ``ifpeek.watch``) fire an immediate
  check, and a heartbeat covers the failures that produce no local event
  (upstream outage, zombie association).
- Hysteresis: N consecutive failed checks are required before acting.
- Cooldown: after acting, checks are suppressed for a while. This also
  swallows the netlink event storm the recovery itself produces.
- Never fight iwd: if the station is "connecting" or "roaming", iwd is
  already on it. ASSOCIATING and UPSTREAM faults never trigger recovery,
  and neither do NO_ADDRESS or NO_ROUTE (those belong to the DHCP client
  or the routing setup, and resetting the association does not own them).
- The target network is remembered while healthy (last known good SSID),
  because once the link is down ifpeek cannot tell you what it was.
"""

import logging

from dataclasses import dataclass, field
from time import monotonic
from typing import Optional

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

    _failures: int = field(default=0, init=False)
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
        if diagnosis.fault is Fault.HEALTHY:
            if self._failures:
                log.info("healthy again after %d failed checks", self._failures)
            self._failures = 0
            if diagnosis.essid is not None:
                self._last_good_ssid = diagnosis.essid
            log.debug("healthy: %s", diagnosis.detail)
            return

        self._failures += 1
        log.warning(
            "check failed (%d/%d): %s: %s",
            self._failures, self.failures_before_recovery,
            diagnosis.fault.value, diagnosis.detail,
        )
        if diagnosis.fault not in RECOVERABLE_FAULTS:
            log.info(
                "%s is not recoverable by resetting the association: "
                "observing only", diagnosis.fault.value,
            )
            return
        if self._failures < self.failures_before_recovery:
            return
        self._recover(diagnosis)

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
