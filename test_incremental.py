"""Offline recovery checks. Run: python -m unittest -v test_incremental.py"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import transcripts_incremental as app

A, B = "jNQXAC9IVRw", "aqz-KE-bpKQ"


def transcript(key):
    return {"type": "transcript", "videoId": key, "transcript": "A usable caption.", "language": "en"}


class FakeClient:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [transcript(A)]
        self.starts = 0
        self.interrupt_dataset = False
        self.start_error = False
        self.run_value = SimpleNamespace(id="test-run", status="SUCCEEDED", default_dataset_id="test-dataset",
                                         act_id=app.ACTOR_ID, default_key_value_store_id="test-store")
        self.input = None

    def actor(self, actor):
        assert actor == app.ACTOR
        return self

    def start(self, **kwargs):
        self.starts += 1
        self.input = kwargs["run_input"]
        if self.start_error:
            raise TimeoutError("simulated ambiguous POST response")
        return self.run_value

    def run(self, run_id):
        return self

    def get(self):
        return self.run_value

    def wait_for_finish(self, **kwargs):
        return self.run_value

    def key_value_store(self, key):
        return self

    def get_record(self, key):
        return {"value": self.input}

    def dataset(self, dataset_id):
        return self

    def iterate_items(self):
        for index, row in enumerate(self.rows):
            yield row
            if index == 0 and self.interrupt_dataset:
                raise ConnectionError("simulated interrupted dataset download")


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state.json"
        self.out = Path(self.tmp.name) / "out"
        self.client = FakeClient()

    def execute(self, sources=None, **kwargs):
        return app.execute(sources or [A], self.state, self.out, "not-a-real-token",
                           client_factory=lambda token: self.client, **kwargs)

    def test_successful_id_not_submitted_again(self):
        self.assertEqual(self.execute()["newTranscripts"], 1)
        result = self.execute([A, "https://youtu.be/" + A])
        self.assertEqual(result["actorCallsStarted"], 0)
        self.assertEqual(self.client.starts, 1)

    def test_export_failure_recovers_without_another_actor_start(self):
        calls = 0
        def fail_after_fetch(state, out):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated disk export failure")
            app.export_cache(state, out)
        with self.assertRaises(OSError):
            self.execute(exporter=fail_after_fetch)
        self.assertIn(A, json.loads(self.state.read_text())["successes"])
        result = self.execute()
        self.assertEqual(result["actorCallsStarted"], 0)
        self.assertEqual(self.client.starts, 1)
        self.assertEqual((self.out / (A + ".txt")).read_text(), "A usable caption.")

    def test_interrupted_dataset_resumes_existing_run(self):
        self.client.rows = [transcript(A), transcript(B)]
        self.client.interrupt_dataset = True
        with self.assertRaises(ConnectionError):
            self.execute([A, B])
        state = json.loads(self.state.read_text())
        self.assertIn(A, state["successes"])
        self.assertEqual(state["pending"]["runId"], "test-run")
        self.client.interrupt_dataset = False
        result = self.execute([A, B])
        self.assertEqual(result["actorCallsStarted"], 0)
        self.assertEqual(result["totalCached"], 2)
        self.assertEqual(self.client.starts, 1)

    def test_ambiguous_start_never_automatically_restarts(self):
        self.client.start_error = True
        with self.assertRaises(TimeoutError):
            self.execute()
        self.client.start_error = False
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.execute()
        self.assertEqual(self.client.starts, 1)
        self.assertEqual(self.execute(resume_run="test-run")["newTranscripts"], 1)
        self.assertEqual(self.client.starts, 1)

    def test_wrong_recovery_input_rejected(self):
        self.client.start_error = True
        with self.assertRaises(TimeoutError):
            self.execute()
        self.client.input = {"videoUrls": [B], **app.PROFILE}
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.execute(resume_run="different-run")
        self.assertIsNone(json.loads(self.state.read_text())["pending"]["runId"])

    def test_failed_rows_not_marked_successful_and_can_retry(self):
        self.client.rows = [{"type": "error", "videoId": A, "error": "NO_CAPTIONS"}]
        self.assertEqual(self.execute()["totalCached"], 0)
        self.client.rows = [transcript(A)]
        self.assertEqual(self.execute()["newTranscripts"], 1)
        self.assertEqual(self.client.starts, 2)

    def test_lock_rejects_second_writer(self):
        with app.state_lock(self.state):
            with self.assertRaisesRegex(RuntimeError, "locked"):
                self.execute()
        self.assertEqual(self.client.starts, 0)

    def test_channels_and_non_youtube_urls_rejected_before_network(self):
        for source in ["https://www.youtube.com/@apify", "https://example.org/watch?v=" + A,
                       "https://www.youtube.com/playlist?list=abc"]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.execute([source])
        self.assertEqual(self.client.starts, 0)

    def test_empty_success_row_is_not_cached(self):
        self.client.rows = [{"type": "transcript", "videoId": A, "transcript": ""}]
        self.assertEqual(self.execute()["totalCached"], 0)

    def test_one_bounded_batch_per_execution(self):
        result = self.execute([A, B], batch_size=1)
        self.assertEqual(result["remainingUncached"], 1)
        self.assertEqual(self.client.input["videoUrls"], [A])
        self.assertEqual(self.client.starts, 1)


if __name__ == "__main__":
    unittest.main()
