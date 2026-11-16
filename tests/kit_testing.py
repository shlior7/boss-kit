"""Helpers the kit's tests and the host plugins' tests share."""
import os


def fake_cli(tmp, name, cases):
    """A stub *name* on a temp PATH dir that appends its argv to <tmp>/calls and prints cases[a prefix of its args] (else exits 0)."""
    stubs = os.path.join(tmp, "stubs")
    os.makedirs(stubs, exist_ok=True)
    body = "".join(f'  "{k}"*) cat <<\'JSON\'\n{v}\nJSON\n;;\n' for k, v in cases.items())
    path = os.path.join(stubs, name)
    open(path, "w").write(f'#!/bin/sh\necho "{name} $*" >> "{tmp}/calls"\ncase "$*" in\n{body}  *) exit 0;;\nesac\n')
    os.chmod(path, 0o755)
    return stubs
