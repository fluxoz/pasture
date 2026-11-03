import contextlib
import hashlib
import io
import os
import unittest
from unittest import mock

from pasture import cli
from pasture.config import load

from .helpers import TempDir


class CliTest(TempDir, unittest.TestCase):
    def test_token_is_kept_until_used_then_renewed(self):
        first = cli.fresh_token(self.tmp)
        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(cli.fresh_token(self.tmp), first)
        self.assertEqual(oct((self.tmp / "enroll-token").stat().st_mode & 0o777), "0o600")
        (self.tmp / "token-consumed").write_text(hashlib.sha256(first.encode()).hexdigest() + "\n")
        second = cli.fresh_token(self.tmp)
        self.assertNotEqual(second, first)
        self.assertNotEqual(cli.fresh_token(self.tmp, renew=True), second)

    def test_enroll_prints_the_link(self):
        out = io.StringIO()
        with mock.patch("shutil.which", return_value=None), contextlib.redirect_stdout(out):
            cli.main(["enroll", "--host", "box.example.ts.net", "--state", str(self.tmp)])
        token = (self.tmp / "enroll-token").read_text().strip()
        self.assertIn(f"https://box.example.ts.net/enroll#t={token}", out.getvalue())

    def test_bare_command_means_serve(self):
        with mock.patch.object(cli, "cmd_serve") as serve:
            cli.main(["--host", "h.example", "--no-tailscale-serve"])
        args = serve.call_args[0][0]
        self.assertEqual((args.cmd, args.host, args.no_tailscale_serve), ("serve", "h.example", True))

    def test_gateway_keeps_its_own_secrets(self):
        env = {"PASTURE_HOST": "h.example", "PASTURE_STATE_DIR": str(self.tmp / "state")}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = load()
            key = cfg.session_key_file.read_bytes()
            self.assertEqual(len(key), 48)
            self.assertEqual(load().session_key_file.read_bytes(), key)  # kept across restarts
            self.assertGreaterEqual(len(cfg.enroll_token_file.read_bytes()), 40)
            self.assertIsNone(cfg.credentials_file)
