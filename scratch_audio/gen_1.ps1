
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("C:\Users\Rubey\Documents\GitHub\focus-agent\scratch_audio\voice_push_planet.wav", $f)
$s.Rate = 2
$s.Speak("You think this is funny? You think my grass needs fertilizing with your sweat? You are pushing that planet away from you, and I am not impressed by the velocity! Why are your arms shaking? Is gravity offending you today? Move!")
$s.Dispose()
