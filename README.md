# wifireconnect
*Python3 module to test and ensure connectivity on a network.*

## Rationale:
This module attemps to ensure connectivity on networks which have
stability problems on traffic routing (link layer).

## Requirements
You need network manager.
(sudo apt install network-manager)

## Installation
### Install with pip
```
pip3 install --user -U wifireconnect
```

## Usage
From shell:

```
$ python3.7 wifireconnect -h
usage: wifireconnect.py [-h] [-v] [-t TARGET] [-s SLEEP_BETWEEN] [-c COUNT]
                   [-e ESSID] [-p PASSWORD]

Run a connectivity test on a network connection(using ping) every a 's' time
and try to reconnect if that test fail.
(See your networks with 'nmcli conn')

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Verbosity.
  -t TARGET, --target TARGET
                        Target webpage. Default httpbin.com.
  -s SLEEP_BETWEEN, --sleep SLEEP_BETWEEN
                        Time between connectivity tests. Default: 10
  -c COUNT, --count COUNT
                        Num of attemps to ping target on the connectivity
                        test. Default: 2
  -e ESSID, --essid ESSID
                        AP's ESSID.
  -p PASSWORD, --password PASSWORD
                        AP's password.
```

From the interpreter:

```
help(wifireconnect)
```
