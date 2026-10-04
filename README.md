# Video summaries

Turns a YouTube video into what you need to summarize it story by story, without relying on
YouTube's own captions:

- **A transcript with timestamps,** made on your own computer from the video's sound.
- **Screen grabs,** one each time the picture changes, tiled 12 to a page with their times printed.
  They show names and places as spelled on screen, which the sound alone often gets wrong.

Give both to Claude (or read them yourself) to write a title, a short summary, and start and end
times for each story.

This is an early test. It isn't an official FreeOT product.

## Set it up (Windows 10 or 11)

Open **PowerShell** (press the Windows key, type `PowerShell`, press Enter) and paste:

```powershell
irm https://raw.githubusercontent.com/freeot-git/video-summaries/main/install.ps1 | iex
```

This installs two free tools if you don't have them (**ffmpeg**, for video and sound, and **uv**,
which sets up Python), then puts this project in a `video-summaries` folder in your user folder.
Expect about 3 GB of downloads in total, including the speech model on the first run.

An NVIDIA graphics card makes it fast: a 10-minute video takes under a minute. Without one it
still works, using the computer's processor instead, but expect a few minutes for the same video.

## Use it

```powershell
cd ~\video-summaries
uv run process.py "https://www.youtube.com/watch?v=..."
```

Everything for that video lands in `out\<video id>\`:

| File | What it is |
|---|---|
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
- To update everything, run the setup command again. Your `out` folder is kept.

## Please note

Downloading from YouTube is against YouTube's terms of service. Use this only for testing and
for videos you have the right to use.
