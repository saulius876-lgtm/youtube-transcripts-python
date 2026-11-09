"""Download explicit YouTube video IDs once, then reuse successful local transcripts.

Python 3.10+ and apify-client 3.x. Channels, playlists and searches are intentionally
not accepted: discover video IDs upstream, then append them to a file for this step.
"""
import argparse
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlparse

ACTOR = "sauliusautomatesit/youtube-transcript-scraper"
ACTOR_ID = "qdxd1wj9U6iIS8Jtx"
PROFILE = {"transcriptFormat": "clean-text", "languages": ["en"]}
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}


def video_id(value):
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    candidate = None
    if parsed.scheme in {"http", "https"} and host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/")
    elif parsed.scheme in {"http", "https"} and host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] in {"shorts", "embed", "live"}:
                candidate = parts[1]
    if candidate and VIDEO_ID.fullmatch(candidate):
        return candidate
    raise ValueError(f"Expected a single video URL or 11-character ID, got: {value!r}")


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save_state(path, state):
    atomic_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def state_lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise RuntimeError(f"State is locked: {lock}. Stop the other process first. After a crash, confirm it is stopped before removing this lock.") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\n")
        yield path
    finally:
        lock.unlink()


def load_state(path):
    if not path.exists():
        return {"version": 1, "actor": ACTOR, "profile": PROFILE, "successes": {}, "pending": None}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != 1 or state.get("actor") != ACTOR or state.get("profile") != PROFILE:
        raise ValueError("State belongs to a different Actor, profile or version. Use a separate state file.")
    successes = state.get("successes")
    if not isinstance(successes, dict):
        raise ValueError("Invalid state: successes must be a mapping.")
    for key, row in successes.items():
        if not VIDEO_ID.fullmatch(key) or row.get("videoId") != key or row.get("type") != "transcript" or not isinstance(row.get("transcript"), str) or not row["transcript"].strip():
            raise ValueError("Invalid cached transcript; restore the state from backup before continuing.")
    retry_order = state.get("retryOrder", [])
    if (not isinstance(retry_order, list)
            or any(not isinstance(key, str) or not VIDEO_ID.fullmatch(key) for key in retry_order)
            or len(set(retry_order)) != len(retry_order)):
        raise ValueError("Invalid retry order; restore the state from backup before continuing.")
    return state


def validate_export_paths(state_path, out_dir, video_ids):
    """Keep exports from replacing the cache or its writer lock."""
    state = Path(state_path).resolve()
    protected = {state, state.with_name(state.name + ".lock")}
    root = Path(out_dir).resolve()
    targets = [root, root / "transcripts.jsonl"]
    targets.extend(root / (key + ".txt") for key in video_ids)
    if any(target.resolve() in protected for target in targets):
        raise ValueError("Export path would overwrite state or lock; choose separate --state and --out-dir paths.")


