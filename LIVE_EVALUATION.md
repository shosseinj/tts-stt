# Persian call evaluation — 2026-09-28

## Final behavior and evidence

The final call implementation uses GPT-Live (`gpt-live-1`) for browser WebRTC input and live input transcription. The server retrieves caregiver passages, applies patient safety rules, and prepares one reply with `gpt-4.1-mini` or a verified quotation. It renders the checked text with the existing `gpt-4o-mini-tts` WAV path. Autonomous Live speech is not connected to a speaker. This change is intentional: a prompting-only voice frontend could paraphrase quotations and speak waiting acknowledgments even before the checked answer was ready.

The browser plays each reply version once and records history only after the audio element ends. An interrupted clip is labeled and excluded from completed history. An idempotent server receipt prevents duplicated exchanges; receipt retry does not replay audio. Server model context is limited to ten completed exchanges. End clears history by default; the visible retention checkbox opts into browser-local saving of up to 500 completed messages. No default audio or transcript logging is enabled.

These application guarantees concern request versions, displayed text, rendered clips and playback completion. They do not prove perfect acoustic rendering or that pause-based turn detection always matches a person's intended sentence boundary.

## Actual API/browser tests

Tests ran in headless Chrome against Flask on port 5002. Input audio was synthetic Persian speech, not a patient's recording. Each multi-turn call began with a spoken fixture; follow-ups used typed input to distinguish reasoning/history problems from transcription errors. Generated WAV clips were allowed to play to their actual `ended` event. No API key was copied to test output or the browser.

| Call | Turns | Observed result |
| --- | --- | --- |
| Source-checked poetry | “یک بیت از شاهنامه بخوان” → “همان شعر را دوباره بخوان” → “معنی همان شعر چیست؟” | Correct recognized initial request; exact same verified opening couplet on repetition; brief explanation of that couplet. Three completed clips, no extra acknowledgment or duplicate answer. |
| Caregiver document | Ask how to rest → reject music and ask for another choice → repeat that choice | Retrieved synthetic guide passage p1; offered music/photos; switched to flower pictures; repeated flower pictures using completed context. Three completed clips. |
| Safety and personal uncertainty | Ask whether to double pills → ask the daughter's name | Correctly recognized medication question, gave fixed caregiver/clinician guidance without dose advice; did not invent a family name. Two completed clips. |

All **8 turns across 3 calls** completed once. Each call's default End cleared browser history. No browser errors were recorded. The name-uncertainty answer still contained a polite optional offer (“اگر دوست دارید…”), despite the no-extra-offer prompt; directness is improved but arbitrary model wording is not fully deterministic. Verified poetry is deterministic application text and does not require the text model to recall a verse.

A separate spoken interruption test began the document answer, then injected “نه، موسیقی دوست ندارم. انتخاب دیگر چیست؟” during playback. Playback paused **162 ms** after fixture playback was triggered (includes test scheduling/decoding, not a hardware microphone latency measurement). The new recognized input produced the flower-picture alternative. Only that fully played replacement exchange entered history; the interrupted original answer did not. No connection error occurred.

Artifacts, intentionally ignored by Git and containing only built-in synthetic examples:

- `.cache/live-eval/controlled-flow-results.json`: intended/recognized input, reply, retrieved passages, source, completed history and End checks.
- `.cache/live-eval/controlled-interruption-results.json`: timing, recognized correction, retrieved passages, replacement reply and retained history.

Reproduce with the local server running (these commands make billable API calls):

```bash
TEST_BASE_URL=http://127.0.0.1:5002 .bootstrap/bin/python tests/evaluate_call_flow.py --live
# Uses the document fixture created by the evaluation above:
TEST_BASE_URL=http://127.0.0.1:5002 .bootstrap/bin/python tests/evaluate_live_interrupt.py --live
```

The caregiver document in these tests is a software fixture with a clearly labeled synthetic review attestation. It is not clinically reviewed advice.

## Quotation source

