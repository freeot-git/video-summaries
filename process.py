"""Turn a video link into what's needed to summarize it without a published transcript.

    uv run process.py <youtube-url>

Writes to out/<video-id>/:
    video.mp4        the downloaded video (720p at most)
    transcript.txt   our own speech-to-text, one timestamped line per segment
    transcript.json  the same, with start/end seconds
    frames/          a still each time the picture changes, named by its time
    sheets/          those stills tiled 4x3 with their times printed, for quick review
    summary.md       each story's title, start and end times and a short summary
    summary.txt      the same as plain text

The summary is written on this computer by a local model run with Ollama.
"""

import json
import math
import os
import re
import socket
import subprocess
import sys
import sysconfig
import time
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCENE_THRESHOLD = 0.3  # how big a picture change counts as a new shot (0-1)
SHEET_COLS, SHEET_ROWS, THUMB_W = 4, 3, 480
WHISPER_MODEL = "large-v3-turbo"
SUMMARY_MODEL = "qwen3.5:4b"
OLLAMA_URL = "http://127.0.0.1:11434"

SUMMARY_PROMPT = """You split a news video's transcript into its stories.

The transcript comes from speech-to-text, one numbered line per segment. List every distinct
story or segment in order: news stories, explainers, trivia, features. Leave out only the host's
opening greeting and closing sign-off. For each story give:
- title: a short headline in plain words
- first_line, last_line: the numbers of its first and last transcript lines
- summary: two or three sentences saying who, what, where and any key numbers

Use only what the transcript says. Names may be misspelled by speech-to-text; copy them as written."""


def add_winget_links():
    """winget puts ffmpeg here; a window opened before the install won't have it on PATH yet."""
    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
    if links.is_dir():
        os.environ["PATH"] = f"{os.environ['PATH']}{os.pathsep}{links}"


def prefer_ipv4():
    """Some networks reset Python's IPv6 connections to Hugging Face, so the model download fails."""
    plain = socket.getaddrinfo

    def ipv4_first(*args, **kwargs):
        return sorted(plain(*args, **kwargs), key=lambda a: a[0] != socket.AF_INET)

    socket.getaddrinfo = ipv4_first


def add_ollama_dir():
    """The Ollama installer adds itself to PATH, but only for windows opened after the install."""
    ollama = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
    if ollama.is_dir():
        os.environ["PATH"] = f"{os.environ['PATH']}{os.pathsep}{ollama}"


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
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() > 0:
        add_gpu_dll_dirs()
        device, compute_type = "cuda", "float16"
    else:
        print("  No CUDA device is visible; using CPU (slower).", flush=True)
        device, compute_type = "cpu", "int8"
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
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


def ollama(path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(f"{OLLAMA_URL}{path}", data, timeout) as response:
        return json.load(response)


def start_ollama():
    """Ollama normally runs in the background after install; start it if it isn't up."""
    try:
        ollama("/api/version")
        return
    except OSError:
        pass
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(30):
        time.sleep(1)
        try:
            ollama("/api/version")
            return
        except OSError:
            pass
    raise RuntimeError("Ollama didn't start. Open the Ollama app from the Start menu and try again.")


def summarize(rows, out_dir):
    start_ollama()
    if SUMMARY_MODEL not in [m["name"] for m in ollama("/api/tags")["models"]]:
        print(f"  Downloading the summary model ({SUMMARY_MODEL}, about 3.3 GB) the first time...", flush=True)
        subprocess.run(["ollama", "pull", SUMMARY_MODEL], check=True)

    numbered = "\n".join(f"{i}: {r['text']}" for i, r in enumerate(rows, start=1))
    story = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "first_line": {"type": "integer"},
            "last_line": {"type": "integer"},
            "summary": {"type": "string"},
        },
        "required": ["title", "first_line", "last_line", "summary"],
    }
    schema = {"type": "object", "properties": {"stories": {"type": "array", "items": story}}, "required": ["stories"]}
    # Room for the transcript (about 3 characters a token) plus the answer, in 4K steps.
    num_ctx = max(8192, math.ceil((len(numbered) / 3 + 4096) / 4096) * 4096)
    reply = ollama("/api/chat", {
        "model": SUMMARY_MODEL,
        "messages": [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": numbered},
        ],
        "format": schema,
        "think": False,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": num_ctx},
    }, timeout=3600)
    stories = json.loads(reply["message"]["content"])["stories"]

    # Times come from the transcript itself, so they're exact even if the model's line numbers drift a little.
    last = len(rows)
    for s in stories:
        s["first_line"] = min(max(s["first_line"], 1), last)
        s["last_line"] = min(max(s["last_line"], s["first_line"]), last)
        s["start"], s["end"] = rows[s["first_line"] - 1]["start"], rows[s["last_line"] - 1]["end"]
    stories.sort(key=lambda s: s["start"])

    info = json.loads((out_dir / "video.info.json").read_text(encoding="utf-8"))
    title = info.get("title", out_dir.name)
    md = [f"# {title}", "", info.get("webpage_url", ""), ""]
    txt = [title, info.get("webpage_url", ""), ""]
    for i, s in enumerate(stories, start=1):
        span = f"{stamp(s['start'])} - {stamp(s['end'])}"
        md += [f"## {i}. {s['title']}", "", f"**{span}**", "", s["summary"], ""]
        txt += [f"{i}. {s['title']}", f"   {span}", f"   {s['summary']}", ""]
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")
    (out_dir / "summary.txt").write_text("\n".join(txt), encoding="utf-8")
    return stories


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run process.py <youtube-link>")
    url = sys.argv[1]
    add_winget_links()
    add_ollama_dir()
    prefer_ipv4()
    video_id = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", url).group(1)
    out_dir = Path(__file__).parent / "out" / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    video = download(url, out_dir)
    print("Grabbing frames...", flush=True)
    named = grab_frames(video, out_dir)
    build_sheets(named, out_dir)
    print(f"  {len(named)} frames; output in {out_dir}", flush=True)

    print("Transcribing...", flush=True)
    try:
        rows = transcribe(video, out_dir)
    except Exception as exc:
        print(
            f"Transcription failed ({type(exc).__name__}: {exc}). "
            f"The video and frame sheets are still available in {out_dir}. "
            "Check your internet connection for the first model download and "
            "check the NVIDIA driver if CUDA should be available.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    print(f"  {len(rows)} segments; output in {out_dir}", flush=True)

    print("Summarizing...", flush=True)
    try:
        stories = summarize(rows, out_dir)
    except Exception as exc:
        print(
            f"Summary failed ({type(exc).__name__}: {exc}). "
            f"The transcript and frame sheets are still available in {out_dir}.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    print(f"  {len(stories)} stories; see summary.txt in {out_dir}", flush=True)


if __name__ == "__main__":
    main()
