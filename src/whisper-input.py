import whisper
import pyaudio
import wave
import audioop
import time
import subprocess
import shutil
import sys
from plyer import notification
import argparse
from termcolor import colored
import tempfile
import os
import beepy

def play_beep(sound_type, beep_enabled):
    if beep_enabled:
        beepy.beep(sound_type)

def calibrate_mic(duration=1.5):
    """
    Calibrate silence threshold by sampling ambient noise.
    Uses 95th percentile of noise and a high multiplier for reliable speech detection.
    """
    audio = pyaudio.PyAudio()
    stream = audio.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)

    samples = []
    chunks = int(44100 / 1024 * duration)

    for _ in range(chunks):
        try:
            data = stream.read(1024, exception_on_overflow=False)
            rms = audioop.rms(data, 2)
            samples.append(rms)
        except Exception:
            pass

    stream.stop_stream()
    stream.close()
    audio.terminate()

    if samples:
        samples.sort()
        # Use 95th percentile to ignore noise spikes
        p95_idx = int(len(samples) * 0.95)
        noise_floor = samples[p95_idx] if p95_idx < len(samples) else samples[-1]
        # Threshold = 5x noise floor, clamped between 300 and 3000
        threshold = max(300, min(3000, int(noise_floor * 5)))
        return threshold
    return 500  # fallback default

