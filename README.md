# Persian speech processing with OpenAI

A Flask app with a responsive Persian (RTL) speech workspace:

- `POST /tts`: JSON `{"text":"سلام"}` → OpenAI **`gpt-4o-mini-tts`**, `coral` voice, Persian speaking instructions → WAV bytes, `audio/wav`, filename `speech.wav`.
- `/call`: **`gpt-live-1`** voice conversation over browser WebRTC, with a private backend retrieval/safety agent.
- `POST /conversation`: retained chained typed/audio conversation endpoint for compatibility and evaluation.
- `POST /stt`: multipart field `audio` → OpenAI **`gpt-transcribe`**, `languages=["fa"]` → JSON `{"transcription":"..."}`.

No GPU, local Whisper/Piper models, FFmpeg, or Git LFS is required. Speech processing requires internet access and an OpenAI API key with model access and available API billing/quota. Text/audio is sent to OpenAI. The browser displays this and identifies generated speech as AI-generated.

## Ubuntu 26.04 setup

The configured environment is `.venv`, Python 3.12.14, on Ubuntu 26.04 x86_64. Keep using it; system Python 3.14 was not replaced. The manifest contains Flask, the OpenAI SDK, pypdf for local document extraction, python-dotenv for the runner, and websockets for the private Live connection; the lock file pins all dependencies.

From the existing checkout:

```bash
cd /home/newuser/Music/tts/tts-stt
.bootstrap/bin/uv pip sync --python .venv/bin/python requirements.lock.txt
```

For a fresh checkout/environment (Python 3.12 is the tested version):

```bash
# Only if git / venv support is missing:
sudo apt update
sudo apt install git python3-venv

git clone https://github.com/shosseinj/tts-stt.git
cd tts-stt
python3 -m venv .bootstrap
.bootstrap/bin/pip install uv
.bootstrap/bin/uv python install 3.12
.bootstrap/bin/uv venv --python 3.12 .venv
.bootstrap/bin/uv pip sync --python .venv/bin/python requirements.lock.txt
```

These setup steps assume this updated version of the source files. Changes made in this workspace have not been pushed upstream.

## Configure the key and launch

All three features read the API key **only from `OPENAI_API_KEY` in the Flask server environment**. Browser-supplied keys are ignored and there is no key input field. Set it in your own terminal without placing its value in shell history:

```bash
cd /home/newuser/Music/tts/tts-stt
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
printf '\n'
.venv/bin/python app.py
```

Open **http://127.0.0.1:5000**. Ctrl+C stops the foreground server. If another copy is using the port, stop that copy first, or use `PORT=5001 .venv/bin/python app.py` and open http://127.0.0.1:5001.

The Flask process reads `OPENAI_API_KEY` only from its environment. Keys are never embedded in source/templates, returned to clients, or logged by the app. The `./run.sh` launcher loads `.env` on the server (see Runner below); direct `python app.py` only reads exported environment variables. `.env` and `.env.*` are ignored by Git. Do not put a key in JavaScript, source code, chat, or commits. `unset OPENAI_API_KEY` removes it from the current shell after stopping the server.

If recording works but no transcript appears, check the server key first: after saving `OPENAI_API_KEY=your-key` in `.env`, restart with `./run.sh`. Direct `python app.py` needs an exported key. The call page shows a specific setup message for a missing key.

The app starts even without a key so the UI and validation can be tested. Valid speech requests then return HTTP 503 with a setup message. Setting a key in another terminal does not update an already running server: restart it from the configured terminal.

This is a localhost development server. Requests have a 120-second SDK timeout with automatic retries disabled. Raw provider errors and credentials are not exposed. Authentication/access failures return 502, quota/rate limits 429, connection errors 502, timeouts 504, and rejected input 400.

## Troubleshooting HTTP 429 and stale keys

The call page distinguishes temporary rate limits, insufficient quota, exhausted credit, and project/organization spending or usage limits using OpenAI's error code. Unknown 429 responses do not prove that credit is exhausted. Check billing and limits for the **project and organization belonging to the key**, rather than assuming every key uses the same balance. See [OpenAI error codes](https://developers.openai.com/api/docs/guides/error-codes).

