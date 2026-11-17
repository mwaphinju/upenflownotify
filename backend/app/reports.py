def escape_pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def render_lines_pdf(lines: list[str]) -> bytes:
    commands = ["BT", "/F1 11 Tf", "54 770 Td", "14 TL"]
    for line in lines:
        commands.append(f"({escape_pdf_text(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    buffer = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(buffer))
        buffer += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(buffer)
    buffer += f"xref\n0 {len(objects) + 1}\n".encode()
    buffer += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        buffer += f"{offset:010d} 00000 n \n".encode()
    buffer += b"trailer\n"
    buffer += f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    buffer += b"startxref\n"
    buffer += f"{xref_offset}\n".encode()
    buffer += b"%%EOF"
    return bytes(buffer)


def render_kpi_pdf(title: str, kpis: dict) -> bytes:
    lines = [title, ""]
    for key, item in kpis.items():
        label = key.replace("_", " ").title()
        if isinstance(item, dict):
            change = item.get("change_percent")
            change_text = f" ({change:+.1f}% vs previous period)" if change is not None else ""
            lines.append(f"{label}: {item.get('value')}{change_text}")
        else:
            lines.append(f"{label}: {item}")
    return render_lines_pdf(lines)
