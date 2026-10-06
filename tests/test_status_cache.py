import sys, threading, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_board as ab


class StatusCacheTest(unittest.TestCase):
    def setUp(self):
        ab.invalidate_status()
        self.calls = 0
        self.orig = ab.status

        def fake(hours):
            self.calls += 1
            time.sleep(0.2)
            return {"n": self.calls}
        ab.status = fake

    def tearDown(self):
        ab.status = self.orig
        ab.invalidate_status()

    def test_concurrent_requests_share_one_build(self):
        ts = [threading.Thread(target=ab.cached_status, args=(168,)) for _ in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(self.calls, 1)

    def test_invalidate_forces_rebuild(self):
        ab.cached_status(168)
        ab.invalidate_status()
        ab.cached_status(168)
        self.assertEqual(self.calls, 2)


if __name__ == "__main__":
    unittest.main()
