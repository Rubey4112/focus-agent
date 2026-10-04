
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("C:\Users\Rubey\Documents\GitHub\focus-agent\scratch_audio\voice_swivel_neck.wav", $f)
$s.Rate = 2
$s.Speak("Did somebody tell you to swivel your neck, private? Did I issue an order authorizing ocular reconnaissance? No! Then why are your eyeballs wandering around my drill deck looking for a parking spot? Put that phone down and jump!")
$s.Dispose()
