#!/usr/bin/env python3
"""Build the anonymised review copy of the VEIN manuscript.

Reads vein_manuscript.tex and writes vein_manuscript_blind.tex, compiles it in
this folder, rebuilds latex_submission/ as a flat folder (blind tex, bibliography,
class and style files, and only the figures the blind tex includes), compiles it
there, removes LaTeX byproducts, and recreates vein_latex_submission.zip.
"""
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "vein_manuscript.tex"
BLIND = HERE / "vein_manuscript_blind.tex"
FIG_DIR = HERE / "figures"
SUB = HERE / "latex_submission"
ZIP = HERE / "vein_latex_submission.zip"
SUPPORT_FILES = ["references.bib", "sn-jnl.cls", "sn-mathphys-ay.bst"]
JOB = "vein_manuscript_blind"
WITHHELD_URL = "[repository link withheld for review]"
BYPRODUCT_EXTS = [".aux", ".bbl", ".blg", ".log", ".out", ".toc", ".fls",
                  ".fdb_latex", ".synctex.gz", ".bcf", ".run.xml", ".lof", ".lot"]
FORBIDDEN = ["dang", "quang", "vinh", "british university", "buv", "hung yen",
             "vinhqdang", "github", "dq4", "0000-0002", "buv.edu"]


def fail(msg):
    sys.exit("make_blind: " + msg)


def sub_exact(text, pattern, repl, flags=0, expected=1):
    """Regex substitution that must match exactly `expected` times."""
    new, n = re.subn(pattern, repl, text, flags=flags)
    if n != expected:
        fail(f"pattern {pattern!r} matched {n} times, expected {expected}")
    return new


def make_blind_text(text):
    # Author and affiliation blocks (single lines in the source).
    text = sub_exact(text, r"^\\author\*\[1\]\{.*\}\\email\{[^}]*\}$",
                     lambda m: r"\author{Anonymous}", flags=re.M)
    text = sub_exact(text, r"^\\affil\*\[1\]\{.*\}$",
                     lambda m: r"\affil{Anonymous}", flags=re.M)

    # Repository links: \url{https://github.com/...} and any bare github URL.
    text = sub_exact(text, r"\\url\{https?://github\.com/[^}]*\}",
                     lambda m: WITHHELD_URL)
    text = re.sub(r"https?://github\.com/\S*", lambda m: WITHHELD_URL, text)

    # Author contributions paragraph in Statements and Declarations.
    text = sub_exact(
        text,
        r"(\\noindent\\textbf\{Authors' contributions\.\}).*?(?=\n\s*\n)",
        lambda m: m.group(1) + " Withheld for review.",
        flags=re.S,
    )

    # Figures resolve from figures/ in the source folder and from the flat folder itself.
    text = sub_exact(text, r"\\graphicspath\{\{figures/\}\}",
                     lambda m: r"\graphicspath{{figures/}{./}}")
    return text


def check_forbidden(text, label):
    lowered = text.lower()
    hits = [w for w in FORBIDDEN if w in lowered]
    if hits:
        fail(f"{label} still contains identifying terms: {hits}")


def referenced_figures(text):
    names = []
    for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text):
        name = m.group(1).strip()
        if not Path(name).suffix:
            name += ".pdf"
        names.append(name)
    return sorted(set(names))


def build_flat_folder(blind_text):
    SUB.mkdir(exist_ok=True)
    for p in SUB.iterdir():
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    shutil.copy2(BLIND, SUB / BLIND.name)
    for name in SUPPORT_FILES:
        shutil.copy2(HERE / name, SUB / name)
    figs = referenced_figures(blind_text)
    for name in figs:
        src = FIG_DIR / name
        if not src.is_file():
            fail(f"referenced figure missing: {src}")
        shutil.copy2(src, SUB / name)
    return figs


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, text=True)
    return r.returncode, r.stdout


def compile_pdf(cwd):
    """pdflatex, bibtex, pdflatex, pdflatex; returns diagnostics from the final log."""
    steps = [
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{JOB}.tex"],
        ["bibtex", JOB],
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{JOB}.tex"],
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"{JOB}.tex"],
    ]
    for cmd in steps:
        code, out = run(cmd, cwd)
        if cmd[0] == "pdflatex" and code != 0:
            fail(f"{cmd} failed in {cwd}:\n{out[-2000:]}")
        if cmd[0] == "bibtex" and code != 0:
            fail(f"bibtex failed in {cwd}:\n{out[-2000:]}")
    log = (cwd / f"{JOB}.log").read_text(errors="replace")
    undefined = re.findall(r"(?:Citation|Reference) `[^']*' on page \d+ undefined", log)
    errors = re.findall(r"^! .*$", log, flags=re.M)
    pages = re.findall(r"Output written on .*? \((\d+) pages?", log)
    if undefined or errors:
        fail(f"compile in {cwd}: undefined={undefined} errors={errors}")
    if not (cwd / f"{JOB}.pdf").is_file():
        fail(f"no PDF produced in {cwd}")
    return {"pages": int(pages[-1]) if pages else None, "undefined": len(undefined),
            "errors": len(errors)}


def clean_byproducts(folder):
    for ext in BYPRODUCT_EXTS:
        for p in folder.glob(f"{JOB}*{ext}"):
            p.unlink()


def make_zip():
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(SUB.iterdir()):
            if p.is_file():
                zf.write(p, arcname=p.name)


def main():
    src_text = SRC.read_text(encoding="utf-8")
    blind_text = make_blind_text(src_text)
    check_forbidden(blind_text, "blind manuscript")
    BLIND.write_text(blind_text, encoding="utf-8")

    main_result = compile_pdf(HERE)
    clean_byproducts(HERE)

    figs = build_flat_folder(blind_text)
    sub_result = compile_pdf(SUB)
    clean_byproducts(SUB)
    make_zip()

    print(f"blind tex: {BLIND}")
    print(f"manuscript/ build: {main_result}")
    print(f"latex_submission/ build: {sub_result}")
    print(f"figures copied ({len(figs)}): {', '.join(figs)}")
    print(f"zip: {ZIP}")
    print("latex_submission contents:")
    for p in sorted(SUB.iterdir()):
        print(f"  {p.name}")


if __name__ == "__main__":
    main()
