import asyncio
import datetime as dt
import ssl
import unittest

import aiohttp
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pasture import cli, tls

from .helpers import TempDir

HOST = "box.example.ts.net"


class TlsTest(TempDir, unittest.IsolatedAsyncioTestCase):
    def test_ca_signs_one_name(self):
        p = tls.init(self.tmp, HOST)
        ca = x509.load_pem_x509_certificate(p["ca"].read_bytes())
        leaf = x509.load_pem_x509_certificate(p["cert"].read_bytes())  # first PEM block
        constraints = ca.extensions.get_extension_for_class(x509.NameConstraints)
        self.assertTrue(constraints.critical)
        self.assertEqual([n.value for n in constraints.value.permitted_subtrees], [HOST])
        self.assertEqual(leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName), [HOST])
        ca.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes, ec.ECDSA(leaf.signature_hash_algorithm))
        days = (leaf.not_valid_after_utc - dt.datetime.now(dt.timezone.utc)).days
        self.assertTrue(790 <= days <= 800)

    def test_renew_keeps_the_ca_and_refuses_another_host(self):
        p = tls.init(self.tmp, HOST)
        ca, cert = p["ca"].read_bytes(), p["cert"].read_bytes()
        tls.init(self.tmp, HOST)
        self.assertEqual(p["cert"].read_bytes(), cert)  # nothing to do
        tls.init(self.tmp, HOST, renew=True)
        self.assertEqual(p["ca"].read_bytes(), ca)
        self.assertNotEqual(p["cert"].read_bytes(), cert)
        with self.assertRaises(ValueError):
            tls.init(self.tmp, "other.example.ts.net")

    def test_phone_page_and_certificate(self):
        import threading
        import urllib.request

        p = tls.init(self.tmp, HOST)
        server = cli.phone_server(self.tmp, HOST, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(base + "/") as r:
                self.assertIn(f"https://{HOST}/", r.read().decode())
            with urllib.request.urlopen(base + "/pasture-ca.cer") as r:
                self.assertEqual(r.headers["Content-Type"], "application/x-x509-ca-cert")
                self.assertEqual(x509.load_der_x509_certificate(r.read()), x509.load_pem_x509_certificate(p["ca"].read_bytes()))
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_init(self):
        cli.main(["tls", "init", "--host", HOST, "--state", str(self.tmp)])
        self.assertTrue((self.tmp / "tls" / "key.pem").exists())

    async def serve(self, cert_pem: bytes, key_pem: bytes) -> tuple[web.AppRunner, int]:
        (self.tmp / "srv.pem").write_bytes(cert_pem)
        (self.tmp / "srv.key").write_bytes(key_pem)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.tmp / "srv.pem", self.tmp / "srv.key")
        app = web.Application()
        app.router.add_get("/", lambda r: web.Response(text="ok"))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=ctx)
        await site.start()
        self.addAsyncCleanup(runner.cleanup)
        return runner, site._server.sockets[0].getsockname()[1]

    async def test_a_client_that_trusts_only_the_ca_connects(self):
        p = tls.init(self.tmp, HOST)
        _, port = await self.serve(p["cert"].read_bytes(), p["key"].read_bytes())
        client = ssl.create_default_context(cafile=str(p["ca"]))
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://127.0.0.1:{port}/", ssl=client, server_hostname=HOST) as r:
                self.assertEqual(await r.text(), "ok")

    async def test_the_ca_cannot_vouch_for_other_names(self):
        p = tls.init(self.tmp, HOST)
        # Even with the CA key, a certificate for another name fails the name constraint.
        ca = x509.load_pem_x509_certificate(p["ca"].read_bytes())
        ca_key = serialization.load_pem_private_key(p["ca_key"].read_bytes(), None)
        key, cert = tls.make_leaf("other.example.ts.net", ca_key, ca, dt.datetime.now(dt.timezone.utc))
        _, port = await self.serve(cert.public_bytes(serialization.Encoding.PEM), tls._key_pem(key))
        asyncio.get_running_loop().set_exception_handler(lambda loop, ctx: None)  # the refused handshake
        client = ssl.create_default_context(cafile=str(p["ca"]))
        async with aiohttp.ClientSession() as s:
            with self.assertRaises(aiohttp.ClientConnectorCertificateError) as e:
                await s.get(f"https://127.0.0.1:{port}/", ssl=client, server_hostname="other.example.ts.net")
        self.assertIn("subtree", str(e.exception).lower())  # OpenSSL: "permitted subtree violation"
