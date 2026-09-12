# Text-to-Speech / Speech-to-Text Experiments

This repository contains application experiments around speech input/output, including a Python application, local model material, and a separate frontend area.

## Structure

- `app.py` — main application entry point
- `model/` — local model-related files
- `tts_fronted/` — frontend code
- additional local development artifacts

## Scope

The project is a prototype used to explore integration of speech services into an application workflow. It is not presented as a new speech-recognition or speech-synthesis model.

## Security Note

Browser cookies, HAR files, access tokens, and other session artifacts should never be committed to a public repository. Any local capture material should be removed or replaced with sanitized examples before public sharing.


## Goal

The application explores a browser workflow that accepts speech, transcribes it, generates a response, and returns synthesized or recorded audio through a Flask interface.

## Installation

This repository has no dependency manifest, so setup is not reproducible as committed. A local environment must provide Python, PyTorch, Flask, SpeechRecognition, Whisper, `g4f`, and any system audio or text-to-speech programs invoked by `app.py`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install flask torch SpeechRecognition openai-whisper g4f
python app.py
```

## Working with the Repository

The Flask backend is in `app.py`, and the browser assets are under `tts_fronted/`. Check model paths and external executable calls in `app.py` before starting the server. Do not reuse material from `har_and_cookies/` as configuration; captured browser-session data is not a dependency.
