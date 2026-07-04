"""PDF -> text -> retrieve (skips if reportlab/pypdf not installed)."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_pdf():
    try:
        from reportlab.pdfgen import canvas
        from trl.retrieval import build_pdf_index, retrieve_text
    except Exception as e:
        print("SKIP pdf test (deps missing):", e); return
    d = tempfile.mkdtemp(); pdf = os.path.join(d, "p.pdf")
    c = canvas.Canvas(pdf); y = 800
    for ln in ["Handbook", "", "Shipping: free-shipping threshold is 75 dollars.", "",
               "Security: lockout after 5 failed logins.", ""]:
        c.drawString(72, y, ln); y -= 24
    c.showPage(); c.save()
    idx = build_pdf_index([pdf])
    r = retrieve_text(idx, "free shipping minimum?", token_budget=120, k=1, rerank=False)
    assert "75" in r["context"], "PDF retrieval missed the passage"
    print("pdf OK")

if __name__ == "__main__":
    test_pdf(); print("PDF TEST PASSED")
