"""Tests for the SSRF-safe fetcher; every path runs offline through the test seams."""

import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import fetchguard  # noqa: E402
from bridge.core.fetchguard import FetchError, safe_fetch  # noqa: E402

PUBLIC_IP = "93.184.216.34"


class Script:
    """Scripted opener and resolver that record every call."""

    def __init__(self, responses, table=None):
        self.responses = list(responses)
        self.table = table or {}
        self.resolved = []
        self.opened = []

    def resolver(self, host):
        self.resolved.append(host)
        return self.table.get(host, [PUBLIC_IP])

    def opener(self, scheme, host, port, ip, path, headers, timeout):
        self.opened.append(
            {"scheme": scheme, "host": host, "port": port, "ip": ip, "path": path, "headers": headers}
        )
        status, headers_out, body = self.responses.pop(0)
        reader = body if hasattr(body, "read") else io.BytesIO(body)
        return status, headers_out, reader

    def fetch(self, url, **kwargs):
        return safe_fetch(url, resolver=self.resolver, opener=self.opener, **kwargs)


def ok(body=b"hello", ctype="text/html; charset=utf-8", **extra):
    return 200, {"content-type": ctype, **extra}, body


def redirect(location, status=302):
    return status, {"location": location}, b""


class Endless:
    """Reader that never ends, counting bytes handed out."""

    def __init__(self):
        self.served = 0

    def read(self, size):
        self.served += size
        return b"x" * size


class RejectionTests(unittest.TestCase):
    def assert_reason(self, reason, call):
        with self.assertRaises(FetchError) as ctx:
            call()
        self.assertEqual(ctx.exception.reason, reason)

    def test_blocked_address_classes(self):
        cases = {
            "loopback4": "127.0.0.1",
            "loopback6": "::1",
            "private10": "10.1.2.3",
            "private172": "172.16.0.5",
            "private192": "192.168.1.1",
            "link_local": "169.254.1.1",
            "metadata": "169.254.169.254",
            "link_local6": "fe80::1",
            "unique_local6": "fd00::1",
            "multicast": "224.0.0.1",
            "multicast6": "ff02::1",
            "reserved": "240.0.0.1",
            "unspecified": "0.0.0.0",
            "unspecified6": "::",
            "mapped_loopback": "::ffff:127.0.0.1",
            "mapped_metadata": "::ffff:169.254.169.254",
            "mapped_private": "::ffff:10.0.0.1",
            "shared_space": "100.64.0.1",
        }
        for name, address in cases.items():
            with self.subTest(name):
                script = Script([ok()], {"evil.test": [address]})
                self.assert_reason("blocked_address", lambda: script.fetch("http://evil.test/"))
                self.assertEqual(script.opened, [])

    def test_any_blocked_address_rejects(self):
        script = Script([ok()], {"mixed.test": [PUBLIC_IP, "10.0.0.1"]})
        self.assert_reason("blocked_address", lambda: script.fetch("http://mixed.test/"))
        self.assertEqual(script.opened, [])

    def test_ip_literal_is_checked(self):
        script = Script([ok()], {"127.0.0.1": ["127.0.0.1"]})
        self.assert_reason("blocked_address", lambda: script.fetch("http://127.0.0.1/"))

    def test_userinfo_rejected(self):
        script = Script([ok()])
        self.assert_reason("blocked_address", lambda: script.fetch("http://user:pw@example.com/"))
        self.assert_reason("blocked_address", lambda: script.fetch("http://user@example.com/"))
        self.assertEqual(script.resolved, [])

    def test_scheme_rejected(self):
        script = Script([ok()])
        for url in ("ftp://example.com/", "file:///etc/passwd", "gopher://example.com/", "example.com"):
            with self.subTest(url):
                self.assert_reason("scheme", lambda: script.fetch(url))
        self.assertEqual(script.resolved, [])

    def test_dns_failures(self):
        script = Script([ok()], {"empty.test": []})
        self.assert_reason("dns", lambda: script.fetch("http://empty.test/"))

        def boom(host):
            raise RuntimeError("nope")

        self.assert_reason("dns", lambda: safe_fetch("http://x.test/", resolver=boom, opener=script.opener))

    def test_non_2xx(self):
        script = Script([(404, {}, b"missing")])
        self.assert_reason("http_status", lambda: script.fetch("http://example.com/"))

    def test_network_error_mapped(self):
        def broken(*args):
            raise ConnectionRefusedError("refused")

        self.assert_reason(
            "network",
            lambda: safe_fetch("http://example.com/", resolver=lambda h: [PUBLIC_IP], opener=broken),
        )

    def test_timeout_mapped(self):
        def slow(*args):
            raise TimeoutError("timed out")

        self.assert_reason(
            "timeout",
            lambda: safe_fetch("http://example.com/", resolver=lambda h: [PUBLIC_IP], opener=slow),
        )

    def test_deadline_exhausted(self):
        script = Script([(200, {}, Endless())])
        self.assert_reason("timeout", lambda: script.fetch("http://example.com/", timeout=0.0))


