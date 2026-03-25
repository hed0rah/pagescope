"""Color themes for the PageScope TUI."""

from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "devtools": {
        "bg": "#0f172a",
        "bg-card": "#1e293b",
        "bg-alt": "#131c2e",
        "border": "#334155",
        "text": "#e2e8f0",
        "text-dim": "#94a3b8",
        "accent": "#6366f1",
        "green": "#10b981",
        "yellow": "#f59e0b",
        "red": "#ef4444",
        "cyan": "#22d3ee",
        "blue": "#3b82f6",
        # waterfall timing phase colors
        "wf-dns": "#3b82f6",
        "wf-connect": "#10b981",
        "wf-ssl": "#a855f7",
        "wf-wait": "#f59e0b",
        "wf-download": "#22d3ee",
        "wf-queued": "#334155",
    },
    "monokai": {
        "bg": "#272822",
        "bg-card": "#3e3d32",
        "bg-alt": "#2e2d23",
        "border": "#75715e",
        "text": "#f8f8f2",
        "text-dim": "#75715e",
        "accent": "#a6e22e",
        "green": "#a6e22e",
        "yellow": "#e6db74",
        "red": "#f92672",
        "cyan": "#66d9ef",
        "blue": "#66d9ef",
        "wf-dns": "#66d9ef",
        "wf-connect": "#a6e22e",
        "wf-ssl": "#ae81ff",
        "wf-wait": "#e6db74",
        "wf-download": "#66d9ef",
        "wf-queued": "#49483e",
    },
    "solarized": {
        "bg": "#002b36",
        "bg-card": "#073642",
        "bg-alt": "#003340",
        "border": "#586e75",
        "text": "#839496",
        "text-dim": "#586e75",
        "accent": "#268bd2",
        "green": "#859900",
        "yellow": "#b58900",
        "red": "#dc322f",
        "cyan": "#2aa198",
        "blue": "#268bd2",
        "wf-dns": "#268bd2",
        "wf-connect": "#859900",
        "wf-ssl": "#6c71c4",
        "wf-wait": "#b58900",
        "wf-download": "#2aa198",
        "wf-queued": "#073642",
    },
    "dracula": {
        "bg": "#282a36",
        "bg-card": "#44475a",
        "bg-alt": "#303245",
        "border": "#6272a4",
        "text": "#f8f8f2",
        "text-dim": "#6272a4",
        "accent": "#bd93f9",
        "green": "#50fa7b",
        "yellow": "#f1fa8c",
        "red": "#ff5555",
        "cyan": "#8be9fd",
        "blue": "#bd93f9",
        "wf-dns": "#8be9fd",
        "wf-connect": "#50fa7b",
        "wf-ssl": "#bd93f9",
        "wf-wait": "#f1fa8c",
        "wf-download": "#8be9fd",
        "wf-queued": "#44475a",
    },
    "nord": {
        "bg": "#2e3440",
        "bg-card": "#3b4252",
        "bg-alt": "#353c4a",
        "border": "#4c566a",
        "text": "#eceff4",
        "text-dim": "#d8dee9",
        "accent": "#88c0d0",
        "green": "#a3be8c",
        "yellow": "#ebcb8b",
        "red": "#bf616a",
        "cyan": "#88c0d0",
        "blue": "#5e81ac",
        "wf-dns": "#5e81ac",
        "wf-connect": "#a3be8c",
        "wf-ssl": "#b48ead",
        "wf-wait": "#ebcb8b",
        "wf-download": "#88c0d0",
        "wf-queued": "#3b4252",
    },
    "killengn": {
        "bg": "#0a0a0f",
        "bg-card": "#12121c",
        "bg-alt": "#0e0e16",
        "border": "#2a2a3a",
        "text": "#d4d4e0",
        "text-dim": "#6a6a80",
        "accent": "#20DFC8",
        "green": "#20DFC8",
        "yellow": "#DFC820",
        "red": "#C820DF",
        "cyan": "#20DFC8",
        "blue": "#C820DF",
        "wf-dns": "#C820DF",
        "wf-connect": "#20DFC8",
        "wf-ssl": "#DF2068",
        "wf-wait": "#DFC820",
        "wf-download": "#20DFC8",
        "wf-queued": "#1a1a2a",
    },
}

