"""Prompt 959, stage B3: a NAME that a VPN answers with a "fake" address is not refused as «blocked_address».

Found on a real phone (Android 16, a VPN switched on): the own-brain download stopped at once with `blocked_address`, because the VPN's DNS
answered `huggingface.co` with an address from its fake block (Clash / sing-box / v2ray "FakeIP": 198.18.0.0/15, fc00::/18) and the SSRF guard
refuses every non-public address. The tunnel turns such an address back into the real site, so a name that resolves into those blocks is a normal
VPN setup. The exception is narrow and these tests pin its edges:

* only for an address that a DNS answer gave for a NAME (never for an IP written in a URL or typed as the host);
* only the two fake blocks (not 10.x, 172.16.x, 192.168.x, 127.x, 169.254.x, 100.64.x, the metadata address ...);
* one real private address in the same answer still poisons the whole answer (the older rule is untouched);
* the TLS handshake is still made for the ORIGINAL name, so the certificate is checked as always;
* the policy switch `allow_vpn_fake_ips=False` brings the old behaviour back.
"""

import socket
import ssl
import unittest

from net_tools.policy import FetchPolicy, classify_ip, is_vpn_fake_ip, parse_url
from net_tools.transport import HttpClientTransport, TransportError, TransportRequest


def request(host="huggingface.co", port=443, scheme="https"):
    return TransportRequest(method="GET", url="%s://%s/" % (scheme, host), host=host, port=port, scheme=scheme, path_query="/", headers={},
                            timeout_s=1.0, max_bytes=1000)


def answer(*ips):
    rows = []
    for ip in ips:
        if ":" in ip:
            rows.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0)))
        else:
            rows.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)))
    return rows


class FakeSocket:
    def __init__(self, peer, log):
        self.peer, self.log, self.closed = peer, log, False

    def settimeout(self, value):
        pass

    def connect(self, address):
        self.log.append(address)

    def getpeername(self):
        return self.peer

    def close(self):
        self.closed = True


class Run:
    """One request through a transport whose DNS answer, sockets and TLS are fakes; the handshake always fails, which ends the run right
    after the address checks (that is exactly the part under test)."""

    def __init__(self, ips, policy=None, peer=None, host="huggingface.co"):
        self.connects, self.handshakes, self.resolved, self.sockets = [], [], [], []
        rows = answer(*ips)
        outer = self

        class Context:
            def wrap_socket(self, sock, server_hostname=None):
                outer.handshakes.append(server_hostname)
                raise ssl.SSLCertVerificationError("certificate verify failed")

        def resolver(name, port, type=0):
            self.resolved.append(name)
            return rows

        def factory(family, kind):
            chosen = peer if peer is not None else (ips[0], 443)
            self.sockets.append(FakeSocket(chosen, self.connects))
            return self.sockets[-1]
        self.transport = HttpClientTransport(policy or FetchPolicy(), resolver=resolver, socket_factory=factory, ssl_context_factory=Context)
        self.error = None
        try:
            self.transport(request(host=host))
        except TransportError as err:
            self.error = err


class IsVpnFakeIpTests(unittest.TestCase):
    def test_the_two_fake_blocks_are_recognised_at_their_edges(self):
        for ip in ("198.18.0.0", "198.18.0.1", "198.19.255.254", "198.19.255.255", "fc00::1", "fc00:3fff:ffff::1", "::ffff:198.18.0.5",
                   "fc00::1%wlan0"):
            with self.subTest(ip=ip):
                self.assertTrue(is_vpn_fake_ip(ip))

    def test_everything_else_is_not_a_fake_address(self):
        for ip in ("198.17.255.255", "198.20.0.0", "10.0.0.1", "10.10.34.34", "172.16.0.9", "192.168.1.1", "127.0.0.1", "169.254.169.254",
                   "100.64.0.1", "0.0.0.0", "8.8.8.8", "93.184.216.34", "fc00:4000::1", "fd00::1", "fe80::1", "::1", "2606:4700::1111",
                   "::ffff:10.0.0.1", "not an ip", "", None, 5, 1.5, b"198.18.0.1"):
            with self.subTest(ip=ip):
                self.assertFalse(is_vpn_fake_ip(ip))

    def test_the_classifier_itself_is_unchanged_the_exception_sits_on_top_of_it(self):
        for ip in ("198.18.0.5", "198.19.0.1", "fc00::5"):
            self.assertEqual(classify_ip(ip), "private", ip)
        self.assertEqual(classify_ip("100.64.0.1"), "carrier_grade_nat")
        self.assertEqual(classify_ip("10.10.34.34"), "private")


