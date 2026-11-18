"""bin/mem-gate: lanes, idle-holder release, status. Every test uses a temp $MEM_GATE_DIR and a stub `sysctl` (memory is always fine).

Run: python3 -m unittest discover -s tests   (the idle/TTL tests wait a few real seconds: POLL, TTL and IDLE are 1-2 s here)
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_testing import fake_cli  # noqa: E402

GATE = os.path.join(BIN, "mem-gate")


class MemGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "gate")
        stubs = fake_cli(self.tmp, "sysctl", {
            "-n kern.memorystatus_level": "62", "-n kern.memorystatus_vm_pressure_level": "1",
            "-n vm.swapusage": "total = 2048.00M  used = 100.00M  free = 1948.00M  (encrypted)"})
        self.env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "MEM_GATE_DIR": self.dir, "MEM_GATE_SLOTS": "1",
                    "MEM_GATE_SERVER_SLOTS": "1", "MEM_GATE_POLL": "1", "MEM_GATE_TTL": "2", "MEM_GATE_IDLE": "2"}
        self.procs = []

    def tearDown(self):
        for p in self.procs:  # only the process groups this test started
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        subprocess.run(["rm", "-rf", self.tmp])

    def start(self, *args, env=None):
        p = subprocess.Popen([GATE, *args], env={**self.env, **(env or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        self.procs.append(p)
        return p

    def admitted(self, p, secs=10):
        """Wait until the wrapper's slot dir names it; True when it does."""
        end = time.time() + secs
        while time.time() < end:
            for s in os.listdir(self.dir) if os.path.isdir(self.dir) else []:
                try:
                    if open(os.path.join(self.dir, s, "pid")).read().strip() == str(p.pid):
                        return True
                except OSError:
                    pass
            time.sleep(0.2)
        return False

    def status(self):
        return subprocess.run([GATE, "--status"], env=self.env, capture_output=True, text=True).stdout

    def test_idle_holder_is_released_for_a_short_gate(self):
        holder = self.start("--", "sleep", "300")
        self.assertTrue(self.admitted(holder))
        gate = self.start("--", "true")
        self.assertEqual(gate.wait(timeout=15), 0, "a short gate stayed queued behind an idle holder")
        self.assertIsNone(holder.poll(), "the released holder's process was killed")
        self.assertIn("released", open(os.path.join(self.dir, "log")).read())

    def test_busy_holder_is_never_released(self):
        holder = self.start("--", "sh", "-c", "while :; do :; done")
        self.assertTrue(self.admitted(holder))
        gate = self.start("--", "true")
        with self.assertRaises(subprocess.TimeoutExpired):
            gate.wait(timeout=8)  # well past TTL (2 s) plus IDLE (2 s)
        self.assertTrue(self.admitted(holder, 1), "a busy holder lost its slot")
        self.assertIsNone(holder.poll())

    def test_released_holder_exit_leaves_the_next_holders_slot(self):
        first = self.start("--", "sleep", "7")
        self.assertTrue(self.admitted(first))
        second = self.start("--", "sleep", "300", env={"MEM_GATE_TTL": "3600"})  # idle too, but must keep its slot
        self.assertTrue(self.admitted(second, 15))
        first.wait(timeout=15)
        self.assertTrue(self.admitted(second, 1), "the first holder's exit freed the second's slot")

    def test_server_lane_is_separate_from_the_gate_lane(self):
        env = {"MEM_GATE_TTL": "3600"}
        gate_holder = self.start("--", "sleep", "300", env=env)
        self.assertTrue(self.admitted(gate_holder))
        self.assertEqual(self.start("--lane", "server", "--", "true", env=env).wait(timeout=10), 0)
        server_holder = self.start("--lane", "server", "--", "sleep", "300", env=env)
        self.assertTrue(self.admitted(server_holder))
        gate = self.start("--", "true", env=env)
        with self.assertRaises(subprocess.TimeoutExpired):
            gate.wait(timeout=3)  # the gate lane's one slot is still the gate holder's
        self.assertTrue(self.admitted(gate_holder, 1))

    def test_server_lane_has_its_own_cap(self):
        env = {"MEM_GATE_TTL": "3600"}
        first = self.start("--lane", "server", "--", "sleep", "300", env=env)
        self.assertTrue(self.admitted(first))
        second = self.start("--lane", "server", "--", "true", env=env)
        with self.assertRaises(subprocess.TimeoutExpired):
            second.wait(timeout=3)

    def test_unknown_lane_is_refused(self):
        r = subprocess.run([GATE, "--lane", "bogus", "--", "true"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_status_shows_holder_age_and_the_queue(self):
        env = {"MEM_GATE_TTL": "3600"}
        holder = self.start("--", "sleep", "300", env=env)
        self.assertTrue(self.admitted(holder))
        self.start("--", "true", env=env)
        time.sleep(2.5)
        out = self.status()
        self.assertRegex(out, r"slot\.1: pid \d+ age \d+s idle \d+s .*sleep 300")
        self.assertRegex(out, r"queue: 1 waiting \(gate 1\), oldest \d+s")

    def test_exit_code_passes_through_and_the_slot_is_freed(self):
        p = self.start("--", "sh", "-c", "exit 7")
        self.assertEqual(p.wait(timeout=10), 7)
        self.assertNotIn("pid", self.status())


if __name__ == "__main__":
    unittest.main()