A running Flask process keeps its startup environment. After editing `.env`, restart with `./run.sh`. An exported `OPENAI_API_KEY` overrides `.env`: if you intend to use the file's value, run `unset OPENAI_API_KEY` in your terminal before `./run.sh`. No key values are logged or displayed.

## Persian transcription accuracy

STT now uses `gpt-transcribe`, the current [high-accuracy file transcription model](https://developers.openai.com/api/docs/models/gpt-transcribe), with `languages=["fa"]` and a Persian-script prompt. This replaces `gpt-4o-transcribe`; TTS is unchanged. There is no silent fallback if your account cannot access the new model.

For recordings or uploads, optionally enter the conversation topic and relevant names/technical terms in the context box (up to 600 characters). This is sent as transcription context, not as a separate text-rewriting step. Include only terms actually relevant to the audio, since irrelevant hints can bias the transcript. See [OpenAI's context guidance](https://developers.openai.com/api/docs/guides/speech-to-text).

The migration and multipart parameters have been tested offline. Improved accuracy on your Persian recordings has **not** been measured: use the same recording and compare the result with a manually checked transcript. Listen to the preview for background noise, distortion, or missing speech before submitting.

## Record your voice in the browser

In **گفتار به متن**, use the **ضبط با میکروفون** tab and click the microphone, allow access, speak, and click **توقف ضبط**. Listen to the preview, then click **تبدیل صدا به متن** to send it using the current API key. Recording stops automatically after two minutes. Audio is only sent when you click the transcription button. File upload remains available.

Recording uses a supported WebM, MP4, or OGG format and releases the microphone when stopped. If permission is denied, allow the microphone in the browser's site settings. Use the localhost URL (or HTTPS for remote hosting), as required by [the browser microphone API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Input and output

TTS input is limited to 4,096 characters; split long passages if the model's token limit rejects them. STT accepts files up to 24 MB (25 MB total HTTP request limit), with extensions WAV, MP3, MP4, M4A, MPEG, MPGA, WebM, OGG, or FLAC. OpenAI validates the encoded audio. The server buffers each request separately and never saves uploads or uses client filenames as filesystem paths. TTS requests explicitly ask for WAV and verify the RIFF/WAVE signature before returning `audio/wav`.

The browser retains the existing routes and transcription response field. The interface includes:

- Separate speech-to-text and text-to-speech workspaces, responsive RTL layout, and a locally bundled Vazirmatn font (OFL license in `tts_fronted/fonts/`). No CDN or font download is needed at runtime.
- Microphone timer and live input-level display, preview, and explicit submission.
- A file-upload tab with drag-and-drop, file-size validation, filename display, and audio preview.
- Editable transcript, word count, clipboard copy, UTF-8 TXT download, and transfer to the TTS editor (up to 4,096 characters).
- TTS sample text, character count, WAV download, and playback speed controls. Playback speed changes only local playback.
- Server setup information dialog; inline error/loading messages and keyboard focus styles.

 API failures are displayed as messages instead of being played as audio. There is no silent local fallback.

## Conversation with an assistant / گفت‌وگو با دستیار

Select **گفت‌وگو با دستیار** to open **http://127.0.0.1:5000/call**. Press **شروع تماس** to connect. No microphone access or audio transmission occurs before Start; microphone tracks stay disabled until the voice session and backend sideband are ready. The browser exchanges its SDP offer through Flask; only Flask authenticates to OpenAI. No permanent or ephemeral API key reaches the browser.

The call uses **`gpt-live-1` over WebRTC for live Persian input** and the server's existing **`gpt-4o-mini-tts`** for each checked answer. Autonomous Live output is never attached to a speaker or inserted into history. This deliberate application-controlled playback avoids spoken waiting phrases, paraphrased quotations and competing answers. It adds backend/TTS latency; waiting is displayed on screen. Separate `/stt` and `/tts` remain available.

Mute disables the microphone track and sends the Live input-mute command. Speaking during an answer pauses its local audio immediately after voice detection; stale server work is discarded. End stops capture/playback, requests provider closure, allows up to five seconds for finalization, clears the caregiver profile and removes the document. **History is cleared by default.** The explicit **نگه‌داری تاریخچه پس از پایان تماس در این مرورگر** checkbox opts into local persistence. Only completed user/assistant exchanges are retained (up to 500 messages), and at most the latest ten exchanges seed the next call. Interrupted answers, UI status and duplicate events are excluded from model history. Saved text is readable by other users of the same browser profile; Clear ends the session and deletes it. Unchecking retention removes the saved copy immediately. TXT download remains available independently.

The visible transcript includes streaming recognized input and each checked answer, with interrupted answers labeled. An audio-ended receipt commits a completed exchange on the server and browser; duplicate receipts are idempotent. Long and growing bubbles follow the latest text. Scrolling upward deliberately pauses following; **رفتن به تازه‌ترین پیام** resumes it. Typed messages (up to 600 characters) work even when microphone permission is denied. No audio is captured before Start. A near-silent local media clock maintains WebRTC during mute/typed-only use without microphone content.

Temporary status-fetch failures retry without clearing text; a dropped WebRTC connection has a 15-second recovery window. Hiding the tab mutes input and pauses playback; closing it ends the call. Calls are capped at 15 minutes, with an abandoned browser heartbeat expiring after 120 seconds. A disconnected call may be restarted with completed exchanges still in the tab. Provider voice time remains billable while muted or waiting; End unused calls.

The optional caregiver section accepts a preferred name (80 characters), trusted contacts (600), orientation facts (1,000), and routine (1,000). Configure these before Start using verified facts. A home address is not evidence of current location; routine is not an appointment or medication schedule.

### Reviewed document retrieval

Before Start, a caregiver can upload a UTF-8 TXT/Markdown file or a text-based PDF, supply the reviewer's name/role and review date, and attest that an appropriate expert reviewed it. **This is caregiver attestation, not independent verification by the app.** Limits: 2 MB, 20–60,000 extracted characters, and 40 PDF pages; encrypted/scanned PDFs are unsupported. Inspect the extracted preview; a UTF-8 TXT export is preferable when Persian PDF extraction is scrambled.

Retrieval runs locally before each reply. It normalizes Persian/Arabic letter variants, removes common question words, and ranks passages by matching words, sending at most three relevant excerpts to the text model. For explicit short follow-ups such as “repeat that,” it can retrieve using the most recent user turn when the current words have no match. The model is instructed to use those excerpts first when they answer the question. Document answers show their excerpts; general everyday conversation is labeled in the interface; it no longer receives a repetitive spoken “به‌طور کلی” preamble. Caregiver-profile answers have a separate label. Citation IDs are checked against retrieved passages, but this does not prove the model interpreted them correctly.

This lightweight lexical search can miss synonyms or retrieve superficially similar passages. It is not semantic search or a medical knowledge system. Medical, medication, and safety questions conservatively receive caregiver/clinician or emergency guidance, including when a document is present; uploaded instructions never authorize medication changes.

Documents are held in this server process's RAM for up to two hours, with a maximum of 16 active uploads. End requests deletion; if that request cannot arrive, timed expiry still removes them. Restarting the server removes all documents. An expired/removed document produces an explicit error instead of silently changing sources. No embedding service, vector database, or full-document API upload is used.

### Live backend, safety, and limitations

The server creates `gpt-live-1` with `store=False`, voice `marin`, client delegation, and restricted browser event permissions. It attaches a private authenticated sideband WebSocket to the same session. The browser may mute/unmute or close; it cannot replace instructions or inject backend results. The answer model defaults to **`gpt-6-astra`** for both calls and `/conversation` (optional server `CONVERSATION_MODEL` override). It explicitly requests **Fast mode** with `service_tier="fast"` (premium API pricing; actual latency is not guaranteed), uses `reasoning.effort="low"`, `text.verbosity="low"`, and instructions for 1–2 direct Persian sentences, normally no more than 35 words. The 4,096-token budget includes internal reasoning and structured JSON; it is not the requested spoken length. Existing 600-character validation and safety rules remain. This upgrade affects reasoning/answer quality, not input recognition. It can cost more and take longer than the previous mini model. Model access and improved Persian answer quality have not been live-verified for this upgrade. See the [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra). Separate `/tts` and `/stt` keep their existing models and WAV/upload contracts.

For each recognized input, the backend retrieves document passages first, applies safety rules and generates a concise final reply. The reply is rendered to a validated WAV once and delivered through `/live/play`; only completion of that clip records the exchange. Results whose input version has changed are discarded. Live receives completed exchanges as quiet context, never as a command to speak again. Medication, urgent, lost and distress questions receive caregiver/clinician or emergency guidance. No contact or other external action is performed.

Input transcript deltas are not finalized turns: the agent uses a 1.2-second quiet debounce and the browser waits for local voice activity to stop before playback. Long pauses, weak/noisy microphones and echo can still split or interrupt a turn incorrectly. Voice detection uses three 25 ms samples above an RMS threshold, with browser echo cancellation. This is not a clinical speech detector. Headphones help avoid speaker echo. The caregiver panel exposes the last 12 checks: recognized input, retrieved passages and generated reply, without default logging.

Answers are instructed to be short and direct, without repeating requests, promises to answer, waiting phrases or unsolicited follow-up questions. A small checked, public-domain Shahnameh snapshot in `poetry.py` contains three opening couplets from [Ganjoor, Shahnameh, opening section](https://ganjoor.net/ferdousi/shahname/aghaz/sh1), verified on 2026-09-28. Supported requests return the actual verse with a source link, and “همان شعر” uses completed history. Unsupported named passages are declined instead of invented. This is a limited quotation collection, not a full Shahnameh search engine; caregiver uploads do not establish authorship. General creative poems must be labeled as original, not attributed to a real poet.

**Safety boundary:** only the checked text is sent to the separate TTS renderer. Rendering still uses a generative speech service and does not prove perfect pronunciation or word-for-word acoustic fidelity. The app is supportive conversation software, not clinical care, supervision, emergency detection or a replacement for a caregiver. Test natural speech and playback with a caregiver before patient use.

The WebRTC path requires microphone permission, localhost/HTTPS, browser WebRTC support, model access, API billing, and a network that allows the negotiated media connection. Voice time is billable even during silence/mute; backend text-model and TTS usage are additional. End unused calls. If autoplay is blocked, use the playback button.

References: [GPT-Live WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc), [client delegation](https://developers.openai.com/api/docs/guides/live-delegation), [server controls and playback limits](https://developers.openai.com/api/docs/guides/voice-server-controls), [Alzheimer's communication guidance](https://www.alz.org/help-support/caregiving/daily-care/communications).

### Conversation API and data handling

`POST /documents` accepts multipart `document`, `reviewed=true`, `reviewer`, and `reviewed_on` (ISO date). It returns an opaque `document_id`, review metadata, and extracted preview. `POST /documents/remove` accepts JSON `{"document_id":"…"}` and returns 204. IDs travel in request bodies rather than access-log URLs. Only retrieved excerpts are sent to OpenAI; review metadata and the full document stay local.

Live endpoints (JSON, same-origin browser requests):

- `POST /live/session`: SDP offer, optional profile/document ID and up to 20 alternating completed history messages → SDP answer and opaque call capability.
- `POST /live/status`: call capability → backend readiness and bounded caregiver diagnostics.
- `POST /live/text`: capability and typed message → server agent work.
- `POST /live/interrupt`: capability → invalidate old work and unfinished playback.
- `POST /live/play`: capability and current version → checked reply, source and base64 WAV; stale versions return 409.
- `POST /live/played`: capability and version → idempotent completion receipt that commits history.
- `POST /live/retry`: capability → retry failed backend work explicitly.
- `POST /live/end`: capability → idempotent session closure.

Call capabilities stay in tab memory and travel in request bodies. Backend transcripts, profile, and diagnostics are held only for the active call and erased on cleanup. At most four calls can exist per development-server process. This is a localhost application; add authentication and deployment controls before remote use.

The retained chained `POST /conversation` accepts either:

```json
{"text":"سلام، دوست دارم صحبت کنم.","history":[],"profile":{"preferred_name":""},"document_id":null}
```

Or multipart `audio` plus `context`, a JSON string containing `history`, `profile`, and optional `document_id`. Audio must use the same formats/24 MB limit as `/stt`. Current text/transcripts are capped at 2,000 characters. History is capped at **six alternating user/assistant messages (three exchanges)**, each at most 2,000 characters. Unknown profile fields, malformed history, and injected system/developer roles are rejected. The four profile keys are `preferred_name`, `trusted_contacts`, `orientation_facts`, and `routine`.

Response fields are `transcript`, `reply`, `category`, `source` (kind and cited excerpts), `audio_base64`, `audio_mime` (`audio/wav`), and `audio_error`. If voice synthesis fails, HTTP 200 includes the useful written reply with null audio and a readable audio-error message. The frontend handles the base64 WAV in a temporary object URL. Responses have `Cache-Control: no-store`.

Data sent to OpenAI by the retained chained endpoints:

| Stage | Sent to the API |
| --- | --- |
| Transcription | The submitted audio and a Persian language/script hint |
| Text reply | The current transcript/typed message, up to three recent exchanges, optional caregiver fields, up to three retrieved document excerpts (including document title), and fixed behavior instructions |
| Speech synthesis | The assistant's Persian reply and speaking-style instructions |

For Live calls, microphone audio goes directly to OpenAI. The backend receives transcripts; the text model receives the current message, up to ten completed exchanges, optional profile and retrieved excerpts. The final reply goes to the TTS API. Completed exchanges are also appended quietly to the Live context. The full caregiver document remains local. API credentials and call capabilities are never persisted in browser storage. By default, history exists only in active memory and End/page close clears it. Opt-in retention stores only completed text exchanges in this browser's localStorage, not audio, profile, document, API key or diagnostics. There is no server database or account synchronization.

The server does not log transcripts, audio, profile contents, keys or raw provider errors. Development access logs contain request metadata. Werkzeug may spool larger multipart uploads temporarily; uploaded files are not retained by the app.

Responses requests set **`store=False`**, with no provider conversation IDs or prior-response links. This disables Responses application-state storage, **not necessarily all provider retention**: abuse-monitoring logs and account-specific data policies can still apply. Clearing the page does not delete provider-held data. See [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data). The optional caregiver profile is not a secure multi-user record system; keep this development app on localhost.

## Tests without a key (no API calls)

```bash
.venv/bin/python -m unittest discover -s tests -v
# With Flask already running:
.venv/bin/python tests/smoke.py
```

The offline integration tests use the real OpenAI SDK with a mocked HTTP transport. They check outgoing model names, Persian language, multipart uploads, WAV/MIME/filename agreement, missing credentials, input limits, secret-safe error handling, network failures, and browser routes. The HTTP smoke test checks the real running Flask interface and validation without submitting billable input, even if a key is configured.

Verified in this workspace: all offline tests passed; real HTTP requests returned 200 for the interface, 400 for malformed input, and 503 for valid TTS/STT requests without a key. Live synthetic tests are described in `LIVE_EVALUATION.md`; these do not use patient data. Mock success does not establish actual Persian voice quality, recognition quality, account/model access, or API connectivity.

The microphone flow was also tested in headless Chrome with a simulated microphone and a mocked transcription response: record/stop, playable WebM preview, upload without browser credentials, repeat recording, existing file upload, and permission denial all passed. This does not verify your physical microphone or live recognition quality. To rerun:

```bash
.bootstrap/bin/pip install playwright
.bootstrap/bin/python tests/browser_recording.py
.bootstrap/bin/python tests/browser_ui.py
.bootstrap/bin/python tests/browser_conversation.py
```

The UI test also covers desktop/tablet/mobile widths, server settings, edited transcript copy/download, TTS transfer, WAV download, playback speed, and error recovery. Speech/conversation API responses in these browser tests are mocked; document upload/retrieval uses the local Flask server.

Conversation tests use mocked SDK requests to exercise typed/audio turns, bounded history, profile forwarding, storage settings, deterministic safety responses, model-classified risks, unsafe output fallback, missing keys, input validation, and provider failures. Document tests cover review attestation, limits, Persian normalization, retrieval and citations, unmatched general conversation, medical fallback with a document, fabricated citation rejection, and removal/expiry.

The call browser test mocks WebRTC/API events to cover no microphone access before Start, duplicate input suppression, exclusion of autonomous output, exactly one completed clip per version, interruption, history default-clear and opt-in persistence/reload, bounded next-call context, transcript growth and deliberate scrolling, transient fetch recovery, denied-microphone typing and mobile layout. Backend tests cover idempotent completion, interrupted/obsolete output exclusion, source-checked poetry and follow-up references. These do not establish physical-microphone accuracy or clinical safety.

## Complete live verification

For the opt-in billable comparison with synthetic Persian audio and a synthetic document:

```bash
TEST_BASE_URL=http://127.0.0.1:5000 .bootstrap/bin/python tests/evaluate_call_flow.py --live
```

It tests three actual multi-turn browser calls: source-checked poetry/repetition/meaning, document choices and follow-up, and medical fallback/personal uncertainty. It saves synthetic input/output and retrieval evidence under ignored `.cache/live-eval/`. `evaluate_live.py` retains the earlier paired comparison with `/conversation`; its fixed-duration waits are exploratory, not assertions of playback completion. This script deliberately persists **only its built-in test examples**; normal patient calls are not logged. See `LIVE_EVALUATION.md` for results and limitations.


After starting the server with your key, run:

```bash
# Makes two billable API requests: Persian synthesis, then transcription of that WAV.
.venv/bin/python tests/smoke.py --live
```

Or test manually:

```bash
curl --fail-with-body http://127.0.0.1:5000/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"سلام. امروز هوا خوب است."}' \
  -o /tmp/persian-openai.wav
curl --fail-with-body http://127.0.0.1:5000/stt \
  -F 'audio=@/tmp/persian-openai.wav;type=audio/wav'
```

For the conversation feature, after configuring the server key, open `/call`, upload a harmless reviewed sample document, and press Start. Try two spoken turns, a question answered by the document, an unrelated greeting, mute/unmute, a typed message, a repeated question, and End. Live calls are billed by voice-session duration plus backend text-model usage. Check the actual reply for Persian quality, factual grounding, and calm safety escalation before patient use. Account/model access, API connectivity, real transcription quality, generated speech, and free-form model safety still require live verification.

Also upload a real Persian recording and listen to the generated audio to assess quality. If calls fail, check the key, model permissions, API billing/quota, and connectivity to `api.openai.com`.

## Repository model inspection

The original selected `amir1` voice is absent. Both committed ONNX files are 133-byte Git LFS pointers. Fetching the Amir LFS object returned HTTP 404 (`Object does not exist on the server`). They are not usable weights and are not loaded by this API implementation. The original model files are preserved. Previously downloaded local models remain in ignored `model/downloaded/` and `.cache/whisper/` folders; no startup step uses them. The local inference packages and model-download setup script were removed from the active setup.

`har_and_cookies/` is historical material, not configuration or a dependency.

## Official API references

- [Text to speech: Persian support, voices, and WAV output](https://developers.openai.com/api/docs/guides/text-to-speech)
- [Speech to text](https://developers.openai.com/api/docs/guides/speech-to-text)



## Runner

From this checkout, run:

```bash
cd /home/newuser/Music/tts/tts-stt
./run.sh
```

The executable launcher uses `.venv/bin/python`, stops processes listening on TCP port **5000**, and starts `app.py`. It sends SIGTERM, waits about five seconds, and uses SIGKILL if an original listener remains. This also stops an unrelated application if it occupies the selected port. It requires `lsof` (`sudo apt install lsof`) and permission to stop the listener; it does not elevate privileges. Ctrl+C stops Flask.

Choose another port with `./run.sh 5001` or `PORT=5001 ./run.sh`. A command-line port takes precedence. You can invoke the runner by its absolute path from any directory.

The runner loads `.env` **only on the server**, in this order: exported environment variables, `tts-stt/.env`, then the parent workspace `.env` (your current `/home/newuser/Music/tts/.env`). Earlier values take precedence. Use this format, substituting your key locally:

```dotenv
OPENAI_API_KEY=your-key
```

Restart `./run.sh` after editing the file. Values are parsed as configuration, never executed as shell commands, and are not printed or sent to the browser. Both `.env` locations stay outside tracked source. Direct `python app.py` still requires an exported key. Alternatively, set it for the terminal without placing it in shell history:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
printf '\n'
./run.sh
```

Open **http://127.0.0.1:5000/call** (or your chosen port).

### If transcription stops after its first word

Restart `./run.sh`, open `http://127.0.0.1:5000/call`, and hard-refresh with **Ctrl+Shift+R** after code updates. An older running process previously served a cached HTML template alongside newer JavaScript, causing missing-element errors that were mislabeled as invalid service messages. The call page now reloads template changes, disables HTML caching and versions its script URL. Python/backend edits still require a server restart.
