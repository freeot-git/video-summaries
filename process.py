"""Turn a video link into what's needed to summarize it without a published transcript.

    uv run process.py <youtube-url>

Writes to out/<video-id>/:
    video.mp4        the downloaded video (720p at most)
    transcript.txt   our own speech-to-text, one timestamped line per segment
    transcript.json  the same, with start/end seconds
    frames/          a still each time the picture changes, named by its time
    sheets/          those stills tiled 4x3 with their times printed, for quick review
"""

import json
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCENE_THRESHOLD = 0.3  # how big a picture change counts as a new shot (0-1)
SHEET_COLS, SHEET_ROWS, THUMB_W = 4, 3, 480
WHISPER_MODEL = "large-v3-turbo"


def add_winget_links():
    """winget puts ffmpeg here; a window opened before the install won't have it on PATH yet."""
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    if links.is_dir():
        os.environ["PATH"] = f"{os.environ['PATH']}{os.pathsep}{links}"


def add_gpu_dll_dirs():
    """The nvidia-* wheels ship their DLLs inside site-packages; Windows won't find them otherwise."""
    nvidia = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for bin_dir in nvidia.glob("*/bin"):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def stamp(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def download(url, out_dir):
    video = out_dir / "video.mp4"
    if not video.exists():
        subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "-f", "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720]",
                "--merge-output-format", "mp4",
                "--write-info-json",
                "-o", str(out_dir / "video.%(ext)s"),
                url,
            ],
            check=True,
        )
    return video


def load_audio(video):
    """16 kHz mono samples via ffmpeg. faster-whisper's own reader (PyAV) breaks across versions."""
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def transcribe(video, out_dir):
    add_gpu_dll_dirs()
    from faster_whisper import WhisperModel

    model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type="float16")
    segments, info = model.transcribe(load_audio(video), vad_filter=True, beam_size=5)
    rows = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]

    (out_dir / "transcript.json").write_text(
        json.dumps({"language": info.language, "duration": info.duration, "segments": rows}, indent=2),
        encoding="utf-8",
    )
    lines = [f"[{stamp(r['start'])} - {stamp(r['end'])}] {r['text']}" for r in rows]
    (out_dir / "transcript.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def grab_frames(video, out_dir):
    frames = out_dir / "frames"
    frames.mkdir(exist_ok=True)
    for old in frames.glob("*.jpg"):
        old.unlink()
    # Always keep the first frame, then one per shot change. showinfo logs each kept frame's time.
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y", "-i", str(video),
            "-vf", f"select='eq(n,0)+gt(scene,{SCENE_THRESHOLD})',showinfo",
            "-fps_mode", "vfr", "-q:v", "3",
            str(frames / "tmp_%05d.jpg"),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", result.stderr)]
    named = []
    for i, t in enumerate(times, start=1):
        src = frames / f"tmp_{i:05}.jpg"
        dst = frames / f"{int(t // 60):02}m{t % 60:05.2f}s.jpg"
        src.rename(dst)
        named.append((t, dst))
    return named


def build_sheets(named, out_dir):
    sheets = out_dir / "sheets"
    sheets.mkdir(exist_ok=True)
    for old in sheets.glob("*.jpg"):
        old.unlink()
    font = ImageFont.truetype("arial.ttf", 22)
    per = SHEET_COLS * SHEET_ROWS
    for n in range(0, len(named), per):
        batch = named[n:n + per]
        thumbs = []
        for t, path in batch:
            im = Image.open(path)
            im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)))
            thumbs.append((t, im))
        th = thumbs[0][1].height
        sheet = Image.new("RGB", (SHEET_COLS * THUMB_W, SHEET_ROWS * th), "black")
        draw = ImageDraw.Draw(sheet)
        for i, (t, im) in enumerate(thumbs):
            x, y = (i % SHEET_COLS) * THUMB_W, (i // SHEET_COLS) * th
            sheet.paste(im, (x, y))
            draw.rectangle([x, y, x + 90, y + 30], fill="black")
            draw.text((x + 6, y + 3), stamp(t), fill="yellow", font=font)
        first, last = stamp(batch[0][0]).replace(":", "m"), stamp(batch[-1][0]).replace(":", "m")
        sheet.save(sheets / f"sheet_{n // per + 1:02}_{first}-{last}.jpg", quality=85)


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run process.py <youtube-link>")
    url = sys.argv[1]
    add_winget_links()
    video_id = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url).group(1)
    out_dir = Path(__file__).parent / "out" / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    video = download(url, out_dir)
    print("Transcribing...", flush=True)
    rows = transcribe(video, out_dir)
    print(f"  {len(rows)} segments", flush=True)
    print("Grabbing frames...", flush=True)
    named = grab_frames(video, out_dir)
    build_sheets(named, out_dir)
    print(f"  {len(named)} frames; output in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
