import hmac
import json
import os
import re
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 10
MAX_TEXT_PER_PAGE = 12_000
TIMEOUT = 25
TYPES = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


def run(args, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(args, TIMEOUT)
    return subprocess.run(
        args, timeout=remaining, check=True, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        env={**os.environ, "LC_ALL": "C.UTF-8", "OMP_THREAD_LIMIT": "1"},
    ).stdout


def read_image(path, deadline):
    return run(["tesseract", str(path), "stdout", "-l", "por"], deadline).strip()


def render_page(path, page, deadline):
    prefix = path.with_name("render")
    run(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
         "-scale-to", "1800", "-png", str(path), str(prefix)], deadline)
    return prefix.with_suffix(".png")


def pdf_page_count(path, deadline):
    info = run(["pdfinfo", str(path)], deadline)
    match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    count = int(match[1]) if match else 0
    if not 1 <= count <= MAX_PAGES:
        raise ValueError("O PDF precisa ter de 1 a 10 páginas.")

    return count


def extract(path, mime):
    deadline = time.monotonic() + TIMEOUT
    if mime != "application/pdf":
        text = read_image(path, deadline)
        if len(text) > MAX_TEXT_PER_PAGE:
            raise ValueError('Texto da página acima do limite.')
        return [{"page": 1, "source": "ocr", "text": text}]

    count = pdf_page_count(path, deadline)
    texts = run(["pdftotext", "-layout", str(path), "-"], deadline).split("\f")
    pages = []
    for page in range(1, count + 1):
        text = texts[page - 1].strip() if page <= len(texts) else ""
        source = "pdf_text"
        if not text:
            text = read_image(render_page(path, page, deadline), deadline)
            source = "ocr"
        if len(text) > MAX_TEXT_PER_PAGE:
            raise ValueError('Texto da página acima do limite.')
        pages.append({"page": page, "source": source, "text": text})
    return pages


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(8)
        super().setup()

    def log_message(self, fmt, *args):
        # A requisição contém dados da receita.
        pass

    def reply(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        token = os.environ.get("DOCSAPI_TOKEN")
        supplied = self.headers.get("Authorization", "").encode("utf-8")
        if token and hmac.compare_digest(supplied, f"Bearer {token}".encode("utf-8")):
            return True
        self.reply(401, {"error": "Token ausente ou inválido."})
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/healthz":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "Rota não encontrada."})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in ("/extract", "/page"):
            return self.reply(404, {"error": "Rota não encontrada."})
        mime = self.headers.get_content_type()
        if mime not in TYPES or (self.path == '/page' and mime != 'application/pdf'):
            return self.reply(415, {"error": "Formato incompatível com esta operação."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, {"error": "Tamanho inválido."})
        if not 1 <= length <= MAX_BYTES:
            return self.reply(413, {"error": "O arquivo precisa ter até 8 MiB."})
        try:
            body = self.rfile.read(length)
        except TimeoutError:
            return self.reply(408, {"error": "Envio do arquivo demorou demais."})
        if len(body) != length:
            return self.reply(400, {"error": "Arquivo incompleto."})

        try:
            start = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="ocr-") as temp:
                path = Path(temp) / ("entrada" + TYPES[mime])
                path.write_bytes(body)
                if self.path == '/page':
                    page = int(self.headers.get('X-OCR-Page', '0'))
                    if not 1 <= page <= pdf_page_count(path, start + TIMEOUT):
                        raise ValueError('Página inválida.')
                    image = render_page(path, page, start + TIMEOUT).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/png')
                    self.send_header('Content-Length', str(len(image)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(image)
                    return
                pages = extract(path, mime)
        except subprocess.TimeoutExpired:
            return self.reply(504, {"error": "A extração demorou demais."})
        except ValueError as error:
            return self.reply(422, {"error": str(error)})
        except (subprocess.CalledProcessError, FileNotFoundError):
            return self.reply(422, {"error": "Não foi possível ler o arquivo."})
        self.reply(200, {"pages": pages, "elapsedMs": round((time.monotonic() - start) * 1000)})


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
