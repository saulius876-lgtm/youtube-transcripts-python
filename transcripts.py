"""Download YouTube transcripts in bulk: videos, whole channels, playlists or search terms.

    python transcripts.py https://www.youtube.com/@veritasium --max-per-source 50 --since "30 days"
    python transcripts.py --file videos.txt --format srt

Writes one file per video to transcripts/ and every row to transcripts/transcripts.jsonl.
"""
import argparse
import json
import os
import sys

from apify_client import ApifyClient

ACTOR = "sauliusautomatesit/youtube-transcript-scraper"
FORMATS = ["text", "clean-text", "segments", "chunks", "srt", "vtt"]
EXTENSIONS = {"srt": ".srt", "vtt": ".vtt", "segments": ".json", "chunks": ".json"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*", help="video links or IDs, channel links (@handle), playlist links or search terms")
    parser.add_argument("--file", help="text file with one source per line")
    parser.add_argument("--format", choices=FORMATS, default="clean-text",
                        help="clean-text (default) has paragraphs and no [Music] cues; chunks adds start and end seconds")
    parser.add_argument("--lang", nargs="+", default=["en"], help="language codes in order of preference (default en)")
    parser.add_argument("--max-per-source", type=int, default=50, help="most videos per channel, playlist or search (default 50)")
    parser.add_argument("--since", help='only videos uploaded after a date (2026-10-01) or within an age ("7 days")')
    parser.add_argument("--out-dir", default="transcripts")
    parser.add_argument("--max-spend", type=float, default=1.0, help="hard spending cap for the run in USD (default 1)")
    args = parser.parse_args()

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN first (Apify Console > Settings > API & Integrations).")

    sources = list(args.sources)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            sources += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if not sources:
        sys.exit("Give at least one video, channel, playlist or search term.")

    run_input = {
        "videoUrls": sources,
        "transcriptFormat": args.format,
        "languages": args.lang,
        "maxVideosPerSource": args.max_per_source,
    }
    if args.since:
        run_input["publishedAfter"] = args.since

    client = ApifyClient(token)
    run = client.actor(ACTOR).call(run_input=run_input, max_total_charge_usd=args.max_spend, logger=None)
    if run is None or run.status != "SUCCEEDED":
        sys.exit(f"Run did not succeed: {run.status if run else 'not found'}")

    os.makedirs(args.out_dir, exist_ok=True)
    saved = 0
    with open(os.path.join(args.out_dir, "transcripts.jsonl"), "w", encoding="utf-8") as jsonl:
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
            path = os.path.join(args.out_dir, item["videoId"] + EXTENSIONS.get(args.format, ".txt"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            saved += 1
            print(f"{item['videoId']}  {item.get('language')}  {item.get('wordCount', 0):>6} words  {item.get('title', '')[:60]}")

    print(f"\n{saved} transcripts saved to {args.out_dir}/")


if __name__ == "__main__":
    main()
