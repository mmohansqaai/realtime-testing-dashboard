"""Inject a light BayOne-aligned theme into embedded HTML reports."""

from __future__ import annotations

import re

# Matches the dashboard light palette (purple wash, dark text).
_THEME_STYLE = """<style id="rttd-dashboard-theme">
:root, html, html.dark, html.dark-mode, [data-color-mode="dark"] {
  color-scheme: light !important;
  --color-canvas-default: #f6f0fb !important;
  --color-canvas-subtle: #efe6f8 !important;
  --color-fg-default: #1b1328 !important;
  --color-fg-muted: #5c5470 !important;
  --color-border-default: #e0d4ef !important;
  --color-accent-fg: #7b2cbf !important;
  --color-pretty-paths: #7b2cbf !important;
}
html, body {
  background: #f6f0fb !important;
  color: #1b1328 !important;
  color-scheme: light !important;
}
input, textarea, select {
  background: #ffffff !important;
  color: #1b1328 !important;
  border-color: #e0d4ef !important;
}
@media (prefers-color-scheme: dark) {
  :root, html, body {
    color-scheme: light !important;
    background: #f6f0fb !important;
    color: #1b1328 !important;
    --color-canvas-default: #f6f0fb !important;
    --color-fg-default: #1b1328 !important;
  }
}
</style>
<script id="rttd-dashboard-theme-js">
(function () {
  try { localStorage.setItem('playwright-report-color-scheme', 'light'); } catch (e) {}
  var root = document.documentElement;
  root.classList.remove('dark', 'dark-mode');
  root.dataset.colorMode = 'light';
  root.style.colorScheme = 'light';
})();
</script>"""


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