class RedirectTests(unittest.TestCase):
    def test_follows_and_revalidates(self):
        script = Script([redirect("/next"), redirect("https://other.test/final"), ok(b"done")])
        result = script.fetch("http://example.com/start")
        self.assertEqual(result.final_url, "https://other.test/final")
        self.assertEqual(result.body, b"done")
        self.assertEqual(script.resolved, ["example.com", "example.com", "other.test"])
        self.assertEqual(script.opened[1]["path"], "/next")
        self.assertEqual(script.opened[2]["scheme"], "https")

    def test_redirect_to_private_address(self):
        script = Script([redirect("http://internal.test/")], {"internal.test": ["10.0.0.9"]})
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/")
        self.assertEqual(ctx.exception.reason, "blocked_address")
        self.assertEqual(len(script.opened), 1)

    def test_redirect_to_bad_scheme(self):
        script = Script([redirect("file:///etc/passwd")])
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/")
        self.assertEqual(ctx.exception.reason, "scheme")

    def test_redirect_to_userinfo(self):
        script = Script([redirect("http://a:b@example.com/")])
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/")
        self.assertEqual(ctx.exception.reason, "blocked_address")

    def test_redirect_limit(self):
        script = Script([redirect("/again")] * 10)
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/", max_redirects=3)
        self.assertEqual(ctx.exception.reason, "too_many_redirects")
        self.assertEqual(len(script.opened), 4)

    def test_exactly_max_redirects_allowed(self):
        script = Script([redirect("/a"), redirect("/b"), ok()])
        self.assertEqual(script.fetch("http://example.com/", max_redirects=2).status, 200)


class SizeTests(unittest.TestCase):
    def test_streaming_cap(self):
        endless = Endless()
        script = Script([(200, {}, endless)])
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/", max_bytes=100_000)
        self.assertEqual(ctx.exception.reason, "too_large")
        self.assertLessEqual(endless.served, 100_000 + 2 * 64 * 1024)

    def test_content_length_cap_before_reading(self):
        endless = Endless()
        script = Script([(200, {"content-length": "5000"}, endless)])
        with self.assertRaises(FetchError) as ctx:
            script.fetch("http://example.com/", max_bytes=1000)
        self.assertEqual(ctx.exception.reason, "too_large")
        self.assertEqual(endless.served, 0)

    def test_body_at_cap_is_allowed(self):
        script = Script([ok(b"a" * 1000)])
        self.assertEqual(len(script.fetch("http://example.com/", max_bytes=1000).body), 1000)


class HappyPathTests(unittest.TestCase):
    def test_result_fields_and_request(self):
        script = Script([ok(b"<html>", "Text/HTML; charset=UTF-8")])
        result = script.fetch("https://example.com:8443/a/b?q=1")
        self.assertEqual(result.url, "https://example.com:8443/a/b?q=1")
        self.assertEqual(result.final_url, result.url)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.content_type, "text/html")
        self.assertEqual(result.body, b"<html>")
        sent = script.opened[0]
        self.assertEqual((sent["host"], sent["port"], sent["ip"]), ("example.com", 8443, PUBLIC_IP))
        self.assertEqual(sent["path"], "/a/b?q=1")
        self.assertEqual(sent["headers"]["User-Agent"], fetchguard.DEFAULT_UA)

    def test_no_cookies_or_credentials(self):
        script = Script([ok()])
        script.fetch("http://example.com/")
        names = {name.lower() for name in script.opened[0]["headers"]}
        self.assertFalse(names & {"cookie", "authorization", "proxy-authorization"})

    def test_missing_content_type(self):
        script = Script([(200, {}, b"x")])
        self.assertEqual(script.fetch("http://example.com/").content_type, "")

    def test_dns_rebinding_pin(self):
        calls = []

        def rebinding(host):
            calls.append(host)
            return [PUBLIC_IP] if len(calls) == 1 else ["127.0.0.1"]

        script = Script([ok()])
        result = safe_fetch("http://example.com/", resolver=rebinding, opener=script.opener)
        self.assertEqual(result.status, 200)
        self.assertEqual(calls, ["example.com"])
        self.assertEqual(script.opened[0]["ip"], PUBLIC_IP)


if __name__ == "__main__":
    unittest.main()
