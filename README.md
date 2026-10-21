# SRT Media Planner

Python CLI that reads an SRT, creates a Vietnamese summary and scene plan, estimates the number of images/video clips, then searches and downloads media into organized folders.

## Requirements

- Python 3.10 or newer
- Internet access
- A Pexels or Pixabay API key (the program cannot search/download from these catalogs without a key)
- No Python package installation is required; the downloader uses Python's standard library.

Pexels offers photo and video search APIs. Pixabay is supported as an alternative. Keep keys private and set them as environment variables; do not commit them.

## Setup (Windows PowerShell)

```powershell
cd "C:\path\to\srt-media-planner"
Copy-Item .env.example .env
notepad .env
```

Put a key in `PEXELS_API_KEY` or `PIXABAY_API_KEY`. The application reads `.env` itself; no dotenv package is needed. Pexels is preferred when both keys exist.

## Run

```powershell
python srt_media.py "D:\Video Edit - Output\Test\Bài 93\bai 93.srt"
```

Output is created beside the SRT in `bai 93_media/` by default. To choose another location or only produce the content plan:

```powershell
python srt_media.py "D:\path\video.srt" --output "D:\Media\video" --plan-only
```

## Output structure

```text
<name>_media/
  00_summary_vi.md
  01_scene_plan.csv
  02_download_manifest.csv
  images/
  videos/
```

The CSV scene plan contains approximate edit times and a search query for each asset. Actual downloaded counts are recorded in the manifest. Searches may return fewer usable assets than requested because catalog results vary by topic and API limits.

## Estimate rules

The image target alone covers the full video at one image every 3 seconds. Video downloads are bonus footage, capped at 10% of the image target by default. A long clip can be split into several 3-second inserts during editing, so video duration does not reduce the image backup count. For an 11:29 source, that is about 230 images and 23 clips. Override with `--image-seconds` or `--video-ratio`.

The script groups captions into roughly 20-second windows, derives concise English search phrases from the spoken text, and adds source-specific search results while avoiding duplicate downloads. It saves source, creator, and license/attribution information in the manifest where the provider exposes it. Review provider terms and each asset's reuse conditions before publishing.

## Providers and API keys

- Pexels: set `PEXELS_API_KEY`. Photos and videos share the same key.
- Pixabay: set `PIXABAY_API_KEY`. It is used when a Pexels key is absent.

Official setup pages: [Pexels API documentation](https://www.pexels.com/api/documentation/) · [Pixabay API documentation](https://pixabay.com/api/docs/).

If the API returns an error, check the key, network, provider rate limits, and whether new keys are currently available. The content plan is still generated even without a key.
