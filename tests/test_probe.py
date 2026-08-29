"""Tests for the TCP reachability probes. The socket boundary is mocked."""

from contextlib import nullcontext

from wifireconnect import probe


class TestTcpProbe:
    def test_ok(self, monkeypatch):
        monkeypatch.setattr(
            probe, "create_connection", lambda addr, timeout: nullcontext())
        assert probe.tcp_probe("1.1.1.1", 443) is probe.ProbeResult.OK

    def test_refused_means_alive(self, monkeypatch):
        def refuse(addr, timeout):
            raise ConnectionRefusedError

        monkeypatch.setattr(probe, "create_connection", refuse)
        assert probe.tcp_probe("192.168.1.1", 53) is probe.ProbeResult.REFUSED
        # An RST proves the peer is alive: the gateway discriminator
        # depends on this.
        assert probe.host_is_alive("192.168.1.1", 53) is True
        assert probe.gateway_is_alive("192.168.1.1") is True

    def test_timeout_is_unreachable(self, monkeypatch):
        def drop(addr, timeout):
            raise TimeoutError

        monkeypatch.setattr(probe, "create_connection", drop)
        assert probe.tcp_probe("192.0.2.1", 443) is probe.ProbeResult.UNREACHABLE
        assert probe.host_is_alive("192.0.2.1", 443) is False
        assert probe.gateway_is_alive("192.0.2.1") is False

    def test_network_error_is_unreachable(self, monkeypatch):
        def fail(addr, timeout):
            raise OSError("network is unreachable")

        monkeypatch.setattr(probe, "create_connection", fail)
        assert probe.tcp_probe("10.0.0.1", 443) is probe.ProbeResult.UNREACHABLE


class TestGatewayProbe:
    def test_a_gateway_dropping_dns_but_serving_https_is_alive(
            self, monkeypatch):
        def per_port(host, port, timeout=None):
            if port == 443:
                return probe.ProbeResult.OK
            return probe.ProbeResult.UNREACHABLE

        monkeypatch.setattr(probe, "tcp_probe", per_port)
        assert probe.gateway_is_alive("192.168.1.1") is True

    def test_silence_on_every_port_is_dead(self, monkeypatch):
        attempts = []

        def silent(host, port, timeout=None):
            attempts.append(port)
            return probe.ProbeResult.UNREACHABLE

        monkeypatch.setattr(probe, "tcp_probe", silent)
        assert probe.gateway_is_alive("192.168.1.1") is False
        assert attempts == list(probe.GATEWAY_PROBE_PORTS)


class TestInternetReachability:
    def test_a_later_target_saves_the_check(self, monkeypatch):
        results = {
            "1.1.1.1": probe.ProbeResult.UNREACHABLE,
            "8.8.8.8": probe.ProbeResult.OK,
        }
        monkeypatch.setattr(
            probe, "tcp_probe",
            lambda host, port, timeout=None: results[host])
        assert probe.internet_is_reachable() is True

    def test_all_targets_dead(self, monkeypatch):
        monkeypatch.setattr(
            probe, "tcp_probe",
            lambda host, port, timeout=None: probe.ProbeResult.UNREACHABLE)
        assert probe.internet_is_reachable() is False
