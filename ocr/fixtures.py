"""Gera receitas sintéticas e mede a extração HTTP dentro do container."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

IDENTIDADE = ["Paciente: Paciente Ficticio", "Prescritor: Prescritor Ficticio", "CRM-SP 123456"]
ITEM = ["Medicamento: Produto Alfa 10 mg", "Quantidade: 2"]


def pdf(pages, italic=False):
    font = "Times-Italic" if italic else "Helvetica"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(pages)} /Kids [".encode()
        + b" ".join(f"{4 + i * 2} 0 R".encode() for i in range(len(pages))) + b"] >>",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{font} >>".encode(),
    ]
    for index, lines in enumerate(pages):
        contents = b"BT /F1 20 Tf " + b" ".join(
            f"1 {0.06 * ((i % 3) - 1) if italic else 0} 0 1 45 {705 - 38*i} Tm ({line}) Tj".encode()
            for i, line in enumerate(lines)) + b" ET"
        objects.extend([
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {5 + index * 2} 0 R >>".encode(),
            f"<< /Length {len(contents)} >>\nstream\n".encode() + contents + b"\nendstream",
        ])

    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    tail = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        body.extend(f"{off:010d} 00000 n \n".encode())
    body.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{tail}\n%%EOF\n".encode())
    return bytes(body)


def raster(data):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "synthetic.pdf"
        path.write_bytes(data)
        prefix = path.with_suffix("")
        subprocess.run(["pdftoppm", "-singlefile", "-scale-to", "1500", "-png", str(path), str(prefix)], check=True)
        return prefix.with_suffix(".png").read_bytes()


def request(route, data, mime, **headers):
    req = Request("http://127.0.0.1:8080/" + route, data=data, headers={"Content-Type": mime, "Authorization": "Bearer " + os.environ["DOCSAPI_TOKEN"], **headers})
    begin = time.perf_counter()
    with urlopen(req, timeout=35) as response:
        result = response.read()
        took = round((time.perf_counter() - begin) * 1000)
        return result, took


def main():
    native = pdf([IDENTIDADE + ITEM])
    cropped, elapsed = request("page", native, "application/pdf", **{"X-OCR-Page": "1"})
    assert cropped.startswith(b"\x89PNG\r\n\x1a\n")
    docs = [
        ("pdf_texto", native, "application/pdf"),
        ("foto_simulada", raster(native), "image/png"),
        ("manuscrito_simulado", raster(pdf([["Paciente: Paci?nte"] + IDENTIDADE[1:] + ITEM[:1]], italic=True)), "image/png"),
        ("pdf_varias_paginas", pdf([IDENTIDADE, ITEM]), "application/pdf"),
        ("pdf_caractere_ambiguo", pdf([IDENTIDADE + ["Medicamento: Produto A1fa 10 mg", ITEM[1]]]), "application/pdf"),
        ("pdf_revisao", pdf([IDENTIDADE, ["Medicamento: Produto Zeta 10 mg", ITEM[1]]]), "application/pdf"),
    ]
    out = []
    for name, data, mime in docs:
        body, total = request("extract", data, mime)
        out.append({"id": name, "mime": mime, "httpMs": total, **json.loads(body)})
    print(json.dumps({"pageMs": elapsed, "documents": out}))


if __name__ == "__main__":
    main()
