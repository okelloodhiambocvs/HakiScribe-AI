<#
.SYNOPSIS
    Renders the synthetic demo script to 16 kHz mono 16-bit PCM WAV.

.DESCRIPTION
    Reads speaker lines (LABEL: text) from
    demo-data/synthetic/case-cr-123-2026-script.md and speaks every turn with
    a per-speaker installed Windows voice into
    demo-data/synthetic/case-cr-123-2026.wav (about two minutes with
    0.6 s pauses between turns). Also writes
    demo-data/synthetic/case-cr-123-2026.reference.json with per-turn
    timings measured from the actual synthesized audio plus the pause
    lengths. Synthetic demo content only.
    Run from the repo root or the scripts folder:
      powershell -ExecutionPolicy Bypass -File .\scripts\make_demo_audio.ps1
#>
[CmdletBinding()]
param(
    [string]$ScriptPath = "",
    [string]$OutPath = "",
    [string]$RefPath = "",
    [int]$PauseMs = 600
)

$ErrorActionPreference = "Stop"

$here = $PSScriptRoot
if ([string]::IsNullOrEmpty($here)) {
    $cmdPath = $MyInvocation.MyCommand.Path
    if (-not [string]::IsNullOrEmpty($cmdPath)) {
        $here = Split-Path -Parent $cmdPath
    }
}
if ([string]::IsNullOrEmpty($here)) {
    $here = (Get-Location).Path
}
if ((Split-Path -Leaf $here) -eq "scripts") {
    $repoRoot = Split-Path -Parent $here
}
else {
    $repoRoot = $here
}
if ([string]::IsNullOrEmpty($ScriptPath)) {
    $ScriptPath = Join-Path $repoRoot "demo-data\synthetic\case-cr-123-2026-script.md"
}
if ([string]::IsNullOrEmpty($OutPath)) {
    $OutPath = Join-Path $repoRoot "demo-data\synthetic\case-cr-123-2026.wav"
}
if ([string]::IsNullOrEmpty($RefPath)) {
    $RefPath = [System.IO.Path]::ChangeExtension($OutPath, ".reference.json")
}
Write-Host "Repo root: $repoRoot"
Write-Host "Script:    $ScriptPath"
Write-Host "Output:    $OutPath"
Write-Host "Reference: $RefPath"

Add-Type -AssemblyName System.Speech

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Error "Script not found: $ScriptPath"
    exit 1
}

$probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @($probe.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo })
$probe.Dispose()
if ($voices.Count -eq 0) {
    Write-Error "No installed speech voices found. Install a Windows voice first."
    exit 1
}

Write-Host ("Installed voices ({0}):" -f $voices.Count)
foreach ($voice in $voices) {
    Write-Host ("  - {0} [{1}, {2}]" -f $voice.Name, $voice.Culture, $voice.Gender)
}

$turns = @()
foreach ($line in (Get-Content -LiteralPath $ScriptPath)) {
    $trimmed = $line.Trim()
    if ($trimmed -eq "" -or $trimmed.StartsWith("#")) {
        continue
    }
    if ($trimmed -match "^([A-Z][A-Z0-9_]+):\s*(.+)$") {
        $turns += [pscustomobject]@{ Speaker = $Matches[1]; Text = $Matches[2] }
    }
}
if ($turns.Count -eq 0) {
    Write-Error "No speaker lines (LABEL: text) found in $ScriptPath"
    exit 1
}
Write-Host ("Turns: {0}" -f $turns.Count)

$cast = @($voices)
if ($cast.Count -eq 1) {
    Write-Host "Only one voice installed; using it for every speaker."
}
$voiceFor = @{}
$nextVoice = 0
foreach ($turn in $turns) {
    if (-not $voiceFor.ContainsKey($turn.Speaker)) {
        $voiceFor[$turn.Speaker] = $cast[$nextVoice % $cast.Count]
        $nextVoice++
    }
}
Write-Host "Voice cast:"
foreach ($speaker in ($voiceFor.Keys | Sort-Object)) {
    Write-Host ("  {0} -> {1}" -f $speaker, $voiceFor[$speaker].Name)
}