def record_speech(silence_threshold=None, silence_duration=10, max_duration=600, beep_enabled=True):
    """
    Record speech until silence is detected or max_duration is reached.

    Args:
        silence_threshold: RMS threshold for detecting sound (auto-calibrated if None)
        silence_duration: Seconds of silence before stopping (default: 10)
        max_duration: Maximum recording duration in seconds (default: 600 = 10 minutes)
        beep_enabled: Whether to play beep sounds
    """
    if silence_threshold is None:
        silence_threshold = calibrate_mic()
        print(colored(f'Auto-calibrated silence threshold: {silence_threshold}', 'cyan'), file=sys.stderr)

    icon = os.path.join(os.path.dirname(__file__), 'icons', 'speaking.png')
    notification.notify(title="Speech-to-Text", message="Start Speaking...", app_icon=icon, app_name="Speech-to-Text")

    # Initialize PyAudio and Recorder
    audio = pyaudio.PyAudio()
    stream = audio.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)

    # Create a temporary file to save the recording (write incrementally to save memory)
    temp_dir = tempfile.gettempdir()
    temp_file_path = os.path.join(temp_dir, "recording.wav")
    wf = wave.open(temp_file_path, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(audio.get_sample_size(pyaudio.paInt16))
    wf.setframerate(44100)

    frames = []
    last_sound_time = None  # Will be set when speech is first detected
    start_time = time.time()
    chunk_write_interval = 100  # Write to file every N frames to save memory
    speech_started = False

    try:
        while True:
            data = stream.read(1024)
            frames.append(data)

            # Check volume
            rms = audioop.rms(data, 2)
            if rms > silence_threshold:
                if not speech_started:
                    speech_started = True
                    print(colored('Speech detected, recording...', 'green'), file=sys.stderr)
                last_sound_time = time.time()

            # Check if silence duration is reached (only after speech started)
            if speech_started and last_sound_time:
                if (time.time() - last_sound_time) > silence_duration:
                    break

            # Check if max duration is reached
            elapsed = time.time() - start_time
            if elapsed >= max_duration:
                print(f"\nMaximum recording duration ({max_duration}s) reached. Stopping recording.", file=sys.stderr)
                break

            # Periodically write chunks to file to save memory
            if len(frames) >= chunk_write_interval:
                wf.writeframes(b''.join(frames))
                frames = []  # Clear frames from memory

    finally:
        # Write any remaining frames
        if frames:
            wf.writeframes(b''.join(frames))
        wf.close()

        # Stop and close the stream
        stream.stop_stream()
        stream.close()
        audio.terminate()

    return temp_file_path

def transcribe_speech(file_path, beep_enabled=True):
    icon = os.path.join(os.path.dirname(__file__), 'icons', 'silence.png')
    notification.notify(title="Speech-to-Text", message="Processing recording...", app_icon=icon, app_name="Speech-to-Text")
    model = whisper.load_model("base")
    result = model.transcribe(file_path)
    return result["text"]

def is_wayland():
    return os.environ.get('XDG_SESSION_TYPE') == 'wayland' or os.environ.get('WAYLAND_DISPLAY')

def copy_to_clipboard(text):
    if is_wayland() and shutil.which('wl-copy'):
        try:
            subprocess.run(['wl-copy', text], check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    if shutil.which('xclip'):
        try:
            proc = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'), timeout=5)
            return proc.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            pass
    return False

def type_text(text):
    """
    Type text using the most reliable method available.
    Tries multiple tools with fallbacks for maximum compatibility.
    Always copies to clipboard first.
    """
    if not text or not text.strip():
        return

    copied = copy_to_clipboard(text)

    # Try wtype first (native Wayland)
    # Use wl-copy + wtype paste for reliability — wtype direct typing can
    # drop spaces in some apps (terminals, Electron apps on XWayland)
    if is_wayland():
        wtype_path = shutil.which('wtype')
        wl_copy_path = shutil.which('wl-copy')

        # Preferred: clipboard paste (most reliable, preserves all whitespace)
        if copied and wtype_path:
            try:
                time.sleep(0.05)
                subprocess.run([wtype_path, '-M', 'ctrl', 'v', '-m', 'ctrl'],
                             check=True, timeout=10)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass

        # Fallback: wtype direct with delay between keystrokes
        if wtype_path:
            try:
                subprocess.run([wtype_path, '-d', '1', text], check=True, timeout=30)
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass

    # Try xdotool (works on X11 and XWayland apps like VSCode)
    if shutil.which('xdotool'):
        try:
            subprocess.run(['xdotool', 'type', '--clearmodifiers', '--delay', '1', text],
                         check=True, timeout=30)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    # Try ydotool as last resort (uses uinput, works everywhere but needs setup)
    if shutil.which('ydotool'):
        try:
            subprocess.run(['ydotool', 'type', '--', text], check=True, timeout=30)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    if copied:
        print(colored('Text copied to clipboard (paste manually with Ctrl+V)', 'yellow'), file=sys.stderr)
    else:
        print(colored('Could not type or copy text. Install wtype (Wayland) or xdotool (X11)', 'red'), file=sys.stderr)

# Argument parsing
parser = argparse.ArgumentParser(description="Speech-to-Text with Silence Threshold")
parser.add_argument("--silence_duration", type=int, default=5, help="Duration of silence before stopping recording (in seconds)")
parser.add_argument("--silence_threshold", type=int, default=None, help="RMS threshold for silence detection (auto-calibrated if not set)")
parser.add_argument("--max_duration", type=int, default=600, help="Maximum recording duration in seconds (default: 600 = 10 minutes)")
parser.add_argument("--beep", action='store_true', help="Enable beep sound at start and end")
args = parser.parse_args()

if args.silence_duration == 5:
    print(colored('No silence duration argument provided, using default value of 5 seconds.', 'yellow'))
    print(colored(f'Maximum recording duration: {args.max_duration} seconds ({args.max_duration // 60} minutes)', 'cyan'))
    print(colored('Example usage: python script_name.py --silence_duration 1 --max_duration 1200 --beep', 'green'))

# Step 1: Play start beep
play_beep(sound_type=1, beep_enabled=args.beep)

# Step 2 and 3: Record and transcribe speech
speech_file = record_speech(
    silence_threshold=args.silence_threshold,
    silence_duration=args.silence_duration,
    max_duration=args.max_duration,
    beep_enabled=args.beep
)
transcribed_text = transcribe_speech(speech_file, beep_enabled=args.beep)

# Step 4: Type the text
type_text(transcribed_text)

# Step 5: Play end beep and show notification
play_beep(sound_type=1, beep_enabled=args.beep)
icon = os.path.join(os.path.dirname(__file__), 'icons', 'thinking.png')
notification.notify(title="Speech-to-Text", message="Transcription complete!", app_icon=icon, app_name="Speech-to-Text")
