# Get readable YouTube transcripts in your browser

Paste a video or playlist link into Apify, choose readable paragraphs, and export the results. You need a browser and an Apify account. There is no Python setup, terminal command or browser extension to install.

This guide uses the [YouTube Transcript Scraper](https://apify.com/sauliusautomatesit/youtube-transcript-scraper). I build and maintain that paid Actor. Check its [current pricing](https://apify.com/sauliusautomatesit/youtube-transcript-scraper/pricing) before running a large playlist.

## Start with a small batch

1. Open the Actor page and select **Try for free**. Sign in or create your Apify account if prompted, then open the Actor's **Input** form.
2. Under **Videos, channels, playlists, or searches**, remove the prefilled example links. Paste your own video link, or one playlist link. For a playlist, use its full `youtube.com/playlist?list=PLAYLIST_ID` link.
3. Set **Transcript format** to **Clean text (paragraphs)**. The default, **Plain text (raw)**, keeps YouTube's fragmented caption text joined together.
4. For the first try, set **Max videos per channel/playlist/search** to **3** and **Max videos total** to **3**. The first limit applies to each source; the second caps the whole run. These are maximums, not a guarantee that every requested video has captions.
5. In **Run options**, set **Maximum cost per run** instead of leaving it unlimited, then select **Start** (or **Save & start** in the developer view). A charge cap can stop the run before it has collected every requested transcript.
6. When the run finishes, open **Output** and the **Transcripts** view. Check **Row type** and **Error** if a video has no text. A successful run can contain videos that had no usable captions.
7. Preview a video's text in the **Transcript** column. To save the full batch, select **Export**, choose **CSV** or **Excel**, then **Download**. The export contains data rows, including the transcript column; it is not a separate text document for every video.

Keep the run page available if you want to download again later. Exporting an existing result does not require starting another transcript run.

## What the cleanup does

**Clean text (paragraphs)** removes sound cues such as `[Music]` and groups the caption words into paragraphs around pauses or the paragraph-size limit. It adds basic paragraph capitalization and a closing full stop.

It does **not** rewrite sentences, correct names or transcription mistakes, or restore missing punctuation inside sentences. If YouTube's automatic captions misheard a word, the export can contain the same mistake. Existing punctuation from manual captions is retained. Review the wording before quoting or publishing it.

For timed output, choose **Chunks with timings (JSON)** for paragraph-sized blocks with start/end times, or one of the subtitle formats. These are different representations of the captions, not a more accurate transcription.

## Avoid paying for the same playlist twice

Starting the same playlist again can return and charge for the same delivered transcripts again. This browser workflow does not remember which videos you already downloaded.

- To download the same results again, return to the completed run and export its existing output.
- For a later batch, paste only the video links you still need, or deliberately choose another source. Keep your own record of completed video IDs.
- **Only videos uploaded after** filters channels and searches; it does not filter playlist or individual-video inputs. An overlapping date window also does not deduplicate separate runs.

Videos without captions produce a diagnostic row rather than a transcript charge. A run still has its start charge. Language availability also varies: check the **Language** column to see which caption language was returned.

The browser does not need to stay open to do the scraping: the Actor runs on Apify. Keep access to your account and completed run to retrieve its output later.
