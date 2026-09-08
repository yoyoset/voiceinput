# 用 Windows SAPI (Huihui, zh-CN) 合成中英混说测试音频。
#
# 合成语音代替不了真人录音(没有口音、没有口水词、发音过于标准),
# 只用来回答一个结构性问题:SenseVoice 能不能处理句内中英切换。
#
# 中文文本从 tts_sentences.json 读(PS 5.1 直接写在脚本里容易编码出问题)。

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $here 'tts'
if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

$json = Get-Content -Raw -Encoding UTF8 (Join-Path $here 'tts_sentences.json')
$sentences = $json | ConvertFrom-Json

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice('Microsoft Huihui Desktop')
$synth.Rate = 0

# SenseVoice 吃 16kHz 单声道,直接按这个格式合成,省一道重采样
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, `
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, `
    [System.Speech.AudioFormat.AudioChannel]::Mono)

foreach ($s in $sentences) {
    $path = Join-Path $outDir ($s.key + '.wav')
    $synth.SetOutputToWaveFile($path, $fmt)
    $synth.Speak($s.text)
    $synth.SetOutputToNull()
    $size = (Get-Item $path).Length
    Write-Output ("{0}  {1} bytes" -f $s.key, $size)
}

$synth.Dispose()
Write-Output ("done -> " + $outDir)