class PolicyFieldTests(unittest.TestCase):
    def test_the_exception_is_on_by_default_and_must_be_a_bool(self):
        self.assertIs(FetchPolicy().allow_vpn_fake_ips, True)
        self.assertIs(FetchPolicy(allow_vpn_fake_ips=False).allow_vpn_fake_ips, False)
        for bad in ("yes", 1, None, 0.0):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    FetchPolicy(allow_vpn_fake_ips=bad)

    def test_a_copy_with_another_timeout_keeps_the_switch(self):
        self.assertIs(FetchPolicy(allow_vpn_fake_ips=False).with_timeout(3.0).allow_vpn_fake_ips, False)
        self.assertIs(FetchPolicy().with_timeout(3.0).allow_vpn_fake_ips, True)

    def test_the_app_wide_default_does_not_open_the_old_loophole(self):
        policy = FetchPolicy()
        self.assertFalse(policy.allow_private_addresses)
        self.assertFalse(policy.allow_http)


class NameAnsweredWithFakeAddressTests(unittest.TestCase):
    def test_a_name_that_resolves_into_198_18_goes_on_to_the_tls_handshake_for_the_original_name(self):
        run = Run(["198.18.0.7"])
        self.assertEqual(run.error.code, "tls_error", "the address checks passed; only the (faked) certificate check stopped it")
        self.assertEqual(run.connects, [("198.18.0.7", 443)])
        self.assertEqual(run.handshakes, ["huggingface.co"], "the certificate is still checked for the ORIGINAL name")
        self.assertEqual(run.resolved, ["huggingface.co"])

    def test_the_second_fake_half_and_the_ipv6_fake_block_pass_too(self):
        for ips in (["198.19.3.4"], ["fc00::7"], ["198.18.0.7", "fc00::7"], ["93.184.216.34", "198.18.0.7"]):
            with self.subTest(ips=ips):
                run = Run(ips)
                self.assertEqual(run.error.code, "tls_error")
                self.assertEqual(run.handshakes, ["huggingface.co"])

    def test_the_connection_may_end_up_at_the_fake_peer_address(self):
        run = Run(["198.18.0.7"], peer=("198.18.0.7", 443))
        self.assertEqual(run.error.code, "tls_error")
        self.assertTrue(run.sockets and run.handshakes)

    def test_a_real_private_address_in_the_same_answer_still_poisons_it(self):
        run = Run(["198.18.0.7", "10.0.0.7"])
        self.assertEqual((run.error.code, run.error.detail), ("blocked_address", "private"))
        self.assertEqual(run.sockets, [], "no socket may be created")
        self.assertEqual(run.handshakes, [])

    def test_every_other_non_public_address_is_still_refused_for_a_name(self):
        cases = (("10.10.34.34", "private"), ("192.168.1.1", "private"), ("172.16.0.9", "private"), ("127.0.0.1", "loopback"),
                 ("169.254.169.254", "metadata"), ("169.254.1.1", "link_local"), ("100.64.0.1", "carrier_grade_nat"), ("0.0.0.0", "unspecified"),
                 ("::1", "loopback"), ("fd00::1", "private"), ("fc00:4000::1", "private"), ("fe80::1", "link_local"))
        for ip, reason in cases:
            with self.subTest(ip=ip):
                run = Run([ip])
                self.assertEqual((run.error.code, run.error.detail), ("blocked_address", reason))
                self.assertEqual(run.sockets, [])

    def test_after_connecting_a_real_private_peer_is_still_refused_even_for_a_fake_answer(self):
        run = Run(["198.18.0.7"], peer=("10.0.0.1", 443))
        self.assertEqual((run.error.code, run.error.detail), ("blocked_address", "peer_private"))
        self.assertTrue(run.sockets[0].closed)
        self.assertEqual(run.handshakes, [])

    def test_with_the_switch_off_the_fake_address_is_refused_as_before(self):
        run = Run(["198.18.0.7"], policy=FetchPolicy(allow_vpn_fake_ips=False))
        self.assertEqual((run.error.code, run.error.detail), ("blocked_address", "private"))
        self.assertEqual(run.sockets, [])
        run = Run(["198.18.0.7"], policy=FetchPolicy(allow_vpn_fake_ips=False), peer=("198.18.0.7", 443))
        self.assertEqual(run.error.detail, "private")


class IpWrittenInTheUrlNeverGetsTheExceptionTests(unittest.TestCase):
    def test_a_literal_host_is_refused_without_resolving_or_connecting(self):
        for host in ("198.18.0.7", "198.19.1.1", "fc00::7", "::ffff:198.18.0.7"):
            with self.subTest(host=host):
                run = Run(["93.184.216.34"], host=host)
                self.assertEqual((run.error.code, run.error.detail), ("blocked_address", "private"))
                self.assertEqual(run.resolved, [])
                self.assertEqual(run.sockets, [])

    def test_a_url_with_such_an_ip_is_refused_when_it_is_parsed(self):
        for url in ("https://198.18.0.7/", "https://198.19.1.1/x", "https://[fc00::7]/", "https://[::ffff:198.18.0.7]/"):
            with self.subTest(url=url):
                parsed = parse_url(url)
                self.assertEqual((parsed.code, parsed.detail), ("blocked_address", "private"))


if __name__ == "__main__":
    unittest.main()
