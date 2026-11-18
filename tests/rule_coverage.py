#!/usr/bin/env python3
"""rule_coverage: nothing in BOSS-template.md on a base ref is lost from today's template + playbooks/*.md.

  tests/rule_coverage.py [--base REF] [-v]     REF defaults to origin/main, else main

Checks, each failing the run (exit 1):
  - section 3 (hard rules) is in the template word for word as on the base;
  - every heading on the base is still a heading in the template;
  - every rule sentence on the base (one saying never, always or only) is in the template or a playbook, verbatim;
  - every other sentence on the base is in the template or a playbook, verbatim;
  - every playbooks/*.md is named in the template on a line that says when to read it (or that it is loaded), and every
    playbook the template names exists.
It counts where the rule sentences live now (template, or playbooks only); -v lists each one.
Not part of the unittest suite on purpose: a PR that rewords a rule on purpose would fail it. Run it for any PR that
moves template text.
"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULE = re.compile(r"\b(never|always|only)\b", re.I)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def sentences(text):
    """(heading, sentence) for every sentence outside headings, list markers stripped."""
    out, head = [], ""
    for line in text.splitlines():
        if line.startswith("#"):
            head = line
            continue
        line = re.sub(r"^\s*(?:[-*]|\d+b?\.)\s+", "", line).strip()
        out += [(head, norm(s)) for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*`(\[])", line) if s.strip()]
    return out


def section(text, n):
    m = re.search(rf"^## {n}\. .*?(?=^## |\Z)", text, re.M | re.S)
    return m.group(0).strip() if m else ""


def base_text(ref):
    for r in ([ref] if ref else ["origin/main", "main"]):
        p = subprocess.run(["git", "-C", ROOT, "show", f"{r}:BOSS-template.md"], capture_output=True, text=True)
        if p.returncode == 0:
            return r, p.stdout
    sys.exit(f"rule_coverage: no BOSS-template.md on {ref or 'origin/main or main'}")


def main(argv):
    ref = argv[argv.index("--base") + 1] if "--base" in argv[:-1] else ""
    ref, base = base_text(ref)
    tmpl = open(os.path.join(ROOT, "BOSS-template.md"), encoding="utf-8").read()
    books = {os.path.relpath(p, ROOT): open(p, encoding="utf-8").read() for p in sorted(glob.glob(os.path.join(ROOT, "playbooks", "*.md")))}
    t, b = norm(tmpl), norm("\n".join(books.values()))
    fails = 0

    same = section(base, 3) == section(tmpl, 3)
    fails += not same
    print(f"{'ok  ' if same else 'FAIL'} section 3 word for word vs {ref}")

    heads = [h for h in base.splitlines() if h.startswith("#")]
    gone = [h for h in heads if h not in tmpl.splitlines()]
    fails += bool(gone)
    print(f"{'FAIL' if gone else 'ok  '} headings: {len(heads) - len(gone)}/{len(heads)} kept" + "".join(f"\n     missing: {h}" for h in gone))

    rules = [(h, s) for h, s in sentences(base) if RULE.search(s)]
    where = [(h, s, "template" if s in t else ("playbooks" if s in b else "MISSING")) for h, s in rules]
    miss = [w for w in where if w[2] == "MISSING"]
    books_only = [w for w in where if w[2] == "playbooks"]
    fails += bool(miss)
    print(f"{'FAIL' if miss else 'ok  '} rule sentences (never/always/only): {len(rules)} on {ref}, "
          f"{len(rules) - len(books_only) - len(miss)} in the template, {len(books_only)} in playbooks only, {len(miss)} missing")
    for h, s, w in where if "-v" in argv else miss:
        print(f"     [{w}] {h[:40]}: {s}")

    rest = [(h, s) for h, s in sentences(base) if not RULE.search(s)]
    lost = [(h, s) for h, s in rest if s not in t and s not in b]
    fails += bool(lost)
    print(f"{'FAIL' if lost else 'ok  '} other sentences: {len(rest)} on {ref}, {len(rest) - len(lost)} kept verbatim, {len(lost)} missing")
    for h, s in lost:
        print(f"     [MISSING] {h[:40]}: {s}")

    named = {}
    for line in tmpl.splitlines():
        for name in re.findall(r"`playbooks/([\w-]+\.md)`", line):
            named[name] = named.get(name) or bool(re.search(r"\b(read|loads)\b", line, re.I))
    files = {os.path.basename(p) for p in books}
    bad = sorted(f"{f}: not named" for f in files - set(named)) + sorted(f"{f}: no such file" for f in set(named) - files)
    bad += sorted(f"{f}: no line says when to read it" for f, when in named.items() if f in files and not when)
    fails += bool(bad)
    print(f"{'FAIL' if bad else 'ok  '} playbooks: {len(files)} files, {len(files) - len(bad)} named with when to read them"
          + "".join(f"\n     {b}" for b in bad))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