THEME_NAMES = list(THEMES.keys())


def get_theme_css(name: str) -> str:
    """Generate TCSS variable overrides for a given theme."""
    t = THEMES.get(name, THEMES["devtools"])
    return f"""
    Screen {{ background: {t['bg']}; }}
    #header-bar {{ background: {t['bg-card']}; border-bottom: solid {t['border']}; }}
    #header-bar Label {{ color: {t['text']}; }}
    #url-input {{ background: transparent; border: none; color: {t['accent']}; }}
    #url-input:focus {{ background: {t['bg']}; color: {t['text']}; }}
    #status-label {{ color: {t['text-dim']}; }}
    #filter-bar {{ background: {t['bg-card']}; border-bottom: solid {t['border']}; }}
    #filter-bar Button {{ color: {t['text-dim']}; background: transparent; }}
    #filter-bar Button:hover {{ color: {t['text']}; background: transparent; }}
    #filter-bar Button.active {{ color: {t['accent']}; text-style: bold underline; background: transparent; }}
    #filter-input {{ background: {t['bg']}; border: none {t['border']}; color: {t['text']}; }}
    DataTable > .datatable--header {{ background: {t['bg-card']}; color: {t['text-dim']}; }}
    DataTable > .datatable--cursor {{ background: {t['border']}; }}
    DataTable > .datatable--even-row {{ background: {t['bg']}; }}
    DataTable > .datatable--odd-row {{ background: {t['bg-alt']}; }}
    #detail-panel {{ background: {t['bg-card']}; border-top: solid {t['border']}; }}
    #detail-tabs {{ background: {t['bg']}; border-bottom: solid {t['border']}; }}
    #detail-tabs Button {{ color: {t['text-dim']}; background: transparent; }}
    #detail-tabs Button.active {{ color: {t['accent']}; text-style: bold underline; background: transparent; }}
    #detail-content Static {{ color: {t['text']}; }}
    #summary-bar {{ background: {t['bg-card']}; border-top: solid {t['border']}; }}
    #summary-bar Label {{ color: {t['text-dim']}; }}
    #console-filter-bar {{ background: {t['bg-card']}; border-bottom: solid {t['border']}; }}
    #console-filter-bar Button {{ color: {t['text-dim']}; background: transparent; }}
    #console-filter-bar Button:hover {{ color: {t['text']}; background: transparent; }}
    #console-filter-bar Button.active {{ color: {t['accent']}; text-style: bold underline; background: transparent; }}
    #console-search {{ background: {t['bg']}; border: none {t['border']}; color: {t['text']}; }}
    #console-detail {{ background: {t['bg-card']}; border-top: solid {t['border']}; }}
    #console-detail-content {{ color: {t['text']}; }}
    #console-summary {{ background: {t['bg-card']}; border-top: solid {t['border']}; }}
    #console-summary Label {{ color: {t['text-dim']}; }}
    #console-input-bar {{ background: {t['bg-alt']}; border-top: solid {t['border']}; }}
    #console-prompt {{ color: {t['cyan']}; }}
    #console-eval-input {{ background: {t['bg']}; border: none {t['border']}; color: {t['text']}; }}
    Footer {{ background: {t['bg-card']}; }}
    .placeholder-tab {{ color: {t['border']}; }}
    #dom-tree {{ background: {t['bg']}; }}
    #dom-tree > .tree--cursor {{ background: {t['border']}; }}
    #dom-tree > .tree--guides {{ color: {t['border']}; }}
    #legend-overlay {{ background: {t['bg-card']}; border: solid {t['border']}; color: {t['text']}; }}
    """
