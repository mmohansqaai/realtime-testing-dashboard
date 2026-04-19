"""Inject dashboard-matching light theme into embedded HTML reports (e.g. Playwright HTML reporter)."""

from __future__ import annotations

import re

# Align with frontend/src/index.css (lavender + pink). Playwright bundles Primer CSS; dark OS theme
# applies @media (prefers-color-scheme: dark) with --color-canvas-default #0d1117 — override both.
_THEME_STYLE = """<style id="rttd-dashboard-theme">
html{
  color-scheme:light!important;
  background:linear-gradient(165deg,#f3ecff 0%,#fceef6 45%,#fff5fb 100%) fixed!important;
  min-height:100%;
}
body{
  background:transparent!important;
  color:#2d1f3d!important;
  font-family:'Plus Jakarta Sans',system-ui,-apple-system,sans-serif!important;
}
#root{
  background:transparent!important;
}
:root{
  --color-fg-default:#2d1f3d!important;
  --color-fg-muted:#6b5f78!important;
  --color-fg-subtle:#8b7a99!important;
  --color-canvas-default:#f3ecff!important;
  --color-canvas-overlay:#ffffff!important;
  --color-canvas-inset:#faf5ff!important;
  --color-canvas-subtle:#fceef6!important;
  --color-border-default:#e2d0f0!important;
  --color-border-muted:#dcc8ea!important;
  --color-border-subtle:rgba(45,31,61,0.12)!important;
  --color-accent-fg:#7c3aed!important;
  --color-accent-emphasis:#7c3aed!important;
  --color-accent-muted:rgba(124,58,237,0.35)!important;
  --color-accent-subtle:#ede9fe!important;
  --color-neutral-muted:rgba(124,58,237,0.12)!important;
  --color-neutral-subtle:rgba(243,236,255,0.85)!important;
}
@media (prefers-color-scheme:dark){
  :root{
    --color-fg-default:#2d1f3d!important;
    --color-fg-muted:#6b5f78!important;
    --color-fg-subtle:#8b7a99!important;
    --color-canvas-default:#f3ecff!important;
    --color-canvas-overlay:#ffffff!important;
    --color-canvas-inset:#faf5ff!important;
    --color-canvas-subtle:#fceef6!important;
    --color-border-default:#e2d0f0!important;
    --color-border-muted:#dcc8ea!important;
    --color-border-subtle:rgba(45,31,61,0.12)!important;
    --color-accent-fg:#7c3aed!important;
    --color-accent-emphasis:#7c3aed!important;
    --color-accent-muted:rgba(124,58,237,0.35)!important;
    --color-accent-subtle:#ede9fe!important;
    --color-neutral-muted:rgba(124,58,237,0.12)!important;
    --color-neutral-subtle:rgba(243,236,255,0.85)!important;
  }
}
</style>"""


def inject_dashboard_theme(html: str) -> str:
    if not html or not html.strip():
        return html
    if 'rttd-dashboard-theme' in html:
        return html
    # Prefer end of <body> so bundled/JS-injected report CSS (Playwright Primer) does not win over us.
    if re.search(r'</body>', html, flags=re.IGNORECASE):
        return re.sub(
            r'(</body>)',
            _THEME_STYLE + r'\1',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    if re.search(r'</head>', html, flags=re.IGNORECASE):
        return re.sub(
            r'(</head>)',
            _THEME_STYLE + r'\1',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
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
