# Video summaries

Turns a YouTube video into a story-by-story summary, without relying on YouTube's own captions
or any online AI service. Everything runs on your own computer:

- **A summary:** each story's title, start and end times, and two or three sentences on it.
- **A transcript with timestamps,** made from the video's sound.
- **Screen grabs,** one each time the picture changes, tiled 12 to a page with their times printed.
  They show names and places as spelled on screen, which the sound alone often gets wrong.

The summary is written by a small AI model running on your computer, so check names and details
against the transcript and screen grabs before you rely on them.

This is an early test. It isn't an official FreeOT product.

## Set it up (Windows 10 or 11)

Open **PowerShell** (press the Windows key, type `PowerShell`, press Enter) and paste:

```powershell
irm https://raw.githubusercontent.com/freeot-git/video-summaries/main/install.ps1 | iex
```

This installs three free tools if you don't have them (**ffmpeg**, for video and sound, **uv**,
which sets up Python, and **Ollama**, which runs the summary model), then puts this project in a
`video-summaries` folder in your user folder. Expect about 6.5 GB of downloads in total, including
the speech and summary models on the first run.

An NVIDIA graphics card makes it fast. Without one it still works, using the computer's processor
instead: a 10-minute video took about 5 minutes on a 2022 laptop.

## Use it

```powershell
cd ~\video-summaries
uv run process.py "https://www.youtube.com/watch?v=..."
```

Everything for that video lands in `out\<video id>\`:

| File | What it is |
|---|---|
| `summary.txt` | Each story's title, start and end times, and a short summary |
| `summary.md` | The same, formatted for viewers that show Markdown |
| `transcript.txt` | What was said, one line per sentence or two, with start and end times |
| `transcript.json` | The same, for other programs to read |
| `sheets\` | The screen grabs, 12 to a page, each labeled with its time |
| `frames\` | The same screen grabs one by one, at full size |
| `video.mp4` | The downloaded video |

## If something stops working

- **Downloads fail with an error from yt-dlp:** YouTube changes things often, and yt-dlp catches up
  quickly. Update it from the `video-summaries` folder:
  `uv lock --upgrade-package yt-dlp; uv sync`
- **"ffmpeg isn't recognized":** close PowerShell, open a new window and try again.
- **"Summary failed":** make sure Ollama is running (open it from the Start menu), then run the
  same command again.
- To update everything, run the setup command again. Your `out` folder is kept.

## Please note

Downloading from YouTube is against YouTube's terms of service. Use this only for testing and
for videos you have the right to use.
