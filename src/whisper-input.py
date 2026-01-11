import whisper
import pyaudio
import wave
import audioop
import time
import subprocess
import shutil
import sys
from pynput.keyboard import Key, Controller
from plyer import notification
import argparse
from termcolor import colored
import tempfile
import os
import beepy

def play_beep(sound_type, beep_enabled):
    if beep_enabled:
        beepy.beep(sound_type)

def record_speech(silence_threshold=500, silence_duration=10, max_duration=600, beep_enabled=True):
    """
    Record speech until silence is detected or max_duration is reached.
    
    Args:
        silence_threshold: RMS threshold for detecting sound (default: 500)
        silence_duration: Seconds of silence before stopping (default: 10)
        max_duration: Maximum recording duration in seconds (default: 600 = 10 minutes)
        beep_enabled: Whether to play beep sounds
    """
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
    last_sound_time = time.time()
    start_time = time.time()
    chunk_write_interval = 100  # Write to file every N frames to save memory

    try:
        while True:
            data = stream.read(1024)
            frames.append(data)

            # Check volume
            rms = audioop.rms(data, 2)
            if rms > silence_threshold:
                last_sound_time = time.time()

            # Check if silence duration is reached
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

def type_text(text):
    """
    Type text using the most reliable method available.
    On Linux, xdotool is more reliable than pynput for many applications.
    Falls back to pynput if xdotool is not available.
    """
    if not text or not text.strip():
        return
    
    # Try xdotool first (more reliable on Linux for terminals/browsers)
    xdotool_path = shutil.which('xdotool')
    if xdotool_path:
        try:
            # xdotool type is more reliable for terminals and browsers
            subprocess.run([xdotool_path, 'type', '--clearmodifiers', text], 
                         check=True, timeout=30)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            # Fall through to pynput if xdotool fails
            pass
    
    # Fallback to pynput
    try:
        # Add a small delay to ensure the target window is ready
        time.sleep(0.1)
        keyboard = Controller()
        keyboard.type(text)
    except Exception as e:
        print(f"Error typing text: {e}", file=sys.stderr)
        # Last resort: try to use xsel/xclip to put text in clipboard
        # User can paste manually
        try:
            xsel_path = shutil.which('xsel') or shutil.which('xclip')
            if xsel_path:
                proc = subprocess.Popen([xsel_path, '-i'], stdin=subprocess.PIPE, 
                                      stderr=subprocess.DEVNULL)
                proc.communicate(input=text.encode('utf-8'), timeout=5)
                print("Text copied to clipboard (paste manually with Ctrl+V)", file=sys.stderr)
        except Exception:
            pass

# Argument parsing
parser = argparse.ArgumentParser(description="Speech-to-Text with Silence Threshold")
parser.add_argument("--silence_duration", type=int, default=5, help="Duration of silence before stopping recording (in seconds)")
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
speech_file = record_speech(silence_duration=args.silence_duration, max_duration=args.max_duration, beep_enabled=args.beep)
transcribed_text = transcribe_speech(speech_file, beep_enabled=args.beep)

# Step 4: Type the text
type_text(transcribed_text)

# Step 5: Play end beep and show notification
play_beep(sound_type=1, beep_enabled=args.beep)
icon = os.path.join(os.path.dirname(__file__), 'icons', 'thinking.png')
notification.notify(title="Speech-to-Text", message="Transcription complete!", app_icon=icon, app_name="Speech-to-Text")
