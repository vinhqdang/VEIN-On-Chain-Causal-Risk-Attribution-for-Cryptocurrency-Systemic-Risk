#!/usr/bin/env python3
"""Build the flat LaTeX package of the manuscript WITH author details.

Copies vein_manuscript.tex (author, affiliation, repository link and
contributions included), references.bib, the Springer class and style, and
the figures it includes into latex_submission_named/ with no subfolders,
compiles it there (pdflatex, bibtex, pdflatex x2) and writes
vein_latex_submission_named.zip. Use make_blind.py for the anonymised package.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "latex_submission_named"
ZIP = HERE / "vein_latex_submission_named.zip"
TEX = "vein_manuscript.tex"
SUPPORT = ["references.bib", "sn-jnl.cls", "sn-mathphys-ay.bst"]
BYPRODUCTS = (".aux", ".log", ".bbl", ".blg", ".out")


def main() -> None:
    src = (HERE / TEX).read_text()
    figs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", src)
    # Figures sit next to the .tex in the flat package.
    src = src.replace(r"\graphicspath{{figures/}}", r"\graphicspath{{figures/}{./}}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / TEX).write_text(src)
    for name in SUPPORT:
        shutil.copy(HERE / name, OUT / name)
    for fig in figs:
        shutil.copy(HERE / "figures" / fig, OUT / fig)

    stem = TEX[:-4]
    for cmd in (["pdflatex", "-interaction=nonstopmode", stem], ["bibtex", stem],
                ["pdflatex", "-interaction=nonstopmode", stem],
                ["pdflatex", "-interaction=nonstopmode", stem]):
        subprocess.run(cmd, cwd=OUT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = (OUT / f"{stem}.log").read_text(errors="replace")
    if re.search(r"^! ", log, re.M) or "undefined" in log:
        raise SystemExit("compile failed or has undefined references; see latex_submission_named/")
    for p in OUT.iterdir():
        if p.suffix in BYPRODUCTS:
            p.unlink()

    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.iterdir()):
            z.write(p, p.name)
    print(f"wrote {ZIP.name}: {len(list(OUT.iterdir()))} files")


if __name__ == "__main__":
    main()
