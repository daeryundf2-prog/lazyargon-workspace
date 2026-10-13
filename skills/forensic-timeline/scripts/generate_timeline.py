#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_timeline.py
Digital Forensic Interactive Timeline Generator
Generates standalone HTML timeline with search, category filtering, and print-optimized CSS.
"""

import argparse
import html
import json
import sys
from datetime import datetime

# Windows(cp1252/cp949) 콘솔에서 한글 진단 메시지가 UnicodeEncodeError로 죽는 것을 막는다.
# 커밋 e3fa4e6 ("force UTF-8 stdio in all CLI scripts")에서 이 스크립트만 누락되었다.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg-main: #f8fafc;
    --bg-card: #ffffff;
    --text-primary: #0f172a;
    --text-secondary: #475569;
    --border-color: #e2e8f0;
    --primary: #1e3a8a;
    --primary-light: #3b82f6;
    --danger: #dc2626;
    --warning: #d97706;
    --success: #16a34a;
    --accent: #6366f1;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Pretendard", "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
    background-color: var(--bg-main);
    color: var(--text-primary);
    line-height: 1.6;
    padding: 24px;
  }}
  .container {{
    max-width: 1200px;
    margin: 0 auto;
  }}
  header {{
    background: linear-gradient(135deg, #1e3a8a 0%, #1e293b 100%);
    color: #ffffff;
    padding: 32px;
    border-radius: 12px;
    margin-bottom: 24px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  }}
  header h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 8px; }}
  header p {{ font-size: 14px; opacity: 0.9; }}
  .meta-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-top: 20px;
    padding-top: 16px;
    border-top: 1px solid rgba(255, 255, 255, 0.2);
  }}
  .meta-item {{ font-size: 13px; }}
  .meta-label {{ opacity: 0.7; margin-bottom: 2px; }}
  .meta-val {{ font-weight: 600; }}
  
  .controls {{
    background: var(--bg-card);
    padding: 16px 20px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    margin-bottom: 24px;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    justify-content: space-between;
  }}
  .search-box input {{
    padding: 8px 14px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-size: 14px;
    width: 280px;
    outline: none;
  }}
  .search-box input:focus {{
    border-color: var(--primary-light);
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
  }}
  .filter-btns {{
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .btn {{
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: #ffffff;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
  }}
  .btn.active, .btn:hover {{
    background: var(--primary);
    color: #ffffff;
    border-color: var(--primary);
  }}
  
  /* Timeline Layout */
  .timeline {{
    position: relative;
    padding-left: 32px;
  }}
  .timeline::before {{
    content: '';
    position: absolute;
    left: 11px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: #cbd5e1;
  }}
  .timeline-item {{
    position: relative;
    margin-bottom: 20px;
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px 20px;
    transition: transform 0.1s ease, box-shadow 0.1s ease;
  }}
  .timeline-item:hover {{
    transform: translateX(4px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  }}
  .timeline-item::before {{
    content: '';
    position: absolute;
    left: -27px;
    top: 20px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #64748b;
    border: 2px solid #ffffff;
    box-shadow: 0 0 0 2px #cbd5e1;
  }}
  .timeline-item.tag-critical::before {{ background: var(--danger); box-shadow: 0 0 0 2px #fecaca; }}
  .timeline-item.tag-file::before {{ background: var(--primary-light); box-shadow: 0 0 0 2px #bfdbfe; }}
  .timeline-item.tag-web::before {{ background: var(--warning); box-shadow: 0 0 0 2px #fef3c7; }}
  .timeline-item.tag-chat::before {{ background: var(--accent); box-shadow: 0 0 0 2px #e0e7ff; }}
  .timeline-item.tag-system::before {{ background: var(--success); box-shadow: 0 0 0 2px #bbf7d0; }}

  .item-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .item-time {{
    font-size: 15px;
    font-weight: 700;
    color: var(--primary);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }}
  .item-badge {{
    display: inline-block;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
  }}
  .badge-critical {{ background: #fee2e2; color: #991b1b; }}
  .badge-file {{ background: #dbeafe; color: #1e40af; }}
  .badge-web {{ background: #fef3c7; color: #92400e; }}
  .badge-chat {{ background: #ede9fe; color: #5b21b6; }}
  .badge-system {{ background: #dcfce7; color: #166534; }}

  .item-body {{
    font-size: 14px;
    color: var(--text-primary);
  }}
  .item-desc {{
    font-weight: 600;
    margin-bottom: 4px;
  }}
  .item-details {{
    font-size: 13px;
    color: var(--text-secondary);
    background: #f1f5f9;
    padding: 8px 12px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    word-break: break-all;
    margin-top: 6px;
  }}

  @media print {{
    body {{ background: #ffffff; padding: 0; }}
    .controls {{ display: none; }}
    header {{ background: #1e293b; color: #ffffff; padding: 20px; }}
    .timeline-item {{ break-inside: avoid; border: 1px solid #cbd5e1; }}
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>{title}</h1>
    <p>입력 JSON을 시각화한 타임라인. 원본 아티팩트를 대체하지 않으며, 미입력 시 샘플 증거를 생성하지 않는다.</p>
    <div class="meta-grid">
      <div class="meta-item"><div class="meta-label">분석 대상</div><div class="meta-val">{target}</div></div>
      <div class="meta-item"><div class="meta-label">생성 일시</div><div class="meta-val">{analyzed_at}</div></div>
      <div class="meta-item"><div class="meta-label">총 이벤트 건수</div><div class="meta-val">{total_events} 건</div></div>
      <div class="meta-item"><div class="meta-label">타임존</div><div class="meta-val">{timezone}</div></div>
      <div class="meta-item"><div class="meta-label">정렬</div><div class="meta-val">{ordering}</div></div>
    </div>
  </header>

  <div class="controls">
    <div class="search-box">
      <input type="text" id="searchInput" placeholder="키워드/파일명/행위 검색..." onkeyup="filterTimeline()">
    </div>
    <div class="filter-btns">
      <button class="btn active" onclick="setCategory('all', this)">전체</button>
      <button class="btn" onclick="setCategory('critical', this)">주의</button>
      <button class="btn" onclick="setCategory('file', this)">📁 파일 행위</button>
      <button class="btn" onclick="setCategory('web', this)">🌐 웹/검색</button>
      <button class="btn" onclick="setCategory('chat', this)">💬 메신저/대화</button>
      <button class="btn" onclick="setCategory('system', this)">⚙️ 시스템</button>
    </div>
  </div>

  <div class="timeline" id="timelineList">
    {timeline_items}
  </div>
</div>

<script>
let currentCategory = 'all';

function setCategory(cat, btn) {{
  currentCategory = cat;
  document.querySelectorAll('.filter-btns .btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  filterTimeline();
}}

function filterTimeline() {{
  const query = document.getElementById('searchInput').value.toLowerCase();
  const items = document.querySelectorAll('.timeline-item');
  
  items.forEach(item => {{
    const cat = item.getAttribute('data-category');
    const text = item.innerText.toLowerCase();
    
    const matchesCat = (currentCategory === 'all' || cat === currentCategory);
    const matchesQuery = text.includes(query);
    
    if (matchesCat && matchesQuery) {{
      item.style.display = 'block';
    }} else {{
      item.style.display = 'none';
    }}
  }});
}}
</script>
</body>
</html>
"""