def export_cache(state, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [state["successes"][key] for key in sorted(state["successes"])]
    for row in rows:
        atomic_text(out_dir / (row["videoId"] + ".txt"), row["transcript"])
    atomic_text(out_dir / "transcripts.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def make_client(token):
    from apify_client import ApifyClient
    # A retry after an ambiguous POST could start a second paid run. Recovery is explicit.
    return ApifyClient(token, max_retries=0)


def execute(sources, state_path, out_dir, token=None, batch_size=10, max_spend=Decimal("0.05"),
            resume_run=None, client_factory=make_client, exporter=export_cache):
    ids = list(dict.fromkeys(video_id(s) for s in sources))
    if not ids:
        raise ValueError("Provide at least one video ID or URL.")
    if not 1 <= batch_size <= 100 or not Decimal("0") < Decimal(str(max_spend)) <= Decimal("1"):
        raise ValueError("Batch size must be 1-100 and max spend greater than $0 and at most $1.")
    report = {"actorCallsStarted": 0, "cachedBefore": 0, "newTranscripts": 0, "runIds": [], "problems": []}
    # Check requested IDs before creating a lock or any export directory.
    validate_export_paths(state_path, out_dir, ids)
    with state_lock(state_path) as path:
        state = load_state(path)
        # Exports include the full cache, including IDs not requested this time.
        pending_ids = (state.get("pending") or {}).get("videoIds", [])
        validate_export_paths(path, out_dir, set(ids) | set(state["successes"]) | set(pending_ids))
        report["cachedBefore"] = sum(i in state["successes"] for i in ids)
        # Repair/recreate exports before considering any new paid work.
        exporter(state, out_dir)
        missing = [i for i in ids if i not in state["successes"]]
        pending = state.get("pending")
        if resume_run and (not pending or pending.get("runId")):
            raise ValueError("--resume-run is only for an ambiguous pending start with no recorded run ID.")
        if pending or missing:
            if not token:
                raise ValueError("Set APIFY_TOKEN to fetch uncached videos or recover a pending run.")
            client = client_factory(token)
            if pending and not pending.get("runId"):
                if not resume_run:
                    raise RuntimeError("An earlier Actor start is ambiguous. Find its run in Apify Console and use --resume-run RUN_ID. No new run was started.")
                run = client.run(resume_run).get()
                if run is None or run.act_id != ACTOR_ID:
                    raise ValueError("Recovery run does not belong to this Actor.")
                record = client.key_value_store(run.default_key_value_store_id).get_record("INPUT")
                actual = (record or {}).get("value", {})
                if any(actual.get(k) != v for k, v in pending["input"].items()):
                    raise ValueError("Recovery run input does not match the pending request.")
                pending["runId"] = resume_run
                save_state(path, state)
            if not pending:
                # New queue entries get their first attempt before unresolved retries.
                # Among retries, use persisted oldest-attempt-first order.
                ranks = {key: index for index, key in enumerate(state.get("retryOrder", []))}
                selected = sorted(missing, key=lambda key: (key in ranks, ranks.get(key, 0)))[:batch_size]
                run_input = {"videoUrls": selected, **PROFILE}
                pending = {"runId": None, "videoIds": selected, "input": run_input}
                state["pending"] = pending
                # Persist intent before calling the network; never silently retry an uncertain start.
                save_state(path, state)
                run = client.actor(ACTOR).start(run_input=run_input,
                    max_total_charge_usd=Decimal(str(max_spend)), run_timeout=timedelta(minutes=3))
                pending["runId"] = run.id
                save_state(path, state)
                report["actorCallsStarted"] += 1
            report["runIds"].append(pending["runId"])
            run = client.run(pending["runId"]).wait_for_finish(wait_duration=timedelta(minutes=4))
            if run is None or run.status not in TERMINAL:
                raise RuntimeError("Run is not terminal yet. Rerun this command to resume it without starting another run.")
            for row in client.dataset(run.default_dataset_id).iterate_items():
                key = row.get("videoId")
                if row.get("type") == "transcript" and isinstance(row.get("transcript"), str) and row["transcript"].strip():
                    if key not in pending["videoIds"]:
                        raise RuntimeError("Unexpected video in dataset; pending run preserved for inspection.")
                    if key not in state["successes"]:
                        state["successes"][key] = row
                        save_state(path, state)
                        report["newTranscripts"] += 1
                else:
                    report["problems"].append({"videoId": key, "error": row.get("errorDetail") or row.get("error") or "No usable transcript"})
            unfinished = [i for i in pending["videoIds"] if i not in state["successes"]]
            if unfinished:
                report["problems"].append({"notCached": unfinished, "runStatus": str(run.status)})
            # Rotate only after the existing dataset is fully read. An interrupted
            # download keeps its pending run and must recover before any new work.
            attempted = set(pending["videoIds"])
            state["retryOrder"] = [key for key in state.get("retryOrder", [])
                                   if key not in state["successes"] and key not in attempted]
            state["retryOrder"].extend(unfinished)
            state["lastRun"] = {"id": pending["runId"], "status": str(run.status)}
            state["pending"] = None
            save_state(path, state)
            exporter(state, out_dir)
        report["remainingUncached"] = sum(i not in state["successes"] for i in ids)
        report["totalCached"] = len(state["successes"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="*")
    parser.add_argument("--file", help="one video ID or URL per line; blank lines and # comments ignored")
    parser.add_argument("--state", default=".transcript-state/state.json")
    parser.add_argument("--out-dir", default="transcripts-incremental")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-spend", type=Decimal, default=Decimal("0.05"), help="maximum new-run charge in USD, default 0.05; at most one new run per execution")
    parser.add_argument("--resume-run", help="reconcile an ambiguous start with a verified run from Apify Console")
    args = parser.parse_args()
    sources = list(args.sources)
    if args.file:
        sources.extend(line.strip() for line in Path(args.file).read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#"))
    try:
        report = execute(sources, args.state, args.out_dir, os.environ.get("APIFY_TOKEN"),
                         args.batch_size, args.max_spend, args.resume_run)
        print(json.dumps(report, indent=2))
        return 2 if report["problems"] else 0
    except Exception as exc:
        print(f"Stopped: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