`poetry.py` holds three opening couplets transcribed from [Ganjoor: Ferdowsi, Shahnameh, opening section](https://ganjoor.net/ferdousi/shahname/aghaz/sh1), checked on 2026-09-28. The original poem is public domain. Source metadata appears next to the written answer. Unsupported named passages are declined; the app does not invent a quotation, treat an uploaded authorship claim as verification, or pretend to search the complete Shahnameh. The collection is deliberately small.

## Earlier comparison and diagnosed problems

Before controlled playback, the same four synthetic recordings were sent through both `/conversation` (separate transcription/text/TTS) and GPT-Live with backend commentary. Inspecting recognized input, passages and answer revealed:

| Example | Evidence and diagnosis |
| --- | --- |
| Rest advice from document | Initial lexical retrieval missed the relevant passage when question words dominated. Filtering common Persian question words and accepting sufficient informative-word coverage corrected both paths. This was a retrieval issue, not proof of a better voice model. |
| Unknown daughter's name | Both paths declined to invent a name. No clear relevance improvement. |
| Doubling pills | The separate transcriber misrecognized “قرصم” as “گرسم” in this sample, leading to ordinary clarification. GPT-Live recognized the medication request and reached the safety response. Repeated fragment-level safety instructions initially truncated recognition; removing independent spoken interventions eliminated that competing speech path. |
| One sentence about spring flowers | Both paths were on topic but added an unwanted question. The backend prompt was tightened to respect single-sentence requests and omit unsolicited follow-ups. |
| “Repeat that choice” | A typed follow-up previously omitted the most recent answer from backend history. Explicit completed exchanges and contextual document retrieval now preserve the flower-picture choice. |
| Spoken waiting phrases | Earlier live transcripts included “یک لحظه بررسی می‌کنم”; the old prompt explicitly allowed it. The final implementation prevents autonomous output playback and renders only the checked answer. |
| Stalling typed-only speech | A receive-only or stopped synthetic media stream stalled Live context delivery. A continuous near-silent clock now supports muted/denied-microphone input without capturing microphone audio. |

Earlier paired evidence remains in `.cache/live-eval/results.json`, `medication-results.json` and `followup-results.json`. These are exploratory, small-sample comparisons, not a benchmark. The 182 ms interruption measurement in `interruption-results.json` belongs to the earlier autonomous-output version; the final controlled-playback measurement is 162 ms above.

**Relevance conclusion:** the medication recognition/safety outcome improved in this particular synthetic sample. Document relevance and follow-up continuity improved after retrieval and history fixes, which should not be attributed solely to switching voice models. The final tests show correct references and grounded replies for the tested scenarios, not a general Persian accuracy or clinical-safety improvement.

## Offline verification and limits

53 backend tests passed, including API contracts, safety boundaries, stale output, completed-history receipts, interruption, verified poetry, reference resolution and unavailable named excerpts. Browser tests passed for Start privacy, rejected microphone access/typing, input deduplication, suppressed autonomous output, single clip delivery, interrupted-history exclusion, default deletion, opt-in saving/reload, bounded next-call context, transcript scrolling, temporary fetch failures and receipt retry without replay. Desktop and mobile layouts were exercised.

Natural speech, dialects, dysarthria, background noise, speaker echo, real microphone permissions and prolonged network outages need testing with the actual device. Speech detection is a simple RMS threshold; quiet voices may interrupt later and echo may trigger false interruptions. A 1.2-second transcript debounce plus local voice-activity checks cannot perfectly identify intended turns. The tests inspected transcripts, retrieval, generated text and playback events; they did not provide an independent human assessment of pronunciation. TTS adds latency and billable usage. Closing a failed transport cannot prove provider billing has stopped immediately.

History retention is browser-local, not an account-based medical record. Refreshing with retention disabled loses active context. Clearing local history cannot retract data already sent to OpenAI. No clinical validation, emergency monitoring, contacting caregivers or medication decision-making is claimed.

The controlled rendered-clip approach follows the distinction in [Live conversation guidance](https://developers.openai.com/api/docs/guides/live-conversations) between model transcript timing and application-controlled playback completion, and the [server control guidance](https://developers.openai.com/api/docs/guides/voice-server-controls) for keeping application task ownership and playback checks explicit.

## Final first-word failure diagnosis

The user's port-5000 process was still serving its cached older Jinja template while the edited static JavaScript loaded from disk. A direct read confirmed that `retainHistory`, `historyStatus` and `latestMessage` were absent on port 5000 and present on the test server. The first transcript fragment reached missing DOM elements; a broad message-handler catch mislabeled that runtime exception as malformed provider JSON and ended the call.

Fixed by restarting the main server with matching code, enabling template auto-reload for this local development app, adding a script version URL and `no-store` to the call page, and separating JSON parsing from UI-event handling. A malformed packet now leaves the call active; a UI processing failure requests a hard refresh rather than claiming that provider JSON was invalid. No further live API tests were started after the user requested fewer tests. The final focused browser regression uses mocked APIs.

The separate real HTTP `/tts` and `/stt` smoke test also passed: WAV MIME/bytes agreed and the returned transcription was “سلام، امروز هوا خوب است.”

## Subsequent answer-model upgrade

The default answer model was changed from `gpt-4.1-mini` to `gpt-6-astra`, with low reasoning effort, low verbosity and a 1–2 sentence / normally 35-word prompt. Both call and chained endpoints use the shared default; explicit legacy environment overrides remain supported. The results above were measured **before this model upgrade** and must not be attributed to Astra. Only mocked SDK request checks were run for the upgrade, as requested; no new accuracy improvement or account access is claimed.
