from datetime import datetime, timezone
from fpdf import FPDF

# fpdf2 2.8+ renamed X -> XPos, Y -> YPos. Handle both, no crash.
try:
    from fpdf.enums import XPos, YPos, WrapMode
    _NEW_X = XPos.LMARGIN
    _NEW_Y = YPos.NEXT
    _WRAP = WrapMode.CHAR
except Exception:
    try:
        from fpdf.enums import X, Y
        _NEW_X = X.LMARGIN
        _NEW_Y = Y.NEXT
        _WRAP = None
    except Exception:
        _NEW_X = None
        _NEW_Y = None
        _WRAP = None

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _write(pdf: FPDF, h: int, text: str):
    pdf.set_x(pdf.l_margin)
    kwargs = {}
    if _NEW_X is not None:
        kwargs["new_x"] = _NEW_X
        kwargs["new_y"] = _NEW_Y
    if _WRAP is not None:
        kwargs["wrapmode"] = _WRAP
    pdf.multi_cell(0, h, str(text), **kwargs)

def build_pdf_bytes(session: dict, exporter_name: str) -> bytes:
    if not session.get("certified"):
        raise ValueError("BLOCKED: Only CERTIFIED transcript can be exported - Magistrate must certify first")
    if not exporter_name or not exporter_name.strip():
        raise ValueError("Exporter name is required - human must be accountable for export")
    if not session.get("final_text"):
        raise ValueError("BLOCKED: No final certified text found")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 14)
    _write(pdf, 8, "REPUBLIC OF KENYA - THE JUDICIARY")
    pdf.set_font("helvetica", "", 10)
    _write(pdf, 6, "SYNTHETIC DEMO - NO REAL LITIGANTS")
    pdf.ln(4)
    pdf.set_font("helvetica", "B", 11)
    _write(pdf, 6, f"Case: {session['case_number']}")
    pdf.set_font("helvetica", "", 10)
    _write(pdf, 6, f"Clerk: {session.get('clerk')}")
    _write(pdf, 6, f"Certified by: {session.get('magistrate')}")

    hash_val = session.get("final_hash") or ""
    _write(pdf, 6, f"SHA256 Hash: {hash_val[:32]}")
    if len(hash_val) > 32:
        _write(pdf, 6, hash_val[32:])

    pdf.ln(4)
    _write(pdf, 6, session["final_text"])
    pdf.ln(4)
    _write(pdf, 6, f"Exported by HUMAN: {exporter_name.strip()} at {_now()}")

    session["audit_log"].append(
        {"ts": _now(), "actor": exporter_name.strip(), "action": "PDF_EXPORTED", "details": "Certified PDF exported by named human"}
    )
    return bytes(pdf.output())