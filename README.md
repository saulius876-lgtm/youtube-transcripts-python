# Bulk YouTube transcripts in Python: channels, playlists and searches, even from a server

`transcripts.py` downloads YouTube transcripts for single videos, **whole channels**, playlists and
search terms, and saves one file per video as plain text, paragraphs for LLMs, timestamped chunks
for RAG, or SRT/VTT subtitles.

For a recurring queue of known video URLs, **[`transcripts_incremental.py`](INCREMENTAL.md)**
remembers successful transcripts before the next request, exports from local state, and skips
paid Actor calls when every requested video is already cached. [Repeat-run walkthrough](INCREMENTAL.md).

It exists because of this error. A transcript script that works on a laptop often fails as soon as it
runs on AWS, GCP, Azure, Render, Railway, Vercel, Hugging Face Spaces or Colab:

```text
youtube_transcript_api._errors.RequestBlocked:
Could not retrieve a transcript for the video https://www.youtube.com/watch?v=jNQXAC9IVRw!
This is most likely caused by:

YouTube is blocking requests from your IP. This usually is due to one of the following reasons:
- You have done too many requests and your IP has been blocked by YouTube
...
```

or `IpBlocked`, or a `429`. YouTube does not block the library; it blocks the network the request
comes from, and data center IP ranges get refused quickly. Your code is fine, and upgrading the
library will not fix it.

## The free options first

- **Small volume:** run the transcript step on a machine with a home connection (an old laptop or a
  Raspberry Pi) and send the text to your server. Free; a home IP can still get rate limited at
  thousands of requests a day.
- **You like running infrastructure:** `youtube-transcript-api` takes a proxy config. With
  residential proxies plus your own retries, channel expansion and no-captions handling, it works.

```python
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig

api = YouTubeTranscriptApi(proxy_config=GenericProxyConfig(
    http_url="http://user:pass@proxy.example.com:8000",
    https_url="http://user:pass@proxy.example.com:8000",
))
print(api.fetch("jNQXAC9IVRw").snippets[:3])
```

## The hosted option this repo uses

