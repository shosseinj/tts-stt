"""Persian speech processing via OpenAI; API calls are made by the Flask server."""
import io
import base64
import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from openai import (
    OpenAI, APIError, APIConnectionError, APITimeoutError, APIStatusError,
    AuthenticationError, PermissionDeniedError, RateLimitError, BadRequestError,
)
from werkzeug.exceptions import HTTPException, BadRequest, BadGateway, RequestEntityTooLarge
from documents import upload_document, remove_document, retrieve_for_turn
from conversation import clean_text, validate_context, generate_reply, MAX_MESSAGE

app = Flask(__name__, static_folder="tts_fronted", static_url_path="/static",
            template_folder="tts_fronted")
# Leave room for multipart headers below the API's 25 MB upload limit.
app.config["MAX_CONTENT_LENGTH"] = 25_000_000
# Keep local template edits aligned with freshly served JavaScript, even with debug off.
app.config["TEMPLATES_AUTO_RELOAD"] = True
MAX_AUDIO_BYTES = 24_000_000
AUDIO_TYPES = {
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".mpeg": "audio/mpeg",
    ".mpga": "audio/mpeg", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".flac": "audio/flac",
}


class MissingAPIKey(Exception):
    pass


def get_client():
    # Only the server environment is trusted for credentials; browser headers/body are ignored.
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key and (not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key)):
        raise BadRequest("The API key contains invalid characters. Please enter it again.")
    if not key:
        raise MissingAPIKey()
    return OpenAI(api_key=key, base_url="https://api.openai.com/v1",
                  timeout=120.0, max_retries=0)


@app.errorhandler(MissingAPIKey)
def missing_key(_error):
    return jsonify(error="Set OPENAI_API_KEY in the server environment and restart the app. Use ./run.sh to load .env, or export the key before starting app.py.", code="missing_api_key"), 503


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.description), error.code


@app.errorhandler(APIError)
def api_error(error):
    # Do not expose/log raw provider errors: they may include input or credentials.
    app.logger.warning("OpenAI request failed (%s)", type(error).__name__)
    if isinstance(error, (AuthenticationError, PermissionDeniedError)):
        return jsonify(error="OpenAI authentication or access failed. Check your API key and model access."), 502
    if isinstance(error, RateLimitError):
        # Allowlisted codes/messages only: raw provider messages may contain private data.
        messages = {
            "insufficient_quota": "OpenAI reports insufficient quota for this API key. Check the key's project/organization billing and usage limits; this does not identify your overall credit balance.",
            "credit_balance_exhausted": "OpenAI reports exhausted prepaid credits for this key's organization. Verify the billing organization associated with the key.",
            "project_spend_limit_exceeded": "This API key's project reached its spending limit. Check the project's limits, even if credits remain.",
            "organization_spend_limit_exceeded": "This API key's organization reached its spending limit. Check organization limits, even if credits remain.",
            "organization_usage_limit_exceeded": "This API key's organization reached its approved usage limit. Check organization usage limits.",
            "rate_limit_exceeded": "OpenAI temporarily limited request/token throughput. Wait before retrying and check model/project rate limits. This is not a credit-balance error.",
            "slow_down": "OpenAI asks you to slow down requests. Wait before retrying; this is not a credit-balance error.",
        }
        code = error.code if error.code in messages else (
            "insufficient_quota" if error.type == "insufficient_quota" else
            "rate_limit_exceeded" if error.type == "rate_limit_error" else "unclassified_429")
        app.logger.warning("OpenAI limit classification: %s", code)
        return jsonify(code=code, error=messages.get(code,
            "OpenAI rejected this request with HTTP 429 without a recognized reason. This alone does not establish insufficient credit.")), 429
    if isinstance(error, APITimeoutError):
        return jsonify(error="OpenAI timed out. Please try again."), 504
    if isinstance(error, APIConnectionError):
        return jsonify(error="Cannot connect to OpenAI. Check the server's internet connection."), 502
    if isinstance(error, BadRequestError):
        return jsonify(error="OpenAI rejected the input. Try shorter text or a valid supported audio file."), 400
    if isinstance(error, APIStatusError) and error.status_code == 413:
        return jsonify(error="Audio is too large for OpenAI. Upload a shorter recording."), 413
    return jsonify(error="OpenAI speech processing failed. Please try again later."), 502


@app.get("/")
def home():
    return render_template("index.html")


def synthesize_audio(client, text, supportive=False):
    instructions = "Speak naturally and clearly in Persian (Farsi)."
    if supportive:
        instructions += " Use a calm, respectful adult voice, a gentle pace and short pauses. Do not add words."
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts", voice="coral", input=text,
        instructions=instructions, response_format="wav",
    ) as response:
        audio = response.read()
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise BadGateway("OpenAI returned an unexpected audio format.")
    return audio


