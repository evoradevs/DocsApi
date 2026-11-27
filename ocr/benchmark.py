"""Pipe this file to Python inside the running OCR container."""
import json
import os
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

EXPECTED = "RECEITA SINTETICA"


def synthetic_pdf():
    stream = b"BT /F1 36 Tf 50 660 Td (RECEITA SINTETICA) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    table_offset = len(document)
    document.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{table_offset}\n%%EOF\n".encode())
    return bytes(document)


def measure(mime, body, source):
    values = []
    for _ in range(10):
        request = Request("http://127.0.0.1:8080/extract", data=body, headers={"Content-Type": mime, "Authorization": "Bearer " + os.environ["DOCSAPI_TOKEN"]})
        start = time.perf_counter()
        with urlopen(request, timeout=35) as response:
            result = json.load(response)
        values.append((time.perf_counter() - start) * 1000)
        page, = result["pages"]
        assert page["source"] == source and EXPECTED in page["text"], page
    print(json.dumps({"source": source, "trials": len(values),
                      "medianMs": round(statistics.median(values)), "maxMs": round(max(values))}))


if __name__ == "__main__":
    pdf = synthetic_pdf()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "synthetic.pdf"
        path.write_bytes(pdf)
        prefix = path.with_suffix("")
        subprocess.run(["pdftoppm", "-singlefile", "-scale-to", "1200", "-png",
                        str(path), str(prefix)], check=True)
        measure("application/pdf", pdf, "pdf_text")
        measure("image/png", prefix.with_suffix(".png").read_bytes(), "ocr")
