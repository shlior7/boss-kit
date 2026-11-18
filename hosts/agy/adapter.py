"""AGY CLI host.  AGY has no safe queued-message command, so a live worker is never interrupted."""
import bossnative
import bosshost


class Host(bosshost.Host):
    def __init__(self, cfg, manifest):
        super().__init__(cfg, manifest)
        self.cli = bosshost.installed(manifest) or "agy"

    def workers(self, ids=None):
        return bossnative.list_workers("agy", self.cfg, ids)

    def create(self, repo, branch, prompt, model="", effort="", name="", folder=""):
        def command(worktree, text, model, effort, log):
            argv = [self.cli, "--print", "--mode", "auto", "--output-format", "json"]
            if model:
                argv += ["--model", model]
            if effort:
                argv += ["--effort", effort]
            return argv + [text]
        return bossnative.create("agy", self.cfg, command, branch, prompt, model, effort, name, folder)

    def send(self, wid, text, terminal=None):
        self._no("sending a message to a live AGY worker", "AGY has no queue command; wait for its completion or start a follow-up worker")

    def archive(self, wid):
        bossnative.archive("agy", self.cfg, wid)

    def rename(self, wid, name):
        bossnative.rename("agy", self.cfg, wid, name)

    def move(self, wid, folder):
        bossnative.move("agy", self.cfg, wid, folder)

    def screen(self, wid, terminal):
        return bossnative.screen("agy", self.cfg, wid)

    def archive_cmd(self, wid):
        return f"boss-host archive {wid}  # only after the AGY process exits; worktree is retained"
