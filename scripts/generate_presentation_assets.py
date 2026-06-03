#!/usr/bin/env python3
"""Generate dashboard-themed PNG assets for the technical briefing deck."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "presentations" / "assets" / "generated"

# Match frontend dark theme
BG = (11, 16, 32)
PANEL = (21, 29, 53)
PANEL_SOFT = (16, 23, 43)
BORDER = (39, 50, 80)
TEXT = (231, 236, 246)
MUTED = (159, 176, 207)
SUCCESS = (38, 194, 129)
DANGER = (255, 107, 107)
WARNING = (255, 179, 71)
PURPLE = (198, 147, 249)
PURPLE_DARK = (138, 56, 225)
GOLD = (234, 179, 8)
ACCENT = (85, 170, 255)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _gradient_bg(size: tuple[int, int], top: tuple[int, ...] = BG, bottom: tuple[int, ...] = (18, 26, 48)) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _rounded_rect(draw: ImageDraw.ImageDraw, xy: tuple, fill, outline=None, radius: int = 16) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=2)


def _save(img: Image.Image, name: str) -> Path:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSETS_DIR / name
    img.save(path, "PNG", optimize=True)
    return path


def logo() -> Path:
    img = Image.new("RGBA", (420, 98), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _rounded_rect(d, (0, 8, 96, 90), PURPLE_DARK, radius=18)
    f = _font(28, True)
    d.text((18, 28), "RTD", fill=(255, 255, 255), font=f)
    d.text((112, 22), "Real-Time Testing", fill=PANEL, font=_font(22, True))
    d.text((112, 54), "Dashboard", fill=PURPLE, font=_font(18))
    return _save(img, "logo.png")


def footer() -> Path:
    w, h = 3424, 272
    img = Image.new("RGB", (w, h), (10, 14, 28))
    d = ImageDraw.Draw(img)
    for x in range(w):
        t = x / w
        c = (
            int(138 + (198 - 138) * t),
            int(56 + (147 - 56) * t),
            int(225 + (249 - 225) * t),
        )
        d.line([(x, 0), (x, h)], fill=c)
    d.rectangle((0, 0, w, 6), fill=GOLD)
    d.text((48, 96), "Real-Time Testing Dashboard  ·  QA Observability for Playwright CI", fill=(255, 255, 255), font=_font(36, True))
    d.text((48, 168), "Vercel UI  ·  Render API  ·  PostgreSQL  ·  GitHub Actions ingest", fill=(240, 240, 255), font=_font(26))
    return _save(img, "footer.png")


def slide_bg() -> Path:
    img = _gradient_bg((2500, 1767))
    d = ImageDraw.Draw(img)
    for i in range(12):
        x = 200 + i * 180
        d.ellipse((x, 400, x + 120, 520), fill=(30, 40, 70))
    d.text((120, 120), "Real-Time Testing Dashboard", fill=MUTED, font=_font(48, True))
    return _save(img, "slide_bg.png")


def hero_dashboard() -> Path:
    w, h = 1411, 721
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    _rounded_rect(d, (24, 24, w - 24, h - 24), PANEL, outline=BORDER, radius=24)
    d.text((48, 40), "Live dashboard preview", fill=TEXT, font=_font(32, True))
    # KPI row
    labels = [("Total Runs", "128"), ("Pass Rate", "94%"), ("Cases", "1,024"), ("Defects", "7")]
    x0 = 48
    for label, val in labels:
        _rounded_rect(d, (x0, 100, x0 + 300, 220), PANEL_SOFT, outline=BORDER, radius=14)
        d.text((x0 + 16, 118), label, fill=MUTED, font=_font(18))
        d.text((x0 + 16, 150), val, fill=SUCCESS if "94" in val else TEXT, font=_font(36, True))
        x0 += 320
    # chart area
    _rounded_rect(d, (48, 250, w - 48, h - 48), PANEL_SOFT, outline=BORDER, radius=16)
    d.text((64, 268), "Pass rate trend (last 14 runs)", fill=MUTED, font=_font(20))
    bx, by = 80, 520
    heights = [180, 220, 200, 260, 240, 280, 300, 290, 310, 320]
    for i, ht in enumerate(heights):
        color = SUCCESS if ht > 250 else WARNING
        d.rectangle((bx + i * 55, by - ht, bx + i * 55 + 36, by), fill=color)
    return _save(img, "hero_dashboard.png")


def architecture() -> Path:
    w, h = 1774, 887
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "System architecture", fill=TEXT, font=_font(40, True))

    def box(x, y, bw, bh, title, sub, color):
        _rounded_rect(d, (x, y, x + bw, y + bh), PANEL, outline=color, radius=18)
        d.text((x + 20, y + 18), title, fill=TEXT, font=_font(26, True))
        d.text((x + 20, y + 56), sub, fill=MUTED, font=_font(20))

    box(60, 120, 320, 140, "GitHub Actions", "Playwright CI + ingest POST", ACCENT)
    box(420, 120, 300, 140, "Vercel", "React dashboard (same-origin /api)", PURPLE)
    box(760, 120, 340, 140, "Render API", "FastAPI ingest · summary · CI", WARNING)
    box(1140, 120, 300, 140, "PostgreSQL", "Runs · cases · report ZIPs", SUCCESS)

    # arrows
    for x1, x2 in [(380, 420), (720, 760), (1100, 1140)]:
        d.line([(x1, 190), (x2, 190)], fill=GOLD, width=6)
        d.polygon([(x2 - 12, 182), (x2, 190), (x2 - 12, 198)], fill=GOLD)

    box(260, 360, 520, 200, "Data flow", "workflow_dispatch → run tests → JSON/ZIP ingest → dashboard refresh", PANEL_SOFT)
    box(860, 360, 520, 200, "Live observability", "KPIs · trends · live feed · embedded HTML report viewer", PANEL_SOFT)
    box(420, 620, 900, 200, "Security boundary", "Secrets server-side only: GITHUB_ACTIONS_INGEST_TOKEN, GITHUB_CI_TOKEN, DATABASE_URL", PANEL_SOFT)
    return _save(img, "architecture.png")


def process_flow() -> Path:
    w, h = 1160, 1068
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "End-to-end pipeline", fill=TEXT, font=_font(36, True))
    steps = [
        ("01", "Trigger", "Dashboard or push", ACCENT),
        ("02", "CI run", "Jobs & steps on GitHub", PURPLE),
        ("03", "Ingest", "POST /api/ingest/...", WARNING),
        ("04", "Observe", "KPIs + live feed update", SUCCESS),
    ]
    y = 120
    for num, title, sub, color in steps:
        _rounded_rect(d, (40, y, w - 40, y + 200), PANEL, outline=color, radius=20)
        d.ellipse((70, y + 50, 150, y + 130), fill=color)
        d.text((88, y + 68), num, fill=(255, 255, 255), font=_font(32, True))
        d.text((180, y + 48), title, fill=TEXT, font=_font(30, True))
        d.text((180, y + 100), sub, fill=MUTED, font=_font(22))
        if y < 900:
            d.polygon([(w // 2 - 20, y + 210), (w // 2 + 20, y + 210), (w // 2, y + 250)], fill=GOLD)
        y += 230
    return _save(img, "process_flow.png")


def kpi_panel() -> Path:
    w, h = 594, 304
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((16, 12), "Executive KPIs", fill=TEXT, font=_font(22, True))
    for i, (lbl, val, col) in enumerate([("Runs", "128", TEXT), ("Pass", "94%", SUCCESS), ("Defects", "7", DANGER)]):
        x = 16 + i * 190
        _rounded_rect(d, (x, 70, x + 170, 260), PANEL_SOFT, outline=BORDER, radius=12)
        d.text((x + 14, 90), lbl, fill=MUTED, font=_font(16))
        d.text((x + 14, 130), val, fill=col, font=_font(40, True))
    return _save(img, "kpi_panel.png")


def ingest_diagram() -> Path:
    w, h = 590, 298
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((16, 10), "GitHub Actions ingest", fill=TEXT, font=_font(20, True))
    _rounded_rect(d, (16, 50, 260, 270), PANEL_SOFT, outline=ACCENT, radius=12)
    d.text((28, 70), "CI workflow", fill=MUTED, font=_font(16))
    d.text((28, 100), "JSON payload", fill=TEXT, font=_font(18))
    d.text((28, 130), "+ optional ZIP", fill=TEXT, font=_font(18))
    d.line([(260, 160), (310, 160)], fill=GOLD, width=4)
    _rounded_rect(d, (310, 80, 560, 240), PANEL_SOFT, outline=PURPLE, radius=12)
    d.text((324, 100), "Render API", fill=TEXT, font=_font(18, True))
    d.text((324, 130), "X-Ingest-Token", fill=WARNING, font=_font(16))
    d.text((324, 160), "Postgres persist", fill=SUCCESS, font=_font(16))
    return _save(img, "ingest_diagram.png")


def html_report_embed() -> Path:
    w, h = 4241 // 2, 2142 // 2  # ~2120 x 1071 - use reasonable
    w, h = 1200, 600
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((32, 24), "Embedded Playwright HTML report", fill=TEXT, font=_font(32, True))
    _rounded_rect(d, (32, 80, w - 32, h - 32), PANEL, outline=BORDER, radius=16)
    d.text((56, 110), "Suite: checkout-smoke  ·  Build: abc1234  ·  42 passed / 2 failed", fill=MUTED, font=_font(20))
    for i, (name, status) in enumerate([("login", "passed"), ("cart", "passed"), ("pay", "failed")]):
        y = 160 + i * 120
        col = SUCCESS if status == "passed" else DANGER
        _rounded_rect(d, (56, y, w - 56, y + 90), PANEL_SOFT, outline=col, radius=10)
        d.text((72, y + 28), name, fill=TEXT, font=_font(24, True))
        d.text((w - 200, y + 28), status.upper(), fill=col, font=_font(22, True))
    return _save(img, "html_report_embed.png")


def ci_steps() -> Path:
    w, h = 392, 1126
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((20, 20), "CI execution", fill=TEXT, font=_font(22, True))
    steps = [
        ("queued", MUTED),
        ("in_progress", WARNING),
        ("completed", SUCCESS),
    ]
    y = 80
    for name, col in [
        ("Install deps", SUCCESS),
        ("Run Playwright", WARNING),
        ("Publish to dashboard", ACCENT),
        ("Upload artifacts", MUTED),
    ]:
        _rounded_rect(d, (16, y, w - 16, y + 200), PANEL_SOFT, outline=col, radius=14)
        d.text((32, y + 40), name, fill=TEXT, font=_font(20, True))
        d.text((32, y + 90), "GitHub Actions job step", fill=MUTED, font=_font(16))
        y += 240
    return _save(img, "ci_steps.png")


def github_workflow() -> Path:
    w, h = 1600, 400
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((32, 24), "workflow_dispatch from dashboard", fill=TEXT, font=_font(28, True))
    nodes = ["Dashboard CI panel", "GitHub API", "Actions runner", "Ingest API"]
    x = 40
    for i, node in enumerate(nodes):
        _rounded_rect(d, (x, 120, x + 340, 300), PANEL_SOFT, outline=PURPLE if i == 0 else BORDER, radius=14)
        d.text((x + 20, 180), node, fill=TEXT, font=_font(22, True))
        if i < len(nodes) - 1:
            d.line([(x + 350, 210), (x + 390, 210)], fill=GOLD, width=5)
        x += 390
    return _save(img, "github_workflow.png")


def dashboard_comparison() -> Path:
    w, h = 1682, 1810
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Dashboard vs Playwright HTML", fill=TEXT, font=_font(36, True))
    _rounded_rect(d, (40, 100, w // 2 - 20, h - 40), PANEL, outline=PURPLE, radius=20)
    d.text((60, 130), "Real-Time Dashboard", fill=PURPLE, font=_font(28, True))
    for i, line in enumerate(["Portfolio KPIs", "Trend charts", "CI trigger panel", "Build history"]):
        d.text((60, 200 + i * 50), f"• {line}", fill=TEXT, font=_font(22))
    _rounded_rect(d, (w // 2 + 20, 100, w - 40, h - 40), PANEL, outline=ACCENT, radius=20)
    d.text((w // 2 + 60, 130), "Playwright HTML", fill=ACCENT, font=_font(28, True))
    for i, line in enumerate(["Traces & video", "Step screenshots", "Attachment downloads", "Deep failure debug"]):
        d.text((w // 2 + 60, 200 + i * 50), f"• {line}", fill=TEXT, font=_font(22))
    return _save(img, "dashboard_comparison.png")


def thank_you_hero() -> Path:
    w, h = 2500, 1400
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((120, 200), "Real-Time Testing Dashboard", fill=TEXT, font=_font(72, True))
    d.text((120, 320), "Unified observability for Playwright CI", fill=PURPLE, font=_font(48))
    _rounded_rect(d, (120, 420, 1100, 900), PANEL, outline=BORDER, radius=24)
    d.text((160, 480), "realtime-testing-dashboard-ooka.vercel.app", fill=ACCENT, font=_font(32))
    d.text((160, 560), "API: realtime-testing-dashboard-api-ld7t.onrender.com", fill=MUTED, font=_font(28))
    # mini dashboard
    _rounded_rect(d, (1250, 200, w - 120, h - 120), PANEL, outline=PURPLE, radius=24)
    d.text((1280, 240), "Live KPI snapshot", fill=TEXT, font=_font(32, True))
    for i, (lbl, val) in enumerate([("Runs", "128"), ("Pass", "94%"), ("Cases", "1024")]):
        x = 1280 + i * 380
        _rounded_rect(d, (x, 340, x + 340, 520), PANEL_SOFT, outline=BORDER, radius=14)
        d.text((x + 20, 380), lbl, fill=MUTED, font=_font(24))
        d.text((x + 20, 420), val, fill=SUCCESS, font=_font(48, True))
    return _save(img, "thank_you_hero.png")


def tech_ecosystem() -> Path:
    w, h = 1680, 860
    img = _gradient_bg((w, h))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Platform stack", fill=TEXT, font=_font(36, True))
    stacks = [
        ("FastAPI + SQLAlchemy", "REST, ingest, Alembic migrations"),
        ("React + Vite + TS", "KPI grid, charts, CI panel"),
        ("PostgreSQL on Render", "Durable run & report storage"),
        ("GitHub Actions", "Test execution + publish step"),
    ]
    y = 120
    for title, sub in stacks:
        _rounded_rect(d, (40, y, w - 40, y + 150), PANEL_SOFT, outline=BORDER, radius=16)
        d.text((60, y + 28), title, fill=GOLD, font=_font(28, True))
        d.text((60, y + 78), sub, fill=MUTED, font=_font(22))
        y += 170
    return _save(img, "tech_ecosystem.png")


def generate_all() -> dict[str, Path]:
    return {
        "logo.png": logo(),
        "footer.png": footer(),
        "slide_bg.png": slide_bg(),
        "hero_dashboard.png": hero_dashboard(),
        "architecture.png": architecture(),
        "process_flow.png": process_flow(),
        "kpi_panel.png": kpi_panel(),
        "ingest_diagram.png": ingest_diagram(),
        "html_report_embed.png": html_report_embed(),
        "ci_steps.png": ci_steps(),
        "github_workflow.png": github_workflow(),
        "dashboard_comparison.png": dashboard_comparison(),
        "thank_you_hero.png": thank_you_hero(),
        "tech_ecosystem.png": tech_ecosystem(),
    }


if __name__ == "__main__":
    paths = generate_all()
    for name, path in paths.items():
        print(f"{name} -> {path}")
