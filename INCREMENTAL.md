# Add transcripts to a corpus without requesting successful videos twice

`transcripts_incremental.py` takes video IDs or individual video URLs from your pipeline, remembers successful transcripts, and submits only uncached IDs to the [YouTube Transcript Scraper](https://apify.com/sauliusautomatesit/youtube-transcript-scraper). Rerunning the same successful inputs reads the local cache and makes **no Actor calls**. I build and maintain that paid Actor.

This is useful when your research queue or content pipeline keeps appending videos to the same input file. It does not discover channels or promise an exhaustive channel history. Use the original `transcripts.py` for one-shot channel/playlist/search exports; a date filter by itself does not prevent overlapping paid requests.

## Run the same video twice

Use Python 3.10+ and the repository's `requirements.txt` (`apify-client` 3.x). Set `APIFY_TOKEN` as described in the main README.

```bash
python transcripts_incremental.py jNQXAC9IVRw
python transcripts_incremental.py https://www.youtube.com/watch?v=jNQXAC9IVRw
```

The first command fetches the transcript. The second recognizes the same video ID, including when its URL spelling differs, and reuses it. The output reports `actorCallsStarted`, `newTranscripts`, `cachedBefore` and `remainingUncached`.

The default locations are:

- `.transcript-state/state.json`: successful transcript rows and recovery state. Preserve this file between executions.
- `transcripts-incremental/`: one `.txt` per cached video plus an aggregate `transcripts.jsonl`.

Exports contain **all cached successful transcripts**, not just the latest additions. Downstream processing should also use `videoId` as its stable key. Deleting an export is recoverable from state; deleting state loses the record of what you already fetched and can cause another paid request.

## Grow a queue over time

Create `videos.txt` with one video ID or URL per line. Blank lines and lines beginning with `#` are ignored. The same video may appear more than once; it is requested at most once in a batch.

```text
# My video queue
jNQXAC9IVRw
https://www.youtube.com/watch?v=aqz-KE-bpKQ
```

```bash
python transcripts_incremental.py --file videos.txt --batch-size 10 --max-spend 0.05
```

Append new video links as your upstream process finds them, then rerun this command. Each execution starts **at most one new Actor run**, with up to 10 uncached IDs by default and a $0.05 maximum new-run charge. If `remainingUncached` is positive, repeat the command to process another batch. Batch size can be 1–100 and the example caps `--max-spend` at $1. These are per-execution controls, not a cumulative monthly budget.

Use one state file per independent corpus and retain it on durable local storage if a scheduler invokes the command. Do not launch overlapping executions against the same state. A stateless job runner that discards this file will lose deduplication. No schedule is installed by this example.

Only explicit single-video URLs and 11-character IDs are accepted. Channel handles, playlist-only URLs, search terms and non-YouTube domains are rejected before a paid request. Watch URLs containing both `v` and `list` select only the video in `v`.

## What is remembered

Only rows identified as transcripts with nonempty text enter the successful cache. No-caption/private/unavailable videos are not marked successful and can be retried on a later execution. The report lists unresolved IDs; a run with unresolved inputs exits with code 2. A failed or missing result is not proof that captions will never become available. If the first batch repeatedly contains unavailable videos, move those IDs to a separate retry file so they do not occupy the next batch again.

This example deliberately uses `clean-text` and English as the preferred language. The Actor may fall back to another available caption language; inspect each row's `language`. It does not refresh already cached captions or detect later edits to a video. Different language/format needs require a separate state and a deliberately adapted profile.

## Recovery without another transcript request

Successful rows are saved atomically to state **before** writing export files. If an export fails, fix the output path or disk issue and rerun the same command. It rebuilds the exports from local state before considering new paid work.

When a run has started, its ID is saved. If polling or dataset downloading fails, rerunning resumes that same run; previously saved successful rows remain cached. Recovery of a remote dataset requires that the run and its storage still exist in your Apify account.

An interrupted start can be ambiguous: Apify may have accepted it even if the response never reached your computer. The script disables automatic HTTP retries and saves an intent before starting. In that case it stops instead of automatically creating another paid run. Find the matching run in Apify Console and reconcile it:

```bash
python transcripts_incremental.py --file videos.txt --resume-run RUN_ID_FROM_CONSOLE
```

The script checks the Actor and the original run input before accepting that run. If Console has no matching run, inspect the failed attempt before changing its pending state; the script does not guess whether the request was accepted.

A `.lock` beside the state prevents a second process from writing the same state. After a hard crash, it may remain. Confirm that the previous process is stopped before removing that lock and rerunning. Do not remove or replace the state file to clear a lock.

Keep state and transcripts private as appropriate for your content. State contains downloaded text and run references, never your API token. The default state/export paths are ignored by Git. If you choose custom paths, add those paths to your own ignore rules. Local disk corruption, deleted state and external edits cannot be repaired by this script; back up important corpora.

## Price and verification

Live prices checked 31 October 2026: **$0.0025 per delivered transcript ($2.50 per 1,000)** on the Apify free plan, with 5–15% discounts on paid plans. Actor start is **$0.00005 per GB of run memory, minimum one event**. Diagnostic rows without transcripts have no transcript charge; a run can still have its start charge. If all requested IDs are already successfully cached and there is no pending run, this script makes no Actor call, so there is no new Actor charge.

The existing Actor's pricing was not changed. See [INCREMENTAL-VALIDATION.md](INCREMENTAL-VALIDATION.md) for the actual live repeat-run check and offline failure tests.
