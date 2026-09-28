"""Real HTTP checks; --live explicitly opts into two billable API calls."""
import argparse
import io
import json
import os
import urllib.error
import urllib.request
import wave

URL = os.environ.get("TEST_URL", "http://127.0.0.1:5000")


def request(path, body=None, content_type=None):
    req = urllib.request.Request(URL + path, body, {"Content-Type": content_type} if content_type else {})
    try:
        response = urllib.request.urlopen(req, timeout=150)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def upload(audio):
    boundary = "speech-smoke-boundary"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="speech.wav"\r\n'
            'Content-Type: audio/wav\r\n\r\n').encode() + audio + f'\r\n--{boundary}--\r\n'.encode()
    return request("/stt", body, f"multipart/form-data; boundary={boundary}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make two billable OpenAI calls via Flask")
    args = parser.parse_args()
    assert request("/")[0] == 200
    assert request("/static/script.js")[0] == 200
    assert request("/tts", b"{}", "application/json")[0] == 400
    assert request("/stt", b"", "application/octet-stream")[0] == 400
    if not args.live:
        # Input validation above never calls OpenAI, even if the server has a key.
        print("PASS: real HTTP interface and validation. Live speech tests skipped; use --live with a configured server.")
    else:
        status, headers, audio = request("/tts", json.dumps({"text": "سلام. امروز هوا خوب است."}).encode(), "application/json")
        assert status == 200, (status, audio)
        assert headers.get_content_type() == "audio/wav"
        with wave.open(io.BytesIO(audio)) as wav:
            assert len(wav.readframes(1000)) > 0
        status, _, result = upload(audio)
        assert status == 200, (status, result)
        transcript = json.loads(result)["transcription"]
        assert any("\u0600" <= c <= "\u06ff" for c in transcript), transcript
        print("PASS: live OpenAI WAV synthesis and Persian transcription:", transcript)
