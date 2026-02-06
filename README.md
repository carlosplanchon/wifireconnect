# wifireconnect
*Python module to test and ensure connectivity on a network.*

## Rationale:
This module attemps to ensure connectivity on networks which have
stability problems on traffic routing (link layer).

## Requirements
You need network manager.
(sudo apt install network-manager)

## Installation
### Install with uv:
```bash
uv add wifireconnect
```

## Usage
From shell:

```
$ wifireconnect --help
Usage: wifireconnect [OPTIONS]

Run a connectivity test on a network connection (using ping) every 's' seconds
and try to reconnect if that test fails. (See your networks with 'nmcli conn')

Options:
  -e, --essid TEXT        AP's ESSID.  [required]
  -p, --password TEXT     AP's password.
  -t, --target TEXT       Target webpage for connectivity test.  [default: httpbin.com]
  -s, --sleep INTEGER     Time between connectivity tests in seconds.  [default: 10]
  -c, --count INTEGER     Number of attempts to ping target on the connectivity test.  [default: 2]
  -v, --verbose          Enable verbose output.
  --help                 Show this message and exit.
```

From the interpreter:

```
help(wifireconnect)
```
