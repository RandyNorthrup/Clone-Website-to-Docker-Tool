"""Example plugin: inject a disclosure banner

Inserts a small banner immediately after the opening <body> tag in HTML pages.
Illustrates safe string insertion logic.
"""
import re

BODY_OPEN_RE = re.compile(r"<body[^>]*>", re.IGNORECASE)
BANNER_HTML = "<div style='background:#222;color:#fff;padding:6px 10px;font:12px/1.4 sans-serif'>Offline Archive Export</div>"


def post_asset(rel_path, data, context):
    if not rel_path.lower().endswith(('.html', '.htm')):
        return None
    try:
        text = data.decode('utf-8', errors='replace')
    except Exception:
        return None
    m = BODY_OPEN_RE.search(text)
    if not m:
        return None
    # Insert banner after the matched opening body tag
    idx = m.end()
    return text[:idx] + BANNER_HTML + text[idx:]
