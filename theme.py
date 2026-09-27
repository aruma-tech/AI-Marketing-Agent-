"""theme.py - ALL colors of the dashboard live in this one file.

To change the look, change ONE word: PRESET below.
Choices: "indigo", "green", "sunset", "dark".
Want your own colors? Edit the hex codes (like #4f46e5) inside PRESETS.
"""
from string import Template

PRESET = "indigo"

PRESETS = {
    "indigo": {   # blue-purple, clean and modern
        "primary": "#4f46e5", "primary_dark": "#4338ca", "accent": "#06b6d4",
        "tint": "#eef2ff", "bg": "#f5f7fb", "card": "#ffffff", "text": "#1e293b",
        "muted": "#64748b", "border": "#e2e8f0",
        "draft": "#64748b", "approved": "#2563eb", "scheduled": "#b45309",
        "published": "#15803d", "failed": "#dc2626",
        "page_from": "#e0e7ff", "page_to": "#cffafe",
        "hue": "indigo", "neutral": "slate"},
    "green": {    # fresh green
        "primary": "#047857", "primary_dark": "#065f46", "accent": "#84cc16",
        "tint": "#ecfdf5", "bg": "#f4faf7", "card": "#ffffff", "text": "#12332a",
        "muted": "#5b7a6e", "border": "#d5eadf",
        "draft": "#64748b", "approved": "#0369a1", "scheduled": "#b45309",
        "published": "#15803d", "failed": "#dc2626",
        "page_from": "#d1fae5", "page_to": "#ecfccb",
        "hue": "emerald", "neutral": "slate"},
    "sunset": {   # warm orange-pink
        "primary": "#c2410c", "primary_dark": "#9a3412", "accent": "#ec4899",
        "tint": "#fff4ed", "bg": "#fff9f5", "card": "#ffffff", "text": "#3b1d0e",
        "muted": "#8a6a58", "border": "#f3ddd0",
        "draft": "#78716c", "approved": "#2563eb", "scheduled": "#a16207",
        "published": "#15803d", "failed": "#dc2626",
        "page_from": "#ffedd5", "page_to": "#fce7f3",
        "hue": "orange", "neutral": "stone"},
    "dark": {     # dark mode
        "primary": "#6366f1", "primary_dark": "#4f46e5", "accent": "#22d3ee",
        "tint": "#1e293b", "bg": "#0f172a", "card": "#1e293b", "text": "#e2e8f0",
        "muted": "#94a3b8", "border": "#334155",
        "draft": "#64748b", "approved": "#2563eb", "scheduled": "#b45309",
        "published": "#15803d", "failed": "#dc2626",
        "page_from": "#0f172a", "page_to": "#1e1b4b",
        "hue": "indigo", "neutral": "slate"},
}

COLORS = PRESETS.get(PRESET, PRESETS["indigo"])

# Status colors used by the cards and pills on the dashboard
STATUS_COLORS = {
    "DRAFT": COLORS["draft"], "APPROVED": COLORS["approved"],
    "SCHEDULED": COLORS["scheduled"], "PUBLISHED": COLORS["published"],
    "FAILED": COLORS["failed"],
}

_CSS_TEXT = Template("""
/* 0) The WHOLE page (outside the app box too) */
html, body, gradio-app, .gradio-container, .app, .main {
  background: linear-gradient(160deg, $page_from 0%, $page_to 100%) fixed !important;
  min-height: 100vh;
}

/* 1) Colors for every Gradio part (works through Gradio's own color variables) */
:root, .gradio-container {
  --body-background-fill: $page_from;
  --background-fill-primary: $card;
  --background-fill-secondary: $bg;
  --body-text-color: $text;
  --block-title-text-color: $text;
  --block-label-text-color: $muted;
  --border-color-primary: $border;
  --color-accent: $primary;
  --border-color-accent: $primary;
  --link-text-color: $primary;
  --link-text-color-hover: $primary_dark;
  --button-primary-background-fill: $primary;
  --button-primary-background-fill-hover: $primary_dark;
  --button-primary-text-color: #ffffff;
  --button-primary-border-color: $primary;
  --button-secondary-background-fill: $tint;
  --button-secondary-background-fill-hover: $border;
  --button-secondary-text-color: $primary_dark;
  --button-secondary-border-color: $border;
  --input-background-fill: $card;
  --input-border-color: $border;
  --input-border-color-focus: $primary;
  --checkbox-background-color-selected: $primary;
  --table-even-background-fill: $card;
  --table-odd-background-fill: $bg;
}
.gradio-container {max-width: 1280px !important; margin: auto !important; padding-top: 14px !important;}

/* 2) Buttons */
.gradio-container button.primary {background: $primary !important; color: #fff !important;
  border-color: $primary !important; font-weight: 600 !important;}
.gradio-container button.primary:hover {background: $primary_dark !important;}
.gradio-container button.secondary {background: $tint !important; color: $primary_dark !important;
  border: 1px solid $border !important; font-weight: 600 !important;}

/* 3) Tabs: compact so all 8 fit, selected tab is a solid colored pill */
.gradio-container div[role="tablist"] {background: $card; border-radius: 14px; padding: 4px;
  border: 1px solid $border;}
.gradio-container button[role="tab"] {font-weight: 600 !important; font-size: 13px !important;
  padding: 8px 12px !important; color: $muted !important; border-radius: 10px !important;
  border-bottom: none !important;}
.gradio-container button[role="tab"][aria-selected="true"] {background: $primary !important;
  color: #ffffff !important;}

/* 4) Each tab's content sits on a card so it stands out from the colored page */
.gradio-container div[role="tabpanel"] {background: $card; border: 1px solid $border;
  border-radius: 16px; padding: 16px !important; margin-top: 10px;
  box-shadow: 0 4px 14px rgba(0,0,0,.06);}

/* 5) Tables */
.gradio-container table thead th {background: $tint !important; color: $text !important;}

/* 6) Banner, cards, boxes and pills */
.hero {background: linear-gradient(135deg, $primary 0%, $accent 100%); color: #fff;
  padding: 22px 26px; border-radius: 16px; margin-bottom: 12px;}
.hero h1 {margin: 0; font-size: 26px; color: #fff !important;}
.hero p {margin: 6px 0 0; opacity: .92; color: #fff !important;}
.cards {display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; margin: 12px 0;}
.card {border-radius: 14px; padding: 14px 16px; color: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.15);}
.card b {display: block; font-size: 30px; line-height: 1.1; color: #fff;}
.card span {font-size: 13px; opacity: .95; color: #fff;}
.box {border: 1px solid $border; border-radius: 14px; padding: 12px 16px; margin-top: 8px;
  background: $card; color: $text;}
.warn {border-color: $scheduled; background: $tint;}
.pill {display: inline-block; padding: 2px 12px; border-radius: 999px; color: #fff;
  font-size: 12px; font-weight: 700;}
footer, footer * {color: $muted !important;}
""")

RAW_CSS = _CSS_TEXT.substitute(COLORS)          # for Gradio launch()/Blocks(css=...)
CSS = "<style>" + RAW_CSS + "</style>"     # for gr.HTML (extra safety)

HERO = """
<div class="hero"><h1>📣 AI Marketing Agent</h1>
<p>Posts are written from your own business and website. Nothing is published until you approve it.</p></div>
"""


def make_theme():
    """Return a Gradio theme in the same colors, or None if this Gradio version cannot build one."""
    try:
        import gradio as gr
        return gr.themes.Soft(primary_hue=COLORS["hue"], secondary_hue="cyan",
                              neutral_hue=COLORS["neutral"])
    except Exception:
        return None
