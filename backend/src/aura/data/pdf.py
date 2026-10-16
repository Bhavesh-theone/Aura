"""A tiny PDF writer for generated placeholder documents (demo data, live demo)."""


def pdf_bytes(title: str, lines: list[str]) -> bytes:
    """A small, valid one-page PDF (Helvetica, WinAnsi) with a title and some lines."""
    def esc(text: str) -> str:
        text = text.replace("₹", "INR ")
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 15 Tf", "56 780 Td", f"({esc(title)}) Tj", "/F1 10 Tf", "0 -26 Td"]
    for line in lines:
        ops += [f"({esc(line)}) Tj", "0 -15 Td"]
    ops.append("ET")
    stream = "\n".join(ops).encode("cp1252", errors="replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, xref))
    return bytes(out)
