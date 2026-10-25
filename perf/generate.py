#!/usr/bin/env python3
"""Build the benchmark pages from Bas's stress page (stress-source.html).

The original HUD and its observer script are removed: the HUD rewrites its
text on every container entry, which would add paint work only when the
feature is on and skew the comparison. measure.js replaces it.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "pages"

src = (HERE / "stress-source.html").read_text()
src = re.sub(r"<script>.*?</script>", "", src, flags=re.S)
src = re.sub(r'<div id="hud">.*?</div>\n?', "", src)
src = src.replace("</body>", '<script src="measure.js"></script>\n</body>')
assert 'containertiming="stress-root"' in src

OUT.mkdir(exist_ok=True)
for mode in ("static", "dynamic"):
    page = src.replace('<html lang="en">', f'<html lang="en" data-mode="{mode}">')
    (OUT / f"{mode}.html").write_text(page)
    (OUT / f"{mode}-noattr.html").write_text(
        page.replace(' containertiming="stress-root"', ""))
(OUT / "measure.js").write_text((HERE / "measure.js").read_text())
print("wrote", sorted(p.name for p in OUT.iterdir()))
