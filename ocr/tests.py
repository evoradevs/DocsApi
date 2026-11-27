import json
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from service import Handler, extract


class ExtractionTest(unittest.TestCase):
    @patch("service.run")
    def test_pdf_only_renders_pages_without_text(self, run):
        run.side_effect = ["Pages: 2\n", "Texto sintético\f\f", "", "Página dois"]
        pages = extract(Path("receita.pdf"), "application/pdf")
        self.assertEqual([page["source"] for page in pages], ["pdf_text", "ocr"])
        self.assertEqual(pages[1]["text"], "Página dois")
        self.assertEqual(run.call_count, 4)
        self.assertIn("2", run.call_args_list[2].args[0])

    @patch("service.run", return_value="Receita sintética")
    def test_image_uses_ocr(self, run):
        self.assertEqual(extract(Path("foto.png"), "image/png")[0]["source"], "ocr")
        self.assertEqual(run.call_args.args[0][0], "tesseract")

    @patch("service.run", return_value="Pages: 999\n")
    def test_enforces_page_limit(self, run):
        with self.assertRaisesRegex(ValueError, "páginas"):
            extract(Path("grande.pdf"), "application/pdf")
        run.assert_called_once()

    @patch.dict("os.environ", {"DOCSAPI_TOKEN": "token-sintetico"})
    def test_rejects_missing_or_invalid_token(self):
        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                for route in ("/healthz", "/extract", "/page"):
                    for headers in ({}, {"Authorization": "Bearer incorreto"}):
                        with self.subTest(route=route, headers=headers):
                            data = None if route == "/healthz" else b"synthetic"
                            with self.assertRaises(HTTPError) as error:
                                urlopen(Request(base + route, data=data, headers=headers), timeout=3)
                            self.assertEqual(error.exception.code, 401)
            finally:
                server.shutdown()
                thread.join()

    @patch.dict("os.environ", {"DOCSAPI_TOKEN": "token-sintetico"})
    @patch("service.extract", return_value=[{"page": 1, "source": "ocr", "text": "Sintético"}])
    def test_http_response_and_file_cleanup(self, extract_mock):
        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/extract"
                with urlopen(Request(url, data=b"synthetic", headers={"Content-Type": "image/png", "Authorization": "Bearer token-sintetico"}), timeout=3) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(json.load(response)["pages"][0]["text"], "Sintético")
                self.assertFalse(extract_mock.call_args.args[0].exists())
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(url, data=b"synthetic", headers={"Content-Type": "text/plain", "Authorization": "Bearer token-sintetico"}), timeout=3)
                self.assertEqual(error.exception.code, 415)
                extract_mock.assert_called_once()
            finally:
                server.shutdown()
                thread.join()
