"""Inject a dark theme into embedded HTML reports so they align with the dashboard UI."""

from __future__ import annotations

import re

# Matches frontend :root in frontend/src/index.css
_THEME_STYLE = """<style id="rttd-dashboard-theme">
html{background:#0b1020!important;}
body{background:#0b1020!important;color:#e7ecf6!important;font-family:Inter,system-ui,sans-serif!important;}
</style>"""


def inject_dashboard_theme(html: str) -> str:
    if not html or not html.strip():
        return html
    if 'rttd-dashboard-theme' in html:
        return html
    if re.search(r'<head[^>]*>', html, flags=re.IGNORECASE):
        return re.sub(
            r'(<head[^>]*>)',
            r'\1' + _THEME_STYLE,
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    return _THEME_STYLE + html


def inject_dashboard_theme_bytes(body: bytes, mime: str) -> bytes:
    if not mime.startswith('text/html'):
        return body
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError:
        return body
    return inject_dashboard_theme(text).encode('utf-8')
