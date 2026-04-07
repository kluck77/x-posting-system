"""
Regression guard for dashboard tab switching.

Prevents the bug class that caused S47 → S50 → S55 regressions:
a CSS rule targeting a page root (#page-home/ai/intake/ops) sets
`display:*` without scoping to `.active`, silently defeating the
`.page{display:none}` / `.page.active{display:flex}` contract and
breaking tab switching on iOS Safari.

This test parses static/dashboard.html as text and fails on:
  A) any `#page-* { display:* }` rule not qualified by `.active`
  B) any bare `.page { display:* }` rule with a value other than `none`
  C) missing S35 canonical contract (`.page:not(.active){display:none}`
     and at least one `#page-*.page.active{display:...}` rule)

Zero dashboard.html edits. Pure text parse. Runs in milliseconds.
"""

from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"

PAGE_ROOTS = ("home", "ai", "intake", "ops")


def _load_css_text() -> str:
    """Read dashboard.html and strip /* ... */ comments to avoid
    matching commented-out example selectors."""
    raw = DASHBOARD.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)


def _line_of(raw: str, idx: int) -> int:
    return raw.count("\n", 0, idx) + 1


def test_dashboard_file_exists():
    assert DASHBOARD.exists(), f"dashboard missing: {DASHBOARD}"


def test_no_unqualified_page_root_display_rule():
    """
    Fails if any selector ending in `#page-{home|ai|intake|ops}` or
    `#page-*.page` (without `.active`) opens a block that contains
    `display:`. This catches both:
      - `#page-ai{display:flex}`  (S50 class)
      - `html body .hud-main #page-ai.page{display:block}`  (S47 class)
    """
    raw = DASHBOARD.read_text(encoding="utf-8")
    text = _load_css_text()

    # Match a selector ending in #page-<root> optionally followed by
    # `.page`, NOT followed by `.active`, then `{ ... display: ... }`.
    pattern = re.compile(
        r"(?P<sel>[^{};\n]*?#page-(?:home|ai|intake|ops)(?:\.page)?)"
        r"\s*\{(?P<body>[^{}]*?)\}",
        re.IGNORECASE,
    )

    offenders: list[str] = []
    for m in pattern.finditer(text):
        sel = m.group("sel").strip()
        body = m.group("body")
        if ".active" in sel:
            continue
        if not re.search(r"\bdisplay\s*:", body):
            continue
        # Locate line in the ORIGINAL (pre-strip) file for useful error.
        # Find the selector signature in raw text.
        needle = sel.split()[-1]  # last token, e.g. #page-ai.page
        raw_idx = raw.find(needle + "{")
        if raw_idx == -1:
            raw_idx = raw.find(needle + " {")
        line = _line_of(raw, raw_idx) if raw_idx != -1 else -1
        offenders.append(f"L{line}: `{sel}` sets display:* without .active")

    assert not offenders, (
        "Dashboard tab-switching regression guard tripped. "
        "A CSS rule forces a page root visible outside the .active state. "
        "This is the S47/S50/S55 bug class.\n  "
        + "\n  ".join(offenders)
    )


def test_no_bare_page_display_other_than_none():
    """
    `.page { display: X }` should only set `display: none`. Any other
    value breaks the `.page.active{display:block/flex}` contract when
    specificity ties land wrong.
    """
    raw = DASHBOARD.read_text(encoding="utf-8")
    text = _load_css_text()

    # Bare `.page{...}` — not preceded by `.` or a word char, no `.active`
    # or `:not` right after.
    pattern = re.compile(
        r"(?<![.\w\-])\.page(?![.\w\-:])\s*\{([^{}]*)\}",
        re.IGNORECASE,
    )

    offenders: list[str] = []
    for m in pattern.finditer(text):
        body = m.group(1)
        disp = re.search(r"\bdisplay\s*:\s*([^;}]+)", body)
        if not disp:
            continue
        value = disp.group(1).strip().rstrip("!important").strip().rstrip(";").strip()
        if value.lower() != "none":
            raw_idx = raw.find(".page")
            line = _line_of(raw, raw_idx) if raw_idx != -1 else -1
            offenders.append(f"L{line}: `.page{{display:{value}}}`")

    assert not offenders, (
        "`.page` rule sets display to a value other than `none`. "
        "Only `.page{display:none}` is allowed; visibility belongs on "
        "`.page.active` or `#page-*.page.active`.\n  " + "\n  ".join(offenders)
    )


def test_canonical_contract_present():
    """
    Sanity: the S35 canonical contract must exist. If someone deletes
    it, tab switching silently breaks.
    """
    text = _load_css_text()

    has_hide = re.search(
        r"\.page\s*:\s*not\s*\(\s*\.active\s*\)\s*\{[^{}]*display\s*:\s*none",
        text,
        re.IGNORECASE,
    )
    assert has_hide, (
        "Missing `.page:not(.active){display:none}` — S35 canonical "
        "hide rule. Tab switching depends on it."
    )

    has_show = re.search(
        r"#page-(?:home|ai|intake|ops)\.page\.active\s*\{[^{}]*display\s*:",
        text,
        re.IGNORECASE,
    )
    assert has_show, (
        "Missing `#page-*.page.active{display:...}` — S35 canonical "
        "show rule for at least one page root."
    )
