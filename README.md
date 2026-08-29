# wifireconnect

![wifireconnect banner](https://raw.githubusercontent.com/carlosplanchon/wifireconnect/master/assets/banner.jpg)

*A small Linux network watchdog that diagnoses connectivity failures and
recovers Wi-Fi connections through [iwd](https://iwd.wiki.kernel.org/).*

[![CI](https://github.com/carlosplanchon/wifireconnect/actions/workflows/ci.yml/badge.svg)](https://github.com/carlosplanchon/wifireconnect/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/wifireconnect.svg)](https://pypi.org/project/wifireconnect/)
[![Python versions](https://img.shields.io/pypi/pyversions/wifireconnect.svg)](https://pypi.org/project/wifireconnect/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/carlosplanchon/wifireconnect)

> **Linux + iwd only.** Observation comes from
> [ifpeek](https://github.com/carlosplanchon/ifpeek) (netlink / nl80211);
> recovery talks to iwd over D-Bus (jeepney). No root needed, no
> subprocesses, no passwords.

## How it works

```text
netlink events ───────► immediate health check
                            │
periodic heartbeat ─────────┘
                            │
                            ▼
                         diagnose
                            │
                            ▼
                       maybe recover
```

`ifpeek.watch()` reacts immediately to link / address / route changes, and a
heartbeat covers the failures that produce no local event (a dead upstream,
a zombie association). Each check classifies the connection from L2 upwards:

| Fault            | Meaning                                          | Action        |
| ---------------- | ------------------------------------------------ | ------------- |
| `healthy`        | Internet reachable                               | nothing       |
| `no-interface`   | The interface does not exist                     | observe       |
| `associating`    | Association in progress (operstate DORMANT)      | wait          |
| `not-associated` | No carrier                                       | **reconnect** |
| `no-address`     | Associated but no usable IP (DHCP problem)       | observe       |
| `no-route`       | IP but no default route through the interface    | observe       |
| `zombie`         | Local stack looks fine, gateway does not answer  | **kick**      |
| `upstream`       | Gateway answers, internet does not               | nothing       |

The classification exists mostly to decide when NOT to act: resetting a
healthy association because the ISP is down only adds flapping.

Recovery is hardened against flapping and against fighting iwd:

- N consecutive checks blaming the association are required before acting
  (default 3); healthy or non-recoverable checks break the streak, so an
  upstream outage never accumulates credit towards a kick.
- After acting, a cooldown suppresses further checks (default 60 s), which
  also swallows the netlink event storm the recovery itself produces.
- If iwd is already `connecting` or `roaming`, the watchdog waits.

Reconnection goes to the network you name with `--ssid`, else to the last
network seen healthy, else to iwd's strongest known network in sight.
**iwd keeps the credentials** (its known networks), so there is no
`--password` and there never will be again.

## Requirements

- Linux with [iwd](https://iwd.wiki.kernel.org/) managing the Wi-Fi.
- Permission to talk to iwd on the system D-Bus: belong to the `wheel` or
  `network` group (see iwd's D-Bus policy), or run as root.

## Installation

```bash
uv tool install wifireconnect   # recommended: isolated CLI on your PATH
```

To use it [as a library](#as-a-library), add it as a dependency instead:

```bash
uv add wifireconnect
```

## Usage

Diagnose once (exit code: 0 healthy, 1 unhealthy, 2 no such interface):

```bash
$ wifireconnect check
wlan0: healthy: internet reachable (essid: MyNetwork)
```

Run the watchdog:

```bash
$ wifireconnect run
```

Useful options for `run`:

```text
-i, --interface TEXT  Wi-Fi interface to watch (default: the first one found).
-s, --ssid TEXT       Known network to reconnect to (default: last seen healthy).
-H, --heartbeat FLOAT Seconds between checks when no event arrives. [default: 30]
-f, --failures INT    Consecutive failures required before recovering. [default: 3]
-c, --cooldown FLOAT  Seconds to hold off after a recovery attempt. [default: 60]
-t, --timeout FLOAT   Seconds to wait for each probe answer. [default: 3]
    --dry-run         Diagnose and log, but never touch the association.
-v, --verbose         Debug output.
```

Start with `--dry-run` for a few days if you want to see what it *would*
have done before letting it act.

## As a service

A systemd unit template ships in
[`contrib/wifireconnect.service`](contrib/wifireconnect.service):

```bash
cp contrib/wifireconnect.service /etc/systemd/system/
# edit ExecStart (path, interface), then:
systemctl enable --now wifireconnect
```

## As a library

```python
from wifireconnect import diagnose, Watchdog

diagnose("wlan0")
# Diagnosis(fault=<Fault.HEALTHY: 'healthy'>, interface='wlan0',
#           detail='internet reachable', essid='MyNetwork', gateway=None)

Watchdog(interface="wlan0", dry_run=True).run()  # blocks
```

## Relation to ifpeek

[`ifpeek`](https://github.com/carlosplanchon/ifpeek) observes (netlink,
nl80211, read-only D-Bus); `wifireconnect` decides and acts (probes, iwd).
ifpeek peeks and never touches; everything that sends traffic or mutates
state lives here.