`transcripts.py` calls the
[YouTube Transcript Scraper](https://apify.com/sauliusautomatesit/youtube-transcript-scraper) on
Apify. It runs on Apify's servers with proxies included, expands channels, playlists and searches to
videos, and returns one row per video. Disclosure: I build and maintain that Actor. It is pay per
transcript (prices below), and every run has a spending cap.

### Setup

```bash
git clone https://github.com/saulius876-lgtm/youtube-transcripts-python
cd youtube-transcripts-python
pip install -r requirements.txt
export APIFY_TOKEN=your_token   # Windows PowerShell: $env:APIFY_TOKEN="your_token"
```

The token is in [Apify Console](https://console.apify.com/settings/integrations) under
Settings > API & Integrations. A free Apify account works.

### A video and a whole channel

```bash
python transcripts.py jNQXAC9IVRw https://www.youtube.com/@apify --max-per-source 3
```

Output from a real run on 27 Oct 2026:

```text
6pz9Jg680gw  en     706 words  Your AI Agent Can't Reach This Page? Try Apify Web Fetch
e6My6S_QFJk  en    1031 words  I Built a LinkedIn Lead Scraper with Claude Code + Apify
jNQXAC9IVRw  en      39 words  Me at the zoo
SRMUijiQ9Mo  en    1369 words  Apify Plugin for ChatGPT & Codex: Build a Shopping Assistant

4 transcripts saved to transcripts/
```

`transcripts/jNQXAC9IVRw.txt`:

```text
All right, so here we are, in front of the elephants the cool thing about these guys is that they
have really... really really long trunks and that's cool (baaaaaaaaaaahhh!!) and that's pretty much
all there is to say.
```

Every row, with title, channel, length, view count, language and the other caption languages
available, is also in `transcripts/transcripts.jsonl`. A video that cannot give a transcript is
reported and not charged:

```text
skipped xxxxxxxxxxx: This video is unavailable
```

### More examples

```bash
# The last 30 days of a channel
python transcripts.py https://www.youtube.com/@veritasium --since "30 days" --max-per-source 100

# Search results from the last week as SRT subtitles
python transcripts.py "python tutorial" --since "7 days" --max-per-source 20 --format srt

# A list of links from a file, Spanish first, English as a fallback
python transcripts.py --file videos.txt --lang es en
```

### Formats

| `--format` | File | Use it for |
|---|---|---|
| `clean-text` (default) | `.txt`, sound cues removed, paragraphs at pauses | LLM prompts, reading |
| `text` | `.txt`, caption lines joined as YouTube sends them | your own cleanup |
| `chunks` | `.json`, paragraphs with `start`, `end`, `wordCount` | RAG, embeddings, timestamped citations |
| `segments` | `.json`, every caption line with `start` and `duration` | timing analysis |
| `srt`, `vtt` | `.srt`, `.vtt` subtitle files | players, editors |

`chunks` from the same video:

```json
[
 {
  "text": "All right, so here we are, in front of the elephants the cool thing about these guys is ...",
  "start": 1.2,
  "end": 18.881,
  "wordCount": 39
 }
]
```

Each chunk's `start` links straight back to the moment: `https://www.youtube.com/watch?v=jNQXAC9IVRw&t=1s`.

## Calling it from your own code

```python
from apify_client import ApifyClient

client = ApifyClient("YOUR_APIFY_TOKEN")
run = client.actor("sauliusautomatesit/youtube-transcript-scraper").call(
    run_input={
        "videoUrls": ["https://www.youtube.com/@apify", "jNQXAC9IVRw"],
        "transcriptFormat": "clean-text",
        "maxVideosPerSource": 50,
    },
    max_total_charge_usd=1,      # the run stops charging at $1
)
for item in client.dataset(run.default_dataset_id).iterate_items():
    if item["type"] == "transcript":
        print(item["videoId"], item["title"], item["wordCount"])
```

This is `apify-client` 3.x, where `call()` returns a `Run` object. On 1.x and 2.x use
`run["defaultDatasetId"]`. From any other language, POST the same input to
`https://api.apify.com/v2/acts/sauliusautomatesit~youtube-transcript-scraper/run-sync-get-dataset-items`
with an `Authorization: Bearer <token>` header and the rows come back in the response.

## Repeated runs without requesting successful videos again

```bash
python transcripts_incremental.py jNQXAC9IVRw
python transcripts_incremental.py jNQXAC9IVRw
```

The first execution fetches and caches the transcript. The second reads the cache without an
Actor call. Use `--file videos.txt` for an input queue and retain `.transcript-state/state.json`
between executions. This workflow accepts explicit videos, not channel discovery. It saves
successful rows before exporting so an export failure can be retried without another transcript
request. The default is one batch of 10 uncached videos, with a $0.05 new-run cap.

See [INCREMENTAL.md](INCREMENTAL.md) for bounded batches, recovery and coverage limits;
[validation](INCREMENTAL-VALIDATION.md) includes a live fetch followed by a repeat with no API token.

## What it costs

Prices checked 31 Oct 2026: **$2.50 per 1,000 transcripts** ($0.0025 each) on Apify's free plan,
5% to 15% less on paid plans, plus Actor start at $0.00005 per GB of run memory (minimum one event). Videos without captions have no transcript charge. Apify's free
plan includes $5 of usage a month, about 2,000 transcripts.

| Job | Roughly |
|---|---:|
| 100-video playlist | $0.25 |
| 1,000-video channel backfill | $2.50 |
| 20,000-video corpus | $50 |

At very high volume your own proxies cost less per request and more of your time.

## Notes

- To pick up new uploads every day, run the script from cron with `--since "1 day"`, or save the
  input as a Task in Apify Console and give it a schedule. Deduplicate on `videoId` before requesting already-successful transcripts again; a date window alone does not prevent overlapping requests. For explicit video queues, use the incremental script above.
- Auto-generated captions are used when a video has no manual ones (`isAutoGenerated` says which).
  When none of your `--lang` codes exists, the best available language is used; the `language`
  column says what you got.
- A video the Actor cannot read: open an issue here with the video ID.

MIT licensed.
