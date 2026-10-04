Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile("$PSScriptRoot\test_voice.wav", $format)
$synth.Rate = 2
$synth.Speak("Attention private! Did somebody tell you to swivel your neck?! Put that phone down!")
$synth.Dispose()
Write-Host "Generated test_voice.wav successfully!"
