"""Example plugin: rewrite HTML <title>

Demonstrates a simple content mutation using the post_asset hook.
Adds a suffix to every <title> element encountered in HTML/HTM pages.
"""
import re

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)

SUFFIX = " • Captured"

def post_asset(rel_path, data, context):
    # Only operate on HTML
    if not rel_path.lower().endswith(('.html', '.htm')):
        return None
    try:
        text = data.decode('utf-8', errors='replace')
    except Exception:
        return None
    def _repl(m):
        inner = m.group(1).strip()
        if inner.endswith(SUFFIX):
            return m.group(0)
        return f"<title>{inner}{SUFFIX}</title>"
    new_text, count = TITLE_RE.subn(_repl, text, count=1)
    if count:
        return new_text
    return None