def escape_text(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


DEFAULT_MAX_EVENTS = 10000


def load_events(path, max_events=DEFAULT_MAX_EVENTS):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("input JSON must be a list of event objects")
    if len(data) > max_events:
        raise ValueError(f"too many events: {len(data)} > {max_events} (split input or use --max-events)")
    events = []
    for i, ev in enumerate(data):
        if not isinstance(ev, dict):
            raise ValueError(f"event[{i}] must be an object")
        # Guard: details length cap 2KB to prevent HTML DoS via huge field
        if isinstance(ev.get("details"), str) and len(ev["details"]) > 2048:
            ev = dict(ev)
            ev["details"] = ev["details"][:2048] + " …(truncated 2KB)"
        events.append(ev)
    return events


def order_events(events):
    parsed = []
    awareness = None
    for ev in events:
        raw = ev.get("timestamp")
        if not isinstance(raw, str) or not raw.strip():
            return list(events), "입력 순서 (시각 누락/형식 불명)"
        try:
            value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return list(events), "입력 순서 (시각 형식 불명)"
        current_awareness = value.tzinfo is not None
        if awareness is None:
            awareness = current_awareness
        elif awareness != current_awareness:
            return list(events), "입력 순서 (타임존 표기 혼합)"
        parsed.append((value, ev))
    return [ev for _, ev in sorted(parsed, key=lambda item: item[0])], "시각 오름차순"


def generate_html(
    events,
    title="디지털포렌식 시계열 타임라인",
    target="피분석 기기 / 저장매체",
    timezone_label="as provided (not converted)",
):
    items_html = []
    ordered_events, ordering = order_events(events)
    category_map = {
        "critical": ("tag-critical", "badge-critical", "주의"),
        "file": ("tag-file", "badge-file", "파일행위"),
        "web": ("tag-web", "badge-web", "웹/검색"),
        "chat": ("tag-chat", "badge-chat", "메신저"),
        "system": ("tag-system", "badge-system", "시스템"),
    }

    for ev in ordered_events:
        cat = str(ev.get("category", "file")).lower()
        if cat not in category_map:
            cat = "file"
        tag_cls, badge_cls, badge_label = category_map[cat]
        time_str = escape_text(ev.get("timestamp", "-"))
        desc = escape_text(ev.get("description", ""))
        details = escape_text(ev.get("details", ""))
        safe_cat = escape_text(cat)

        detail_html = f'<div class="item-details">{details}</div>' if details else ""

        item = f"""
        <div class="timeline-item {tag_cls}" data-category="{safe_cat}">
          <div class="item-header">
            <span class="item-time">{time_str}</span>
            <span class="item-badge {badge_cls}">{badge_label}</span>
          </div>
          <div class="item-body">
            <div class="item-desc">{desc}</div>
            {detail_html}
          </div>
        </div>
        """
        items_html.append(item)

    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    return HTML_TEMPLATE.format(
        title=escape_text(title),
        target=escape_text(target),
        analyzed_at=escape_text(now_str),
        timezone=escape_text(timezone_label),
        ordering=escape_text(ordering),
        total_events=len(events),
        timeline_items="\n".join(items_html),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Forensic Timeline HTML Generator")
    parser.add_argument("--input", default=None, help="Input JSON file containing an events list")
    parser.add_argument("--output", default="timeline_report.html", help="Output HTML path")
    parser.add_argument("--title", default="디지털포렌식 시계열 타임라인", help="Report title")
    parser.add_argument("--target", default="피분석 저장매체 (PC/Mobile)", help="Target device")
    parser.add_argument(
        "--max-events",
        type=int,
        default=DEFAULT_MAX_EVENTS,
        help="Maximum number of events accepted in one input file (default: %(default)s)",
    )
    parser.add_argument(
        "--timezone",
        default="as provided (not converted)",
        help="Label only. This tool does not convert timestamps.",
    )
    args = parser.parse_args(argv)
    if not args.input:
        print("[-] --input is required. Refusing to emit sample evidence.", file=sys.stderr)
        return 2

    try:
        events_data = load_events(args.input, max_events=max(1, args.max_events))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[-] Failed to load events: {exc}", file=sys.stderr)
        return 2

    html_out = generate_html(
        events_data,
        title=args.title,
        target=args.target,
        timezone_label=args.timezone,
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"[+] Timeline HTML written: {args.output} ({len(events_data)} events)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
