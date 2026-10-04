
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("C:\Users\Rubey\Documents\GitHub\focus-agent\scratch_audio\voice_slug_motivation.wav", $f)
$s.Rate = 2
$s.Speak("I have seen slugs move faster than this! Quitting is not an option on my watch! Pump those legs! Jump higher, soldier!")
$s.Dispose()
