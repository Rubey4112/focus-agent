
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Volume = 100
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(8000, [System.Speech.AudioFormat.AudioBitsPerSample]::Eight, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile("C:\Users\Rubey\Documents\GitHub\focus-agent\scratch_audio\voice_heavy_boots.wav", $f)
$s.Rate = 2
$s.Speak("One, two, three, one! Are your boots too heavy for you, warrior? Do you need me to carry them for you? Don't you dare drop those heels! If those boots touch my dirt before I say so, we are staying out here until the sun forgets where it lives! Move those legs!")
$s.Dispose()
