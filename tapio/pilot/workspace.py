"""Shared shell; review endpoints and permissions remain authoritative."""

import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent


def shell(content: str, active: str, title: str) -> str:
    content = re.sub(r"<style>.*?</style>", "", content, flags=re.S)
    content = re.sub(
        r"<!doctype[^>]*>|</?html[^>]*>|<meta[^>]*>|<title>.*?</title>|</?body[^>]*>",
        "",
        content,
        flags=re.I | re.S,
    )
    nav = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if label == active else "") + f">{label}</a>"
        for label, url in [
            ("Import", "/app/import"),
            ("Review", "/pilot/confirmation/groups"),
            ("Ask", "/app/ask"),
            ("Summary", "/app/summary"),
        ]
    )
    subnav = ""
    if active == "Review":
        subnav = """<nav class="review-nav" aria-label="Review tools">
<a href="/pilot/confirmation/groups">Review queue</a>
<a href="/pilot/confirmation">Individual review</a>
<a href="/pilot/confirmation/concepts">Concepts</a>
<a href="/pilot/confirmation/rules">User rules</a>
<a href="/pilot/confirmation/mappings">Category mappings</a></nav>"""
    css = (ROOT / "workspace.css").read_text()
    js = (ROOT / "workspace.js").read_text()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · TAPIO</title><style>{css}</style></head><body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="app-header"><a class="brand" href="/pilot/confirmation/groups">TAPIO</a>
<nav class="app-nav" aria-label="Application">{nav}</nav>
<span class="local-label">Local workspace</span></header>
<script>{js}</script><main id="main">{subnav}{content}</main></body></html>"""


def placeholder(area: str) -> str:
    description = (
        "Bank CSV upload and import results will be added here. Existing command-line "
        "imports remain available; this page does not import or modify records."
        if area == "Import"
        else "A period overview of personal, property and forestry activity will be added "
        "here. No totals or completeness claims are shown until the overview is connected "
        "to validated evidence."
    )
    return shell(
        f"""<h1>{area}</h1><div class="placeholder"><p>{description}</p>
<p><a href="/pilot/confirmation/groups">Review imported transactions</a> or
<a href="/app/ask">ask about existing evidence</a>.</p></div>""",
        area,
        area,
    )