$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

# Render each turn to its own temp WAV so start/end timings come from the
# actual synthesized durations; then concatenate the PCM with silence
# pauses into the final file (all parts share the same 16 kHz mono
# 16-bit format, 32000 bytes per second).
$pcm = New-Object System.Collections.Generic.List[byte]
$referenceTurns = @()
$cursorMs = 0
$header = $null
$pauseBytes = [int]([math]::Round($PauseMs * 32.0))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = -2
$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("hakiscribe-turns-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $index = 0
    foreach ($turn in $turns) {
        $voice = $voiceFor[$turn.Speaker]
        $synth.SelectVoice($voice.Name)
        $tempWav = Join-Path $tempDir ("turn-{0}.wav" -f $index)
        $synth.SetOutputToWaveFile($tempWav, $format)
        Write-Host ("[{0}/{1}] {2} <{3}>" -f ($index + 1), $turns.Count, $turn.Speaker, $voice.Name)
        $synth.Speak($turn.Text)
        $synth.SetOutputToNull()
        $raw = [System.IO.File]::ReadAllBytes($tempWav)
        if ($raw.Length -lt 44) {
            throw ("Turn {0} produced no audio." -f $index)
        }
        if ($header -eq $null) {
            $header = New-Object byte[] 44
            [System.Array]::Copy($raw, 0, $header, 0, 44)
        }
        $dataLen = $raw.Length - 44
        $speechMs = [int]([math]::Round($dataLen / 32.0))
        $startMs = $cursorMs
        $endMs = $cursorMs + $speechMs
        $referenceTurns += [pscustomobject]@{
            turn_idx = $index
            role     = $turn.Speaker
            voice    = $voice.Name
            start_ms = $startMs
            end_ms   = $endMs
            text     = $turn.Text
        }
        $data = New-Object byte[] $dataLen
        [System.Array]::Copy($raw, 44, $data, 0, $dataLen)
        $pcm.AddRange($data)
        $silence = New-Object byte[] $pauseBytes
        $pcm.AddRange($silence)
        $cursorMs = $endMs + $PauseMs
        Remove-Item -LiteralPath $tempWav -Force
        $index++
    }
}
finally {
    $synth.SetOutputToNull()
    $synth.Dispose()
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

$dataSize = $pcm.Count
$totalSize = 44 + $dataSize
[System.Array]::Copy([System.BitConverter]::GetBytes($totalSize - 8), 0, $header, 4, 4)
[System.Array]::Copy([System.BitConverter]::GetBytes($dataSize), 0, $header, 40, 4)
$out = New-Object byte[] $totalSize
[System.Array]::Copy($header, 0, $out, 0, 44)
$pcm.CopyTo($out, 44)
[System.IO.File]::WriteAllBytes($OutPath, $out)

$bytes = (Get-Item -LiteralPath $OutPath).Length
$seconds = ($bytes - 44) / 32000
Write-Host ("Wrote {0} ({1} bytes, about {2} s, 16 kHz mono 16-bit PCM)" -f $OutPath, $bytes, [math]::Round($seconds, 1))
if ($seconds -lt 15 -or $seconds -gt 600) {
    Write-Error ("Duration {0} s outside the 15-600 s gate." -f [math]::Round($seconds, 1))
    exit 1
}

$sha256 = (Get-FileHash -LiteralPath $OutPath -Algorithm SHA256).Hash.ToLower()
$reference = [pscustomobject]@{
    audio_file   = Split-Path -Leaf $OutPath
    audio_sha256 = $sha256
    turns        = $referenceTurns
}
$noBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($RefPath, ($reference | ConvertTo-Json -Depth 5), $noBom)
Write-Host ("Wrote reference {0} ({1} turns, sha256 {2})" -f $RefPath, $referenceTurns.Count, $sha256.Substring(0, 12))
