"""
Convert markdown content collection files to PDFs.

Prompt Opinion's content collection UI accepts PDF only (application/pdf).
This script converts each .md file in content-collection/ to a styled PDF
using Chrome headless.

Steps:
  1. Read markdown, convert to HTML with basic styling
  2. Write HTML to temp file
  3. Invoke Chrome headless --print-to-pdf to produce PDF
  4. Clean up temp HTML

Output PDFs are saved alongside the markdown files.
"""

import shutil
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
  h1 {{ font-size: 24pt; border-bottom: 2px solid #333; padding-bottom: 8px; }}
  h2 {{ font-size: 18pt; margin-top: 24px; color: #222; }}
  h3 {{ font-size: 14pt; color: #333; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; }}
  th, td {{ border: 1px solid #bbb; padding: 8px 10px; text-align: left; }}
  th {{ background: #f3f3f3; }}
  code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }}
  blockquote {{ border-left: 3px solid #888; padding-left: 10px; color: #555; margin: 12px 0; }}
  li {{ margin: 4px 0; }}
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
        extensions=["tables", "fenced_code", "toc"],
    )
    full_html = HTML_TEMPLATE.format(title=md_path.stem, content=html_body)

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(full_html)
        tmp_html_path = Path(tmp.name)

    pdf_path = output_dir / f"{md_path.stem}.pdf"

    try:
        # Chrome headless print-to-pdf
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
    content_dir = Path(__file__).parent / "content-collection"
    output_dir = content_dir / "_pdf"
    output_dir.mkdir(exist_ok=True)

    md_files = sorted(content_dir.glob("*.md"))
    print(f"Converting {len(md_files)} markdown files to PDF...")

    for md_path in md_files:
        pdf_path = convert_file(md_path, output_dir)
        size_kb = pdf_path.stat().st_size / 1024
        print(f"  {md_path.name} → {pdf_path.name} ({size_kb:.1f} KB)")

    print(f"\nDone. PDFs in: {output_dir}")
