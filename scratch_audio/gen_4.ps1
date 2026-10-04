
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("C:\Users\Rubey\Documents\GitHub\focus-agent\scratch_audio\voice_penalty_cleared.wav", $f)
$s.Rate = 2
$s.Speak("Target completed! Penalty cleared, private! Get off my drill deck, pick up your work, and focus! Dismissed!")
$s.Dispose()
