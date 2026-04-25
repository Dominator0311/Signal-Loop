"""
Convert patient-document markdown files to PDFs for Prompt Opinion upload.

Prompt Opinion's per-patient Documents tab accepts PDF uploads. This script
converts clinical document markdowns in this folder (consult notes, discharge
summaries, etc.) into styled PDFs ready to drop into the Documents tab.

Uses Chrome headless — same pattern as agent-config/_convert_to_pdf.py.

Usage:
    cd fhir-bundles/patient-documents
    python _convert_to_pdf.py

Requires the `markdown` package (pip install markdown). Chrome must be at the
path below on macOS.
"""

import subprocess
import tempfile
from pathlib import Path

import markdown


CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 820px;
    margin: 40px auto;
    padding: 20px;
    line-height: 1.55;
    color: #1a1a1a;
  }}
  h1 {{ font-size: 22pt; border-bottom: 2px solid #333; padding-bottom: 8px; margin-bottom: 4px; }}
  h2 {{ font-size: 14pt; margin-top: 20px; color: #222; }}
  h3 {{ font-size: 12pt; color: #333; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: auto; }}
  th, td {{ border: 1px solid #bbb; padding: 6px 12px; text-align: left; }}
  th {{ background: #f3f3f3; }}
  code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
  blockquote {{ border-left: 3px solid #888; padding-left: 10px; color: #555; margin: 12px 0; }}
  li {{ margin: 4px 0; }}
  hr {{ border: 0; border-top: 1px solid #ccc; margin: 20px 0; }}
  strong {{ color: #000; }}
  @page {{ size: A4; margin: 2cm; }}
</style>
</head>
<body>
{content}
</body>
</html>
"""


def convert_file(md_path: Path, output_dir: Path) -> Path:
    """Convert one markdown file to PDF. Returns PDF path."""
    md_text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
    )
    full_html = HTML_TEMPLATE.format(title=md_path.stem, content=html_body)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(full_html)
        tmp_html_path = Path(tmp.name)

    pdf_path = output_dir / f"{md_path.stem}.pdf"

    try:
        subprocess.run(
            [
                CHROME_PATH,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--print-to-pdf={pdf_path}",
                "--print-to-pdf-no-header",
                f"file://{tmp_html_path}",
            ],
            check=True,
            capture_output=True,
        )
    finally:
        tmp_html_path.unlink(missing_ok=True)

    return pdf_path


if __name__ == "__main__":
    docs_dir = Path(__file__).parent
    md_files = sorted(p for p in docs_dir.glob("*.md") if not p.name.startswith("_"))

    if not md_files:
        print("No markdown files to convert.")
        raise SystemExit(0)

    print(f"Converting {len(md_files)} patient document(s) to PDF...")
    for md_path in md_files:
        pdf_path = convert_file(md_path, docs_dir)
        size_kb = pdf_path.stat().st_size / 1024
        print(f"  {md_path.name} → {pdf_path.name} ({size_kb:.1f} KB)")
    print(f"\nDone. Upload PDFs to patient Documents tab in Prompt Opinion.")
