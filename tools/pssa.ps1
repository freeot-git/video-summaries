# Formats and lints the PowerShell files pre-commit passes in, with the pinned PSScriptAnalyzer.
# Runs in Windows PowerShell 5.1, the version the scripts run on. A file the formatter changes is
# written back, so pre-commit stops the commit (or fails CI) until the change is added.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)

$ErrorActionPreference = 'Stop'
$Version = '1.25.0'
$Settings = Join-Path (Split-Path -Parent $PSScriptRoot) 'PSScriptAnalyzerSettings.psd1'

try {
    Import-Module PSScriptAnalyzer -RequiredVersion $Version
} catch {
    Write-Error "PSScriptAnalyzer $Version is not installed. Install it with: Install-Module PSScriptAnalyzer -RequiredVersion $Version -Scope CurrentUser"
    exit 1
}

$failed = $false
foreach ($file in $Files) {
    $path = (Resolve-Path $file).Path
    $bytes = [IO.File]::ReadAllBytes($path)
    $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
    $text = [IO.File]::ReadAllText($path)
    $formatted = Invoke-Formatter -ScriptDefinition $text -Settings CodeFormattingOTBS
    if ($formatted -cne $text) {
        [IO.File]::WriteAllText($path, $formatted, (New-Object Text.UTF8Encoding($hasBom)))
        Write-Output "Formatted $file"
    }
    $findings = Invoke-ScriptAnalyzer -Path $path -Settings $Settings
    foreach ($f in $findings) {
        Write-Output ('{0}:{1}: {2} {3}' -f $file, $f.Line, $f.RuleName, $f.Message)
        $failed = $true
    }
}
if ($failed) { exit 1 }
