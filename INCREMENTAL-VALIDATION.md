# Incremental transcript example validation

Checked 31 October 2026 with Python 3.12.10 and `apify-client` 3.4.0 against live YouTube Transcript Scraper build 1.0.41.

| Check | Outcome |
|---|---|
| Execute the CLI with one uncached public video | One Actor run; one nonempty transcript cached and exported |
| Execute the same CLI again with `APIFY_TOKEN` removed | Zero Actor calls; cached transcript exported successfully |
| Export failure after a fetched transcript, then retry | Offline test: cache preserved; export recovered; no second Actor start |
| Dataset download interrupted after one success | Offline test: existing run resumed; first success preserved; no second Actor start |
| Actor-start request has an ambiguous response | Offline test: another start blocked; explicit matching-run recovery succeeds |
| Wrong recovery run input | Offline test: rejected before changing the pending run ID |
| No-caption/error or empty transcript row | Offline test: not marked successful; later retry remains possible |
| Concurrent state writer | Offline test: second writer rejected before network access |
| Channel/playlist-only/non-YouTube input | Offline test: rejected before network access |
| Input exceeds batch size | Offline test: one bounded batch starts; remaining IDs reported |

Ten offline tests passed:

```bash
python -m unittest -v test_incremental.py
```

Offline tests use a fake API client and do not spend Apify credit. They simulate failure boundaries; they do not establish resilience to disk corruption or every operating-system crash. The live check confirms successful fetch followed by a genuinely offline repeat, not long-term availability for all YouTube videos.

Pricing checked through the live Actor API: FREE transcript $0.0025; Bronze $0.002375; Silver $0.00225; Gold/Platinum/Diamond $0.002125; Actor start $0.00005 per GB of memory, minimum one event. Owner test compute usage is separate from customer event charges.

Sources: [Actor pricing](https://apify.com/sauliusautomatesit/youtube-transcript-scraper/pricing), [official Python client v3 migration](https://docs.apify.com/api/client/python/docs/upgrading-to-v3).
