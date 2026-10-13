#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_infographic.py
Renders AntV Infographic DSL into a standalone interactive HTML/SVG visualization.
Supports legal/forensic themes, responsive containers, and SVG export.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<script src="{script_src}"></script>
<style>
  :root {{
    --bg-main: #f8fafc;
    --bg-card: #ffffff;
    --border: #e2e8f0;
    --primary: #1e3a8a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
    background-color: var(--bg-main);
    color: #0f172a;
    padding: 24px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }}
  .header {{
    max-width: 1200px;
    width: 100%;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #ffffff;
    padding: 16px 24px;
    border-radius: 8px;
    border: 1px solid var(--border);
  }}
  .header h1 {{ font-size: 20px; font-weight: 700; color: var(--primary); }}
  .badge {{ font-size: 12px; background: #e0e7ff; color: #3730a3; padding: 4px 10px; border-radius: 9999px; font-weight: 600; }}
  #container {{
    max-width: 1200px;
    width: 100%;
    min-height: 650px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    display: flex;
    justify-content: center;
    align-items: center;
  }}
  .controls {{
    margin-top: 16px;
    display: flex;
    gap: 8px;
  }}
  .btn {{
    padding: 8px 16px;
    background: var(--primary);
    color: #ffffff;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }}
  .btn:hover {{ opacity: 0.9; }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <span class="badge">AntV Infographic Visualizer</span>
</div>

<div id="container"></div>

<div class="controls">
  <button class="btn" onclick="window.print()">🖨️ 인쇄 / PDF 저장</button>
</div>

<script>
const dslContent = {dsl_escaped};

try {{
  const infographic = new AntVInfographic.Infographic({{
    container: '#container',
    width: '100%',
    height: '100%',
    editable: true,
  }});
  infographic.render(dslContent);
}} catch (err) {{
  console.error("Render failed:", err);
  document.getElementById('container').innerHTML = '<div style="color:red;padding:20px;">인포그래픽 렌더링 오류: ' + err.message + '</div>';
}}
</script>
</body>
</html>
"""


def validate_script_source(source: str) -> str:
    candidate = Path(source)
    if candidate.is_file():
        return candidate.resolve().as_uri()
    parsed = urlparse(source)
    if parsed.scheme == "https" and parsed.netloc:
        return source
    raise ValueError("--antv-script must be an existing local file or an explicit HTTPS URL")


def render_infographic_html(
    dsl_text: str,
    output_path: str,
    script_source: str,
    title: str = "디지털포렌식 시각화 인포그래픽",
) -> str:
    dsl_escaped = (
        json.dumps(dsl_text, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    html_text = HTML_TEMPLATE.format(
        title=html.escape(title, quote=True),
        script_src=html.escape(validate_script_source(script_source), quote=True),
        dsl_escaped=dsl_escaped,
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="AntV Infographic Standalone HTML Renderer")
    parser.add_argument("input", nargs="?", help="Input .infographic file")
    parser.add_argument("--output", default="infographic_preview.html", help="Output HTML file path")
    parser.add_argument("--title", default="포렌식 분석 인포그래픽", help="Infographic title")
    parser.add_argument(
        "--antv-script",
        help="Existing local AntV bundle or explicit version-pinned HTTPS URL.",
    )
    args = parser.parse_args(argv)

    if not args.input:
        print("[-] input .infographic file is required; refusing to emit sample evidence", file=sys.stderr)
        return 2
    if not args.antv_script:
        print("[-] --antv-script is required; use a reviewed local bundle or pinned HTTPS URL", file=sys.stderr)
        return 2

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"[-] input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        dsl = input_path.read_text(encoding="utf-8")
        out_file = render_infographic_html(
            dsl,
            args.output,
            script_source=args.antv_script,
            title=args.title,
        )
    except (OSError, ValueError) as exc:
        print(f"[-] infographic render setup failed: {exc}", file=sys.stderr)
        return 2
    print(f"[+] Infographic HTML successfully generated: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
