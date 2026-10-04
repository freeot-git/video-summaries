# Sets up the video summarizer on Windows. Run this in PowerShell:
#
#   irm https://raw.githubusercontent.com/freeot-git/video-summaries/main/install.ps1 | iex
#
# It installs ffmpeg, uv and Ollama (with winget) if they're missing, downloads this project into
# %USERPROFILE%\video-summaries, and installs its Python packages. Running it again updates
# the project and keeps anything already in its out folder.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Windows PowerShell downloads crawl with the progress bar on
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "freeot-git/video-summaries"
$InstallDir = if ($env:VIDEO_SUMMARIES_DIR) { $env:VIDEO_SUMMARIES_DIR } else { Join-Path $HOME "video-summaries" }

function Refresh-Path {
    $links = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
    $env:Path = @(
        [Environment]::GetEnvironmentVariable("Path", "Machine"),
        [Environment]::GetEnvironmentVariable("Path", "User"),
        $links
    ) -join ";"
}

function Install-IfMissing($command, $wingetId) {
    Refresh-Path
    if (Get-Command $command -ErrorAction SilentlyContinue) {
        Write-Host "  $command is already installed."
        return
    }
    Write-Host "  Installing $command..."
    winget install --id $wingetId -e --silent --accept-source-agreements --accept-package-agreements
    Refresh-Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command didn't install. Try running: winget install --id $wingetId -e"
    }
}

Write-Host "Video summarizer setup"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget isn't available. Install 'App Installer' from the Microsoft Store, then run this again."
}

Write-Host "1/3 Tools"
Install-IfMissing "ffmpeg" "Gyan.FFmpeg"
Install-IfMissing "uv" "astral-sh.uv"
Install-IfMissing "ollama" "Ollama.Ollama"

Write-Host "2/3 Downloading the project to $InstallDir"
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("video-summaries-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $zip = Join-Path $tmp "repo.zip"
    Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $tmp
    $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item (Join-Path $src.FullName "*") $InstallDir -Recurse -Force
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "3/3 Installing Python and packages (about 1.5 GB the first time)"
Push-Location $InstallDir
try {
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done. To process a video:"
Write-Host "  cd `"$InstallDir`""
Write-Host "  uv run process.py `"https://www.youtube.com/watch?v=...`""
Write-Host "The first run also downloads the speech model (about 1.6 GB) and the summary model (about 3.3 GB)."
