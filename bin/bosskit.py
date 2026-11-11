"""Shared helpers: where the kit lives, which project is active, and its config.

Kit root: $BOSS_KIT_HOME, else the folder above bin/. Project: $BOSS_PROJECT, else the only
folder under projects/ other than _template. Config: projects/<name>/config.json.
Per-project runtime state (caches, tracker snapshot, the pane's next line) goes to
state/<name>/, which is gitignored.
"""
import json
import os
import sys

KIT = os.environ.get("BOSS_KIT_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(KIT, "projects")


def project_name():
    name = os.environ.get("BOSS_PROJECT")
    if name:
        return name
    found = [d for d in sorted(os.listdir(PROJECTS)) if not d.startswith("_")
             and os.path.isfile(os.path.join(PROJECTS, d, "config.json"))] if os.path.isdir(PROJECTS) else []
    if len(found) == 1:
        return found[0]
    sys.exit("bosskit: set BOSS_PROJECT (projects found: %s)" % (", ".join(found) or "none, run bin/boss-init"))


def load(name=None):
    """(name, config, project dir, state dir) for the active project."""
    name = name or project_name()
    pdir = os.path.join(PROJECTS, name)
    with open(os.path.join(pdir, "config.json")) as f:
        cfg = json.load(f)
    sdir = os.path.join(KIT, "state", name)
    os.makedirs(sdir, exist_ok=True)
    return name, cfg, pdir, sdir
