# Flowtype

Push-to-talk dictation that works in any app. Hold **Right Ctrl**, speak, let go, and the text appears at your cursor.
Double-tap Right Ctrl for hands-free; tap once more to stop, or press Esc to cancel.

It's tuned for English with an Indian accent and for Hinglish. It's separate from the JobPilot web app and only
borrows ideas from its dictation engine.

This is **Phase 1**: the hotkey, audio, VAD, Groq Whisper, the hallucination guards, the paste, and latency logging.
The LLM clean-up, the learning dictionary, the context from the focused window, the overlay and the local fallback
come later (see [Roadmap](#roadmap)).

## Setup (Windows 11)

You need Python 3.11 or newer from python.org, with "Add python.exe to PATH" ticked.

```powershell
cd flowtype
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m flowtype set-key groq        # paste your Groq API key; it goes into Windows Credential Manager
python -m flowtype fetch-tokenizer     # optional (2 MB): counts prompt length exactly instead of estimating
python -m flowtype                     # start dictating
```

Open Notepad, click into it, hold Right Ctrl, say a sentence, and let go. The terminal shows `✓ 9 words in 480 ms`.

Windows permissions:
- **Microphone**: Settings → Privacy & security → Microphone → turn on "Let desktop apps access your microphone".
- **Apps running as administrator**: Windows doesn't let a normal app paste into them. To dictate into an elevated
  window, run Flowtype from an elevated terminal too.

## Setup (macOS)

```bash
cd flowtype
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m flowtype set-key groq        # stored in the macOS Keychain
python -m flowtype
```

Right Ctrl is missing from most Mac keyboards. Set another key in `config.toml`, such as `key = "alt_r"` (Right
Option) or `key = "f13"`.

macOS permissions. Grant each one to the app you launch Flowtype from (Terminal, iTerm or VS Code), then restart that
app:
- **Microphone**: System Settings → Privacy & Security → Microphone. macOS asks the first time.
- **Input Monitoring**: Privacy & Security → Input Monitoring. Without it the hotkey is never seen, and Flowtype
  warns about this at startup.
- **Accessibility**: Privacy & Security → Accessibility. Flowtype needs it to send Cmd+V and to detect password
  fields.

While a password field has focus, macOS turns on Secure Input and Flowtype refuses to paste. Terminal's "Secure
Keyboard Entry" setting does the same.

## Commands

| Command | What it does |
|---|---|
| `python -m flowtype` | Run the dictation app (Ctrl+C to quit) |
| `python -m flowtype set-key groq` / `delete-key groq` | Store or remove the API key in the OS keychain |
| `python -m flowtype devices` | List microphones (set `audio.device` in `config.toml`) |
| `python -m flowtype stats` | Recent dictations with per-stage latency, plus p50/p95 |
| `python -m flowtype words add "Mohsin Sidhpurwala" --star` | Add words to your dictionary (`list`, `remove`) |
| `python -m flowtype transcribe clip.wav` | Run the pipeline on a WAV file and print the text instead of pasting |
| `python -m flowtype eval folder/` | WER and latency over `name.wav` + `name.txt` pairs |
| `python -m flowtype where` | Show the data folder |

Settings: copy [`config.example.toml`](config.example.toml) to the data folder as `config.toml` and edit it.

## How a dictation works

```
key down ─► recorder: the 400 ms pre-roll ring buffer becomes the start of the clip
key up   ─► + 250 ms post-roll ─► Silero VAD trim (no speech → nothing pasted, no API call)
         ─► peak-normalise to −3 dBFS ─► bias prompt (style sample, your words, starred words last, ≤224 tokens)
         ─► Groq whisper-large-v3-turbo (temperature 0, language pinned, verbose segments)
         ─► guard: drop no-speech / looping / stock-phrase segments; one retry without the prompt on a loop or echo
         ─► dictionary: phonetic match to your words, technical-term spellings
         ─► focused field is a password field? refuse
         ─► save clipboard, set text, Ctrl+V / Cmd+V, restore the clipboard 150 ms later
         ─► one row in SQLite `dictations` with every stage's latency
```

The focused-field check runs in parallel with the ASR, so it adds almost no latency. On a fast connection, expect
about 250 ms of post-roll, 200 to 300 ms of ASR and about 20 ms of paste.

## Privacy

- **Keys** live only in the OS keychain (`keyring`: Windows Credential Manager or macOS Keychain). They're never in
  config files, logs or the database.
- **Audio** never touches the disk. Samples stay in memory, go to Groq for transcription, and the buffer is zeroed
  as soon as the dictation is done. The mic stream stays open for the pre-roll, so the OS mic indicator stays on
  while Flowtype runs. Only the last 400 ms are kept, in memory.
- **Data** is stored in one local SQLite file, `flowtype.db` in the data folder. By default it records only timings,
  counts, status and the app name. To also keep the text you dictated, set `store_text = true`. Phase 2's learning
  from corrections needs it.
- **Clipboard**: Flowtype marks the dictated text so Windows clipboard history and cloud clipboard skip it, and so
  do clipboard managers on macOS. Your original clipboard comes back in every format (text, rich text, images,
  copied files). If you copy something else within those 150 ms, Flowtype leaves it alone.

## Code layout

```
flowtype/
  audio/       recorder.py (sounddevice, pre/post-roll), dsp.py (normalise, WAV in memory)
  vad/         silero.py (Silero ONNX via faster-whisper, trim)
  asr/         base.py (ASRProvider), groq_whisper.py, prompt.py (bias prompt, token budget)
  guard/       hallucination.py (no_speech_prob, compression ratio, stock phrases, loop/echo retry)
  dictionary/  phonetic.py (sound-alike match to your words), terms.py (technical spellings)
  context/     focus.py (focused app, password-field check: UI Automation / AX)
  inject/      clipboard.py (save → set → paste → restore), win_clipboard.py, mac_clipboard.py
  hotkey/      state.py (hold / double-tap state machine), listener.py (pynput)
  llm/         base.py (LLMProvider), groq_llm.py: interface only in Phase 1
  store/       db.py (SQLite: dictations, dictionary)
  ui/          console.py (Phase 1 status line)
  eval/        wer.py (WER, Edit Rate)
  pipeline/    dictate.py (one dictation), app.py (threads and wiring)
```

The interfaces the rest of the code depends on:

```python
class ASRProvider(Protocol):
    name: str
    def transcribe(self, audio: np.ndarray, prompt: str, lang: str | None) -> ASRResult: ...
    # audio: mono float32 at 16 kHz. ASRResult has text plus segments carrying no_speech_prob, avg_logprob, compression_ratio.

class LLMProvider(Protocol):
    name: str
    def complete(self, system: str, user: str, *, max_tokens: int = 512, temperature: float = 0.0) -> str: ...
```

## Tests

```bash
python -m pytest
```

They cover the prompt builder's token limit (fuzzed against Whisper's real tokenizer when it's cached), the
hallucination filter, clipboard save and restore (including "don't clobber a newer copy" and "restore even if the
paste fails"), the hotkey state machine, pre-roll and post-roll capture, and the whole pipeline with fake ASR.

## Roadmap

- **Phase 2**: LLM clean-up with guardrails (it may only change words that sound like your dictionary words);
  context from the focused window (UI Automation / AX) added to the prompt; a dictionary that learns from your
  edits, with Edit Rate; a PySide6 overlay; a local faster-whisper fallback when Groq is slow or offline.
- Later: per-app styles, packaging (a signed .exe / .app), auto-start at login.
