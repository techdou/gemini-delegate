import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import agy
import proxy_guard
import run
import update_manager


class ProxyTests(unittest.TestCase):
    def test_default_and_explicit_selection(self):
        self.assertEqual(proxy_guard.select_proxy(env={}), "http://127.0.0.1:7890")
        self.assertEqual(proxy_guard.select_proxy("http://localhost:9000", {"HTTPS_PROXY": "bad"}), "http://localhost:9000")

    def test_no_bypass_or_conflicting_proxy_in_child(self):
        env = proxy_guard.proxy_environment("http://127.0.0.1:7890", {
            "NO_PROXY": "*", "no_proxy": ".googleapis.com", "ALL_PROXY": "socks5://other:1",
            "https_proxy": "http://other:2", "KEEP": "value",
        })
        for key in proxy_guard.PROXY_KEYS:
            self.assertEqual(env[key], "http://127.0.0.1:7890")
        self.assertEqual(env["NO_PROXY"], "")
        self.assertEqual(env["no_proxy"], "")
        self.assertEqual(env["KEEP"], "value")

    def test_invalid_proxies_fail_without_network(self):
        for url in ("", "localhost:7890", "socks5://localhost:7890", "http://localhost:abc", "http://localhost:0", "http://localhost:7890/path"):
            with self.subTest(url=url), patch.object(proxy_guard.socket, "create_connection") as connect:
                with self.assertRaises(proxy_guard.ProxyError):
                    proxy_guard.proxy_environment(url, {})
                connect.assert_not_called()

    def test_dead_proxy_does_not_fall_back(self):
        with patch.object(proxy_guard.socket, "create_connection", side_effect=OSError("closed")), patch.object(proxy_guard, "probe_egress") as probe:
            with self.assertRaises(proxy_guard.ProxyError):
                proxy_guard.prepare_proxy("http://127.0.0.1:7890")
            probe.assert_not_called()

    def test_failed_trace_blocks_launch(self):
        with patch.object(proxy_guard.socket, "create_connection"), patch.object(proxy_guard, "probe_egress", side_effect=proxy_guard.ProxyError("failed")):
            with self.assertRaises(proxy_guard.ProxyError):
                proxy_guard.prepare_proxy("http://127.0.0.1:7890")

    def test_probe_uses_explicit_connect_despite_no_proxy(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.getheader.return_value = None
        conn.getresponse.return_value.read.return_value = b"ip=8.8.8.8\nloc=US\ncolo=SJC\n"
        with patch.dict(os.environ, {"NO_PROXY": "*"}), patch.object(proxy_guard.http.client, "HTTPSConnection", return_value=conn) as factory:
            fields = proxy_guard.probe_egress("http://127.0.0.1:7890")
        self.assertEqual(factory.call_args.args, ("127.0.0.1", 7890))
        conn.set_tunnel.assert_called_once_with("www.cloudflare.com", 443, headers={})
        self.assertEqual(fields["loc"], "US")
        conn.close.assert_called_once()

    def test_invalid_trace_is_rejected(self):
        conn = MagicMock()
        conn.getresponse.return_value.status = 200
        conn.getresponse.return_value.getheader.return_value = None
        conn.getresponse.return_value.read.return_value = b"ip=127.0.0.1\nloc=US\n"
        with patch.object(proxy_guard.http.client, "HTTPSConnection", return_value=conn):
            with self.assertRaises(proxy_guard.ProxyError):
                proxy_guard.probe_egress("http://127.0.0.1:7890")

    def test_credentials_not_in_network_errors(self):
        with patch.object(proxy_guard.socket, "create_connection", side_effect=OSError("closed")):
            with self.assertRaises(proxy_guard.ProxyError) as failure:
                proxy_guard.prepare_proxy("http://secret:password@127.0.0.1:7890")
        self.assertNotIn("password", str(failure.exception))
        self.assertNotIn("secret", str(failure.exception))

    def test_https_redirect_keeps_proxy_and_blocks_http(self):
        conn = MagicMock()
        first, second = MagicMock(), MagicMock()
        first.status = 302
        first.getheader.return_value = "https://other.example/file"
        second.status = 200
        second.getheader.return_value = None
        second.read.return_value = b"ok"
        conn.getresponse.side_effect = [first, second]
        with patch.object(proxy_guard.http.client, "HTTPSConnection", return_value=conn) as factory:
            self.assertEqual(proxy_guard.fetch_https("http://127.0.0.1:7890", "https://example.com", max_bytes=10), b"ok")
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(conn.set_tunnel.call_args.args, ("other.example", 443))
        first.getheader.return_value = "http://example.com/file"
        conn.getresponse.side_effect = [first]
        with patch.object(proxy_guard.http.client, "HTTPSConnection", return_value=conn), self.assertRaises(proxy_guard.ProxyError):
            proxy_guard.fetch_https("http://127.0.0.1:7890", "https://example.com", max_bytes=10)

    def test_update_fetch_uses_same_proxy(self):
        with patch.object(update_manager, "fetch_https", return_value=b"{}") as fetch:
            update_manager.read_source("https://example.com/manifest.json", max_bytes=100, proxy="http://127.0.0.1:9000")
        self.assertEqual(fetch.call_args.args[0], "http://127.0.0.1:9000")


class AgyTests(unittest.TestCase):
    def invoke(self, extra, completed=None, proxy_failure=False):
        env = proxy_guard.proxy_environment("http://127.0.0.1:7890", {"NO_PROXY": "*"})
        kwargs = {"side_effect": proxy_guard.ProxyError("blocked")} if proxy_failure else {"return_value": (env, {"ip": "8.8.8.8", "loc": "US"})}
        with patch.object(sys, "argv", ["agy.py", "--cwd", str(Path(__file__).parent), *extra]), patch.object(agy, "prepare_proxy", **kwargs), patch.object(agy.shutil, "which", return_value="agy.exe"), patch.object(agy.subprocess, "run", return_value=completed) as launch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = agy.main()
        return code, launch

    def test_proxy_failure_never_starts_cli(self):
        code, launch = self.invoke(["--task", "test"], proxy_failure=True)
        self.assertEqual(code, 2)
        launch.assert_not_called()

    def test_eligibility_with_zero_native_exit_is_failure(self):
        code, launch = self.invoke(["--task", "test"], MagicMock(returncode=0, stdout="Eligibility check failed: not currently available in your location", stderr=""))
        self.assertEqual(code, 4)
        self.assertEqual(launch.call_args.kwargs["env"]["NO_PROXY"], "")
        self.assertNotIn("--dangerously-skip-permissions", launch.call_args.args[0])
        self.assertTrue(any(v.startswith("--print=") for v in launch.call_args.args[0]))

    def test_empty_result_is_failure(self):
        code, _ = self.invoke(["--task", "test"], MagicMock(returncode=0, stdout="  ", stderr=""))
        self.assertEqual(code, 1)

    def test_interactive_uses_terminal_and_guard(self):
        code, launch = self.invoke(["--interactive"], MagicMock(returncode=0))
        self.assertEqual(code, 0)
        self.assertNotIn("capture_output", launch.call_args.kwargs)
        self.assertEqual(launch.call_args.kwargs["env"]["NO_PROXY"], "")

    def test_diagnosis_does_not_invent_auth_or_cause(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertTrue(agy.diagnose_eligibility("Eligibility check failed", ""))
        self.assertNotIn("这不是封号", err.getvalue())
        self.assertIn("不能", err.getvalue())

    def test_removed_bypass_options_are_rejected(self):
        for option in ("--allow-no-proxy", "--skip-egress-check"):
            with patch.object(sys, "argv", ["agy.py", "--cwd", ".", "--task", "test", option]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as failure:
                agy.main()
            self.assertEqual(failure.exception.code, 2)


class GeminiTests(unittest.TestCase):
    def test_guard_blocks_all_provider_launch_modes(self):
        for options in (["--task", "test"], ["--probe-model", "flash"], ["--doctor"], ["--doctor", "--dry-run"], ["--probe-model", "flash", "--dry-run"]):
            with patch.object(sys, "argv", ["run.py", *options]), patch.object(run, "prepare_proxy", side_effect=proxy_guard.ProxyError("blocked")), patch.object(run.subprocess, "run") as launch, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run.main(), 2)
            launch.assert_not_called()

    def test_normal_call_receives_guarded_environment(self):
        env = proxy_guard.proxy_environment("http://127.0.0.1:9000", {"NO_PROXY": "*"})
        result = MagicMock(returncode=0, stdout='{"type":"message","role":"assistant","content":"OK"}\n', stderr="")
        with patch.object(sys, "argv", ["run.py", "--task", "test"]), patch.object(run, "prepare_proxy", return_value=(env, {})), patch.object(run, "resolve_cli", return_value="gemini.exe"), patch.object(run, "choose_auth", return_value={"ok": True, "desired_type": "gemini-api-key"}), patch.object(run.subprocess, "run", return_value=result) as launch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run.main(), 0)
        self.assertEqual(launch.call_args.kwargs["env"]["HTTPS_PROXY"], "http://127.0.0.1:9000")
        self.assertEqual(launch.call_args.kwargs["env"]["NO_PROXY"], "")

    def test_model_probe_receives_guarded_environment(self):
        env = proxy_guard.proxy_environment("http://127.0.0.1:9000", {"NO_PROXY": "*"})
        with patch.object(sys, "argv", ["run.py", "--probe-model", "flash"]), patch.object(run, "prepare_proxy", return_value=(env, {})), patch.object(run, "resolve_cli", return_value="gemini.exe"), patch.object(run, "choose_auth", return_value={"ok": True, "desired_type": "gemini-api-key"}), patch.object(run, "probe_model", return_value={"available": True}) as launch, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run.main(), 0)
        self.assertEqual(launch.call_args.kwargs["env"]["HTTPS_PROXY"], "http://127.0.0.1:9000")
        self.assertEqual(launch.call_args.kwargs["env"]["NO_PROXY"], "")

    def test_offline_queries_do_not_probe_network(self):
        for options in (["--auth-status"], ["--list-models"], ["--task", "test", "--dry-run"]):
            with patch.object(sys, "argv", ["run.py", *options]), patch.object(run, "prepare_proxy") as guard, patch.object(run, "choose_auth", return_value={"ok": True, "desired_type": "gemini-api-key"}), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run.main(), 0)
            guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