def read_upload(upload):
    if upload is None:
        raise BadRequest("No audio file provided.")
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in AUDIO_TYPES:
        raise BadRequest("Upload WAV, MP3, MP4, M4A, MPEG, MPGA, WebM, OGG, or FLAC audio.")
    audio = upload.read(MAX_AUDIO_BYTES + 1)
    if not audio:
        raise BadRequest("Audio file is empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise RequestEntityTooLarge("Audio must be at most 24 MB.")
    return ("speech" + extension, audio, AUDIO_TYPES[extension])


def transcribe_audio(client, audio, context=""):
    result = client.audio.transcriptions.create(
        model="gpt-transcribe", languages=["fa"], response_format="json",
        prompt="گفتار فارسی است. متن با خط فارسی و نشانه‌گذاری نوشته شود."
               + (" زمینهٔ گفت‌وگو و واژه‌های مرتبط: " + context if context else ""),
        file=audio,
    )
    if not isinstance(result.text, str):
        raise BadGateway("OpenAI returned an unexpected transcription response.")
    return result.text


@app.post("/tts")
def text_to_speech():
    data = request.get_json(silent=True)
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="Provide a nonempty text string in a JSON object."), 400
    if len(text) > 4096:
        return jsonify(error="Text must be at most 4096 characters; split long passages."), 400
    with get_client() as client:
        audio = synthesize_audio(client, text.strip())
    result = send_file(io.BytesIO(audio), mimetype="audio/wav",
                       download_name="speech.wav", as_attachment=True)
    result.headers["Cache-Control"] = "no-store"
    return result


@app.post("/stt")
def speech_to_text():
    audio = read_upload(request.files.get("audio"))
    context = clean_text(request.form.get("context", ""), "transcription context", 600)
    with get_client() as client:
        transcript = transcribe_audio(client, audio, context)
    result = jsonify(transcription=transcript)
    result.headers["Cache-Control"] = "no-store"
    return result


@app.get("/call")
def call_page():
    response = app.make_response(render_template("call.html", call_asset_version=(Path(app.static_folder) / "conversation.js").stat().st_mtime_ns))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/documents")
def add_document():
    result = jsonify(upload_document(request.files.get("document"), request.form.get("reviewed"),
                                     request.form.get("reviewer", ""), request.form.get("reviewed_on", "")))
    result.headers["Cache-Control"] = "no-store"
    return result


@app.post("/documents/remove")
def delete_document():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Provide a document ID.")
    remove_document(data.get("document_id"))
    return "", 204


@app.post("/conversation")
def converse():
    # Stateless: profile and a bounded recent history are supplied by this active tab.
    # No database, cookies, provider conversation IDs, or server-side session history.
    if request.is_json:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise BadRequest("Provide a JSON object.")
        transcript = clean_text(data.get("text"), "message", MAX_MESSAGE, True)
        audio = None
    else:
        audio = read_upload(request.files.get("audio"))
        try:
            data = json.loads(request.form.get("context", "{}"))
        except ValueError:
            raise BadRequest("Invalid conversation context.") from None
        if not isinstance(data, dict):
            raise BadRequest("Invalid conversation context.")
        transcript = None
    history, profile = validate_context(data.get("history", []), data.get("profile", {}))
    with get_client() as client:
        if audio is not None:
            transcript = transcribe_audio(client, audio).strip()
            if not transcript:
                raise BadRequest("No speech detected. Please record again or type a message.")
            if len(transcript) > MAX_MESSAGE:
                raise BadRequest("Please use a shorter message (at most 2000 characters).")
        passages = retrieve_for_turn(data.get("document_id"), transcript, history)
        reply, category, source = generate_reply(client, transcript, history, profile,
                                                os.environ.get("CONVERSATION_MODEL", "gpt-4.1-mini"), passages)
        audio_error = None
        try:
            speech = base64.b64encode(synthesize_audio(client, reply, supportive=True)).decode("ascii")
        except (APIError, BadGateway):
            # Preserve the written reply, especially safety guidance, if voice fails.
            speech = None
            audio_error = "پخش صوتی آماده نشد. لطفاً پاسخ نوشته‌شده را بخوانید."
        result = jsonify(transcript=transcript, reply=reply, category=category, source=source,
                         audio_base64=speech, audio_mime="audio/wav", audio_error=audio_error)
        result.headers["Cache-Control"] = "no-store"
        return result


from live_call import live
app.register_blueprint(live)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
