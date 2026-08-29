#!/usr/bin/env python3
"""Build the documentation site: operator manual plus generated API reference.

Two halves, deliberately different in kind.

The **manual** is written by hand. It explains how to run the bot, what each
configuration key does, and what goes wrong if you get one of them wrong — the
things a reader cannot recover from signatures.

The **API reference** is generated from docstrings, so it cannot drift from the
code. Several defects found in this codebase were invisible from the outside:
`restore()` silently ignoring `mode`, the exit gate measuring against a flat fee
that was only correct at one position size, `place_order` always sending
`ordertype="market"`. Generated reference makes that surface visible.

Usage:
    ./scripts/build_docs.py              # build into public/
    ./scripts/build_docs.py --serve      # build, then serve locally
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "docs" / "manual"
OUT = ROOT / "public"


def render_markdown(md: str, title: str, rel: str = "") -> str:
    """Wrap markdown in a self-contained page.

    Rendered client-side so the build has no JS/CSS toolchain to keep current —
    the point of this site is that it stays true, not that it is elaborate.
    """
    # The markdown rides inside a <script> block, so a literal closing tag in
    # the source would end it early and silently truncate the page. Split it so
    # the browser never sees one.
    md = md.replace("</script", "<\\/script")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 6rem;
        font: 16px/1.65 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
 nav {{ margin-bottom: 2.5rem; padding-bottom: .75rem; border-bottom: 1px solid #8883; }}
 nav a {{ margin-right: 1.25rem; }}
 pre {{ background: #8881; padding: .85rem 1rem; overflow-x: auto; border-radius: 6px; }}
 code {{ background: #8881; padding: .1rem .3rem; border-radius: 3px; }}
 pre code {{ background: none; padding: 0; }}
 table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; display: block;
          overflow-x: auto; }}
 th, td {{ border: 1px solid #8884; padding: .45rem .7rem; text-align: left; }}
 blockquote {{ border-left: 3px solid #8886; margin-left: 0; padding-left: 1rem; }}
 h1, h2, h3 {{ line-height: 1.25; }}
 h2 {{ margin-top: 2.5rem; padding-top: .4rem; border-top: 1px solid #8883; }}
</style></head><body>
<nav><a href="{rel}index.html">Manual</a><a href="{rel}configuration.html">Configuration</a>
<a href="{rel}operations.html">Operations</a><a href="{rel}api/cryptotrader.html">API reference</a>
<a href="https://github.com/pkumaschow/cryptotrader">Source</a></nav>
<div id="content"></div>
<script type="module">
import {{ marked }} from "https://cdn.jsdelivr.net/npm/marked/lib/marked.esm.js";
document.getElementById("content").innerHTML =
  marked.parse(document.getElementById("md").textContent);
</script>
<script type="text/plain" id="md">{md}</script>
</body></html>
"""


def build(serve: bool = False) -> int:
    if not MANUAL.is_dir():
        print(f"no manual at {MANUAL}", file=sys.stderr)
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    pages = sorted(MANUAL.glob("*.md"))
    for md in pages:
        name = "index" if md.stem == "index" else md.stem
        title = f"CryptoTrader — {md.stem.replace('-', ' ').title()}"
        (OUT / f"{name}.html").write_text(
            render_markdown(md.read_text(), title))
    print(f"manual: {len(pages)} page(s)")

    # --include-undocumented keeps the reference honest: an undocumented symbol
    # shows up as a gap rather than vanishing, which is the opposite of what a
    # coverage-flattering build would do.
    res = subprocess.run(  # noqa: S603
        # `tui` is excluded deliberately. Its panels subclass Textual widgets,
        # so the generated pages were mostly inherited framework methods —
        # volume, not information. It also silences every pdoc warning, which
        # were all Textual TYPE_CHECKING annotations pdoc cannot resolve.
        [sys.executable, "-m", "pdoc", "cryptotrader", "!cryptotrader.tui",
         "-o", str(OUT / "api"), "-d", "google", "--include-undocumented",
         "--no-search", "--footer-text", "CryptoTrader API reference"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if res.returncode != 0:
        print(res.stderr[-2000:], file=sys.stderr)
        return res.returncode
    generated = len(list((OUT / "api").rglob("*.html")))
    print(f"api reference: {generated} page(s)")

    if serve:
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "http.server", "-d", str(OUT), "8000"],
            check=False)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--serve", action="store_true", help="serve after building")
    return build(serve=ap.parse_args().serve)


if __name__ == "__main__":
    raise SystemExit(main())
