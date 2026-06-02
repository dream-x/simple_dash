"""Tests for generate_dashboard.py.

Run from the project root:

    just test
    # or
    python3 -m unittest discover tests -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate_dashboard as gd  # noqa: E402


class TestMergeConfigDicts(unittest.TestCase):
    def test_simple_override(self):
        merged = gd.merge_config_dicts({"a": 1, "b": 2}, {"b": 3, "c": 4})
        self.assertEqual(merged, {"a": 1, "b": 3, "c": 4})

    def test_lists_append(self):
        base = {"services": [{"port": 80}]}
        override = {"services": [{"port": 443}]}
        self.assertEqual(
            gd.merge_config_dicts(base, override)["services"],
            [{"port": 80}, {"port": 443}],
        )

    def test_hosts_dict_merge(self):
        base = {"hosts": {"192.168.1.1": "Router"}}
        override = {"hosts": {"192.168.1.2": "NAS"}}
        merged = gd.merge_config_dicts(base, override)
        self.assertEqual(merged["hosts"], {"192.168.1.1": "Router", "192.168.1.2": "NAS"})

    def test_preserve_subnets_keeps_base(self):
        merged = gd.merge_config_dicts(
            {"subnets": ["10.0.0.0/24"]},
            {"subnets": ["10.0.1.0/24"]},
            preserve_subnets=True,
        )
        self.assertEqual(merged["subnets"], ["10.0.0.0/24"])

    def test_preserve_subnets_false_overwrites(self):
        merged = gd.merge_config_dicts(
            {"subnets": ["10.0.0.0/24"]},
            {"subnets": ["10.0.1.0/24"]},
            preserve_subnets=False,
        )
        self.assertEqual(merged["subnets"], ["10.0.1.0/24"])

    def test_preserve_subnets_writes_when_base_has_none(self):
        merged = gd.merge_config_dicts(
            {},
            {"subnets": ["10.0.0.0/24"]},
            preserve_subnets=True,
        )
        self.assertEqual(merged["subnets"], ["10.0.0.0/24"])

    def test_base_is_not_mutated(self):
        base = {"services": [{"port": 80}]}
        override = {"services": [{"port": 443}]}
        gd.merge_config_dicts(base, override)
        self.assertEqual(base["services"], [{"port": 80}])


class TestResolveConfigData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(gd, "DEFAULT_CONFIG_PATH", self.tmp_path / "public.json"),
            mock.patch.object(gd, "DEFAULT_LOCAL_CONFIG_PATH", self.tmp_path / "local.json"),
            mock.patch.object(gd, "DEFAULT_OVERRIDES_PATH", self.tmp_path / "overrides.json"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def write(self, name: str, data: dict) -> None:
        (self.tmp_path / name).write_text(json.dumps(data), encoding="utf-8")

    def ns(self, config: str | None = None):
        return mock.Mock(config=config)

    def test_local_overwrites_public_subnets(self):
        self.write("public.json", {"subnets": ["10.0.0.0/24"], "services": [{"port": 80}]})
        self.write("local.json", {"subnets": ["10.0.1.0/24"], "services": [{"port": 8123}]})
        data, _ = gd.resolve_config_data(self.ns())
        self.assertEqual(data["subnets"], ["10.0.1.0/24"])
        self.assertEqual(len(data["services"]), 2)

    def test_overrides_never_overwrite_subnets(self):
        self.write("public.json", {"subnets": ["10.0.0.0/24"]})
        self.write("overrides.json", {"subnets": ["10.0.99.0/24"], "hosts": {"10.0.0.1": "Router"}})
        data, _ = gd.resolve_config_data(self.ns())
        self.assertEqual(data["subnets"], ["10.0.0.0/24"])
        self.assertEqual(data["hosts"], {"10.0.0.1": "Router"})

    def test_explicit_config_skips_public_and_local(self):
        self.write("public.json", {"subnets": ["10.0.0.0/24"]})
        self.write("local.json", {"subnets": ["10.0.1.0/24"]})
        custom = self.tmp_path / "custom.json"
        custom.write_text(json.dumps({"subnets": ["172.16.0.0/24"]}), encoding="utf-8")
        data, _ = gd.resolve_config_data(self.ns(config=str(custom)))
        self.assertEqual(data["subnets"], ["172.16.0.0/24"])

    def test_explicit_config_still_layers_overrides(self):
        custom = self.tmp_path / "custom.json"
        custom.write_text(json.dumps({"subnets": ["172.16.0.0/24"]}), encoding="utf-8")
        self.write("overrides.json", {"hosts": {"172.16.0.1": "Router"}})
        data, _ = gd.resolve_config_data(self.ns(config=str(custom)))
        self.assertEqual(data["subnets"], ["172.16.0.0/24"])
        self.assertEqual(data["hosts"], {"172.16.0.1": "Router"})

    def test_explicit_config_pointing_to_overrides_does_not_double_load(self):
        # Edge case: --config dashboard_overrides.json should not re-merge itself.
        self.write("overrides.json", {"hosts": {"10.0.0.1": "Router"}})
        data, _ = gd.resolve_config_data(self.ns(config=str(self.tmp_path / "overrides.json")))
        self.assertEqual(data["hosts"], {"10.0.0.1": "Router"})

    def test_no_files_returns_empty(self):
        data, _ = gd.resolve_config_data(self.ns())
        self.assertEqual(data, {})

    def test_explicit_missing_raises(self):
        with self.assertRaises(SystemExit):
            gd.resolve_config_data(self.ns(config=str(self.tmp_path / "nope.json")))


class TestParseManualServicesDedup(unittest.TestCase):
    def test_dedup_same_name_url(self):
        raw = [
            {"name": "Router", "url": "http://192.168.1.1"},
            {"name": "Router", "url": "http://192.168.1.1"},
        ]
        self.assertEqual(len(gd.parse_manual_services(raw, "test")), 1)

    def test_dedup_case_insensitive(self):
        raw = [
            {"name": "Router", "url": "http://192.168.1.1"},
            {"name": "ROUTER", "url": "HTTP://192.168.1.1"},
        ]
        self.assertEqual(len(gd.parse_manual_services(raw, "test")), 1)

    def test_no_dedup_for_different_url(self):
        raw = [
            {"name": "Router", "url": "http://192.168.1.1"},
            {"name": "Router", "url": "http://192.168.2.1"},
        ]
        self.assertEqual(len(gd.parse_manual_services(raw, "test")), 2)

    def test_dedup_inside_grouped_form(self):
        raw = [{"group": "Infra", "items": [
            {"name": "Router", "url": "http://192.168.1.1"},
            {"name": "Router", "url": "http://192.168.1.1"},
        ]}]
        self.assertEqual(len(gd.parse_manual_services(raw, "test")), 1)


class TestParseBookmarksDedup(unittest.TestCase):
    def test_dedup_grouped(self):
        raw = [{"group": "Cloud", "items": [
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "GitHub", "url": "https://github.com"},
        ]}]
        self.assertEqual(len(gd.parse_bookmarks(raw)), 1)

    def test_dedup_flat(self):
        raw = [
            {"name": "GitHub", "url": "https://github.com"},
            {"name": "GitHub", "url": "https://github.com"},
        ]
        self.assertEqual(len(gd.parse_bookmarks(raw)), 1)


class TestParseDuplicateGroups(unittest.TestCase):
    def test_requires_at_least_two_hosts(self):
        # Single-host groups silently dropped.
        raw = [{"id": "x", "hosts": ["10.0.0.1"]}]
        self.assertEqual(gd.parse_duplicate_groups(raw), [])

    def test_two_hosts_kept(self):
        raw = [{"id": "x", "name": "X", "hosts": ["10.0.0.1", "10.0.0.2"]}]
        groups = gd.parse_duplicate_groups(raw)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].hosts, ("10.0.0.1", "10.0.0.2"))


class TestIsSafeExternalUrl(unittest.TestCase):
    def test_safe_schemes(self):
        for url in ("http://x", "https://x", "mailto:a@b", "tel:+1234", "myapp://path"):
            self.assertTrue(gd.is_safe_external_url(url), url)

    def test_unsafe_schemes_and_relative(self):
        for url in ("javascript:alert(1)", "JAVASCRIPT:x", "data:text/html,x", "/relative/path", "", "no-scheme"):
            self.assertFalse(gd.is_safe_external_url(url), url)


class TestManualFromDictValidation(unittest.TestCase):
    def test_javascript_rejected(self):
        with self.assertRaises(SystemExit):
            gd.manual_from_dict({"name": "Bad", "url": "javascript:alert(1)"}, "g", "src")

    def test_data_uri_rejected(self):
        with self.assertRaises(SystemExit):
            gd.manual_from_dict({"name": "Bad", "url": "data:text/html,x"}, "g", "src")

    def test_https_accepted(self):
        m = gd.manual_from_dict({"name": "GH", "url": "https://github.com"}, "g", "src")
        self.assertEqual(m.url, "https://github.com")

    def test_missing_url_rejected(self):
        with self.assertRaises(SystemExit):
            gd.manual_from_dict({"name": "Bad"}, "g", "src")


class TestBookmarkFromDictValidation(unittest.TestCase):
    def test_javascript_rejected(self):
        with self.assertRaises(SystemExit):
            gd.bookmark_from_dict({"name": "Bad", "url": "javascript:alert(1)"}, "g")

    def test_https_accepted(self):
        b = gd.bookmark_from_dict({"name": "GH", "url": "https://github.com"}, "g")
        self.assertEqual(b.url, "https://github.com")

    def test_empty_url_allowed(self):
        # Bookmarks with empty URL pass through (filtered upstream by parse_bookmarks).
        b = gd.bookmark_from_dict({"name": "Just text"}, "g")
        self.assertEqual(b.url, "")


class TestBoundedGather(unittest.TestCase):
    def test_preserves_order(self):
        async def work(x):
            await asyncio.sleep(0)
            return x * 2

        self.assertEqual(asyncio.run(gd.bounded_gather([1, 2, 3, 4, 5], work, 2)), [2, 4, 6, 8, 10])

    def test_empty_input(self):
        async def work(x):
            return x

        self.assertEqual(asyncio.run(gd.bounded_gather([], work, 4)), [])

    def test_concurrency_capped(self):
        max_active = 0

        async def run() -> int:
            active = 0
            nonlocal_max = 0
            lock = asyncio.Lock()

            async def work(x):
                nonlocal active, nonlocal_max
                async with lock:
                    active += 1
                    nonlocal_max = max(nonlocal_max, active)
                await asyncio.sleep(0.01)
                async with lock:
                    active -= 1
                return x

            await gd.bounded_gather(list(range(20)), work, 4)
            return nonlocal_max

        self.assertLessEqual(asyncio.run(run()), 4)

    def test_more_workers_than_items(self):
        async def work(x):
            return x

        self.assertEqual(asyncio.run(gd.bounded_gather([1, 2, 3], work, 100)), [1, 2, 3])

    def test_exception_propagates(self):
        async def work(x):
            if x == 2:
                raise RuntimeError("boom")
            return x

        with self.assertRaises(RuntimeError):
            asyncio.run(gd.bounded_gather([1, 2, 3], work, 2))


class TestParsePorts(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(gd.parse_ports("80,443"), [80, 443])

    def test_range(self):
        self.assertEqual(gd.parse_ports("8000-8003"), [8000, 8001, 8002, 8003])

    def test_mixed(self):
        self.assertEqual(gd.parse_ports("1-3,5,8000-8001"), [1, 2, 3, 5, 8000, 8001])

    def test_whitespace_tolerated(self):
        self.assertEqual(gd.parse_ports(" 80 , 443 "), [80, 443])


class TestParseHttpResponse(unittest.TestCase):
    def test_200_with_title_and_server(self):
        data = b"HTTP/1.1 200 OK\r\nServer: nginx/1.20\r\n\r\n<html><title>Foo</title></html>"
        status, fp, _, _ = gd.parse_http_response(data)
        self.assertEqual(status, 200)
        self.assertIn("Foo", fp)
        self.assertIn("nginx", fp)

    def test_401_with_realm(self):
        data = b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="Router"\r\n\r\n'
        status, fp, _, _ = gd.parse_http_response(data)
        self.assertEqual(status, 401)
        self.assertIn("Router", fp)

    def test_no_status_line(self):
        status, _, _, _ = gd.parse_http_response(b"random garbage")
        self.assertIsNone(status)


class TestStatusFromHttp(unittest.TestCase):
    def test_auth(self):
        self.assertEqual(gd.status_from_http(401), "auth")
        self.assertEqual(gd.status_from_http(403), "auth")

    def test_5xx_is_error(self):
        self.assertEqual(gd.status_from_http(500), "error")
        self.assertEqual(gd.status_from_http(503), "error")

    def test_default_online(self):
        self.assertEqual(gd.status_from_http(200), "online")
        self.assertEqual(gd.status_from_http(None), "online")
        self.assertEqual(gd.status_from_http(301), "online")


class TestCleanFingerprint(unittest.TestCase):
    def test_strips_html(self):
        self.assertEqual(gd.clean_fingerprint("<b>Hello</b> world"), "Hello world")

    def test_truncates_to_max_len(self):
        self.assertEqual(len(gd.clean_fingerprint("a" * 200)), 140)

    def test_collapses_whitespace(self):
        self.assertEqual(gd.clean_fingerprint("a\n\n  b"), "a b")

    def test_decodes_html_entities(self):
        self.assertEqual(gd.clean_fingerprint("foo &amp; bar"), "foo & bar")

    def test_strips_control_chars(self):
        self.assertEqual(gd.clean_fingerprint("foo\x00\x01bar"), "foo bar")


class TestSlugAndMac(unittest.TestCase):
    def test_slug_lowercases_and_dashes(self):
        self.assertEqual(gd.slug("Hello World"), "hello-world")

    def test_slug_strips_special_chars(self):
        self.assertEqual(gd.slug("foo!!! bar"), "foo-bar")

    def test_normalize_mac_dashes(self):
        self.assertEqual(gd.normalize_mac("AA-BB-CC-DD-EE-FF"), "aa:bb:cc:dd:ee:ff")

    def test_normalize_mac_already_normalized(self):
        self.assertEqual(gd.normalize_mac("aa:bb:cc:dd:ee:ff"), "aa:bb:cc:dd:ee:ff")


class TestServiceForHost(unittest.TestCase):
    def test_per_host_override_wins(self):
        config = gd.empty_config()
        config.services[80] = gd.Service(port=80, name="HTTP", group="Web")
        config.host_services["192.168.1.1"] = {
            80: gd.Service(port=80, name="Router UI", group="Infrastructure")
        }
        result = gd.service_for_host("192.168.1.1", "", 80, config)
        self.assertEqual(result.name, "Router UI")
        self.assertEqual(result.group, "Infrastructure")

    def test_falls_back_to_global_service(self):
        config = gd.empty_config()
        config.services[80] = gd.Service(port=80, name="HTTP", group="Web")
        result = gd.service_for_host("192.168.1.1", "", 80, config)
        self.assertEqual(result.name, "HTTP")

    def test_unknown_port_synthesized(self):
        config = gd.empty_config()
        result = gd.service_for_host("1.2.3.4", "", 12345, config)
        self.assertEqual(result.port, 12345)


class TestBuildConfigFromDict(unittest.TestCase):
    def test_subnets_as_string(self):
        cfg = gd.build_config_from_dict({"subnets": "10.0.0.0/24, 10.0.1.0/24"}, "src")
        self.assertEqual(cfg.subnet_values, ("10.0.0.0/24", "10.0.1.0/24"))

    def test_subnets_as_list(self):
        cfg = gd.build_config_from_dict({"subnets": ["10.0.0.0/24"]}, "src")
        self.assertEqual(cfg.subnet_values, ("10.0.0.0/24",))

    def test_bad_subnets_raises(self):
        with self.assertRaises(SystemExit):
            gd.build_config_from_dict({"subnets": 42}, "src")

    def test_host_overrides_register_per_host_services(self):
        data = {"hosts": {"192.168.1.1": {"name": "Router", "services": [{"port": 80, "name": "Router UI"}]}}}
        cfg = gd.build_config_from_dict(data, "src")
        self.assertEqual(cfg.host_names["192.168.1.1"], "Router")
        self.assertIn("192.168.1.1", cfg.host_services)
        self.assertEqual(cfg.host_services["192.168.1.1"][80].name, "Router UI")


class TestRunWatchBackoff(unittest.TestCase):
    def setUp(self):
        # Isolate the run_watch state file (output + ".state.json") to a temp
        # dir so the suite never writes into the working directory.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = str(Path(self.tmp.name) / "x.html")

    def test_interval_doubles_on_failure_and_resets(self):
        sleeps: list[int] = []
        call = {"n": 0}

        def fake_scan(args):
            call["n"] += 1
            # First three calls fail, fourth succeeds, fifth fails.
            if call["n"] in (1, 2, 3, 5):
                raise RuntimeError("boom")
            return mock.Mock(
                hosts=[],
                config=mock.Mock(manual_services=[]),
            )

        def fake_signature(data):
            return ""

        def fake_write_outputs(args, data):
            return False

        def fake_sleep(seconds):
            sleeps.append(seconds)
            # Stop after 5 iterations.
            if len(sleeps) >= 5:
                raise StopIteration

        args = mock.Mock(output=self.out, watch_interval=10)
        with mock.patch.object(gd, "scan_dashboard", fake_scan), \
             mock.patch.object(gd, "dashboard_signature", fake_signature), \
             mock.patch.object(gd, "write_outputs", fake_write_outputs), \
             mock.patch.object(gd.time, "sleep", fake_sleep):
            with self.assertRaises(StopIteration):
                gd.run_watch(args)

        # 1st failure → 20, 2nd → 40, 3rd → 80, 4th success → reset to 10, 5th failure → 20.
        self.assertEqual(sleeps, [20, 40, 80, 10, 20])

    def test_backoff_capped(self):
        sleeps: list[int] = []
        call = {"n": 0}

        def fake_scan(args):
            call["n"] += 1
            raise RuntimeError("boom")

        def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= 6:
                raise StopIteration

        args = mock.Mock(output=self.out, watch_interval=10)
        with mock.patch.object(gd, "scan_dashboard", fake_scan), \
             mock.patch.object(gd.time, "sleep", fake_sleep):
            with self.assertRaises(StopIteration):
                gd.run_watch(args)

        # nominal=10, cap = max(10*8, 60) = 80. Sequence: 20, 40, 80, 80, 80, 80.
        self.assertEqual(sleeps, [20, 40, 80, 80, 80, 80])


if __name__ == "__main__":
    unittest.main()
