"""Download YouTube transcripts in bulk: videos, whole channels, playlists or search terms.

    python transcripts.py https://www.youtube.com/@veritasium --max-per-source 50 --since "30 days"
    python transcripts.py --file videos.txt --format srt

Writes one file per video to transcripts/ and every row to transcripts/transcripts.jsonl.
"""
import argparse
from contextlib import contextmanager
import json
import os
import sys
import tempfile

from apify_client import ApifyClient

ACTOR = "sauliusautomatesit/youtube-transcript-scraper"
ACTOR_ID = "qdxd1wj9U6iIS8Jtx"
FORMATS = ["text", "clean-text", "segments", "chunks", "srt", "vtt"]
EXTENSIONS = {"srt": ".srt", "vtt": ".vtt", "segments": ".json", "chunks": ".json"}



@contextmanager
def atomic_output(path):
    """Replace one export only after its complete contents reach disk."""
    fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp",
                                     dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*", help="video links or IDs, channel links (@handle), playlist links or search terms")
    parser.add_argument("--file", help="text file with one source per line")
    parser.add_argument("--format", choices=FORMATS, default=None,
                        help="clean-text (default) has paragraphs and no [Music] cues; chunks adds start and end seconds")
    parser.add_argument("--lang", nargs="+", default=None, help="language codes in order of preference (default en)")
    parser.add_argument("--max-per-source", type=int, default=None, help="most videos per channel, playlist or search (default 50)")
    parser.add_argument("--since", help='only videos uploaded after a date (2026-10-01) or within an age ("7 days")')
    parser.add_argument("--out-dir", default="transcripts")
    parser.add_argument("--max-spend", type=float, default=1.0, help="hard spending cap for the run in USD (default 1)")
    parser.add_argument("--resume-run", help="export an existing successful run without starting another Actor run")
    args = parser.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN first (Apify Console > Settings > API & Integrations).")

    if args.resume_run and (args.sources or args.file or args.since or args.lang is not None or args.max_per_source is not None):
        parser.error("--resume-run uses the original run input; omit sources, --file, --since, --lang and --max-per-source.")

    client = ApifyClient(token)
    if args.resume_run:
        run = client.run(args.resume_run).get()
        if run is None or run.id != args.resume_run or run.act_id != ACTOR_ID:
            sys.exit("Recovery run was not found or does not belong to this YouTube Actor.")
        if run.status != "SUCCEEDED":
            sys.exit(f"Recovery requires a SUCCEEDED run; found {run.status}. Inspect partial output in Console.")
        record = client.key_value_store(run.default_key_value_store_id).get_record("INPUT")
        original = (record or {}).get("value")
        output_format = original.get("transcriptFormat", "text") if isinstance(original, dict) else None
        if output_format not in FORMATS:
            sys.exit("Cannot establish the original transcript format; keep the run and inspect its INPUT in Console.")
        if args.format is not None and args.format != output_format:
            sys.exit("An existing run cannot be reformatted; omit --format or use its original format.")
        print(f"Exporting existing run {run.id}; no new Actor run started.")
    else:
        sources = list(args.sources)
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                sources += [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not sources:
            parser.error("Give at least one video, channel, playlist or search term, or --resume-run RUN_ID.")
        output_format = args.format or "clean-text"
        run_input = {"videoUrls": sources, "transcriptFormat": output_format,
                     "languages": args.lang if args.lang is not None else ["en"],
                     "maxVideosPerSource": args.max_per_source if args.max_per_source is not None else 50}
        if args.since:
            run_input["publishedAfter"] = args.since
        run = client.actor(ACTOR).call(run_input=run_input, max_total_charge_usd=args.max_spend, logger=None)
        if run is None or run.status != "SUCCEEDED":
            sys.exit(f"Run did not succeed: {run.status if run else 'not found'}")
        print(f"Run {run.id}; keep this ID to export again with --resume-run.")

    os.makedirs(args.out_dir, exist_ok=True)
    saved = 0
    with atomic_output(os.path.join(args.out_dir, "transcripts.jsonl")) as jsonl:
        for item in client.dataset(run.default_dataset_id).iterate_items():
            jsonl.write(json.dumps(item, ensure_ascii=False) + "\n")
            if item.get("type") != "transcript":
                # No captions, private video and similar: these rows are free.
                reason = item.get("errorDetail") or item.get("error")
                print(f"skipped {item.get('videoId') or item.get('sourceInput')}: {reason}")
                continue
            body = item["transcript"]
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False, indent=1)
            path = os.path.join(args.out_dir, item["videoId"] + EXTENSIONS.get(output_format, ".txt"))
            with atomic_output(path) as f:
                f.write(body)
            saved += 1
            print(f"{item['videoId']}  {item.get('language')}  {item.get('wordCount', 0):>6} words  {item.get('title', '')[:60]}")

    print(f"\n{saved} transcripts saved to {args.out_dir}/")


if __name__ == "__main__":
    main()
