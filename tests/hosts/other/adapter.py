"""The second test host: no workers listing beyond $FIX/other-workers.json, messages from $FIX/messages.json."""
import json
import os

import bosshost


def read(name, default):
    try:
        return json.load(open(os.path.join(os.environ.get("FIX", ""), name)))
    except (OSError, ValueError):
        return default


class Host(bosshost.Host):

    def workers(self, ids=None):
        return read("other-workers.json", [])

    def send(self, wid, text, terminal=None):
        with open(os.path.join(os.environ.get("FIX", ""), "calls"), "a") as f:
            f.write(json.dumps([self.name, "send", wid, text, terminal]) + "\n")

    def messages(self, boss, wid):
        return [tuple(m) for m in read("messages.json", [])]

    def dispatched_at(self, boss, wid):
        return read("dispatched.json", 0)
