<#
.SYNOPSIS
    Renders the synthetic demo script to 16 kHz mono 16-bit PCM WAV.

.DESCRIPTION
    Reads speaker lines (LABEL: text) from
    demo-data/synthetic/case-cr-123-2026-script.md and speaks every turn with
    a per-speaker installed Windows voice into
    demo-data/synthetic/case-cr-123-2026.wav (about two minutes with
    0.6 s pauses between turns). Synthetic demo content only.
    Run from the repo root or the scripts folder:
      powershell -ExecutionPolicy Bypass -File .\scripts\make_demo_audio.ps1
#>
[CmdletBinding()]
param(
    [string]$ScriptPath = "",
    [string]$OutPath = "",
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
Write-Host "Repo root: $repoRoot"
Write-Host "Script:    $ScriptPath"
Write-Host "Output:    $OutPath"

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
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = -2
try {
    $synth.SetOutputToWaveFile($OutPath, $format)
    $index = 0
    foreach ($turn in $turns) {
        $voice = $voiceFor[$turn.Speaker]
        $synth.SelectVoice($voice.Name)
        $prompt = New-Object System.Speech.Synthesis.PromptBuilder
        $prompt.AppendText($turn.Text)
        $prompt.AppendBreak([System.TimeSpan]::FromMilliseconds($PauseMs))
        Write-Host ("[{0}/{1}] {2} <{3}>" -f ($index + 1), $turns.Count, $turn.Speaker, $voice.Name)
        $synth.Speak($prompt)
        $index++
    }
}
finally {
    $synth.SetOutputToNull()
    $synth.Dispose()
}

$bytes = (Get-Item -LiteralPath $OutPath).Length
$seconds = ($bytes - 44) / 32000
Write-Host ("Wrote {0} ({1} bytes, about {2} s, 16 kHz mono 16-bit PCM)" -f $OutPath, $bytes, [math]::Round($seconds, 1))
if ($seconds -lt 15 -or $seconds -gt 600) {
    Write-Error ("Duration {0} s outside the 15-600 s gate." -f [math]::Round($seconds, 1))
    exit 1
}
