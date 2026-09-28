"""Offline integration tests using the real OpenAI SDK and a mock HTTP transport."""
import io
import json
import os
import unittest
from unittest.mock import patch
import wave

import httpx2 as httpx
from openai import OpenAI
import app as backend


def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as output:
        output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * 2400)
    return buf.getvalue()


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-only"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = backend.app.test_client()
        self.requests = []
        self.response = httpx.Response(200, json={"text": "سلام دنیا"})

        def handler(request):
            self.requests.append(request)
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def factory(**kwargs):
            return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

        self.factory = patch.object(backend, "OpenAI", side_effect=factory)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def upload(self, data=b"audio", filename="../../voice.wav"):
        return self.client.post("/stt", data={"audio": (io.BytesIO(data), filename)})

    def test_tts_sdk_and_wav(self):
        self.response = httpx.Response(200, content=wav_bytes(), headers={"Content-Type": "audio/wav"})
        response = self.client.post("/tts", json={"text": "سلام", "api_key": "ignored-client-key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "audio/wav")
        self.assertEqual(response.data, wav_bytes())
        self.assertIn("speech.wav", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        sent = self.requests[0]
        self.assertEqual(str(sent.url), "https://api.openai.com/v1/audio/speech")
        self.assertEqual(sent.headers["Authorization"], "Bearer offline-test-only")
        data = json.loads(sent.content)
        self.assertEqual(data["model"], "gpt-4o-mini-tts")
        self.assertEqual(data["input"], "سلام")
        self.assertEqual(data["response_format"], "wav")
        self.assertEqual(data["voice"], "coral")

    def test_stt_sdk_and_persian(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"transcription": "سلام دنیا"})
        sent = self.requests[0]
        self.assertEqual(sent.url.path, "/v1/audio/transcriptions")
        self.assertIn(b'gpt-transcribe', sent.content)
        self.assertIn(b'name="languages[]"\r\n\r\nfa', sent.content)
        self.assertIn(b'filename="speech.wav"', sent.content)
        self.assertNotIn(b'../../', sent.content)

    def test_browser_credentials_are_ignored(self):
        headers = {"X-OpenAI-API-Key": "browser-test-only"}
        self.response = httpx.Response(200, content=wav_bytes())
        response = self.client.post("/tts", json={"text": "سلام", "api_key": "body-key"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests[-1].headers["Authorization"], "Bearer offline-test-only")
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            response = self.client.post("/tts", json={"text": "سلام"}, headers=headers)
            self.assertEqual(response.status_code, 503)

    def test_transcription_context(self):
        response = self.client.post("/stt", data={"audio": (io.BytesIO(b"audio"), "voice.webm"), "context": "گفتگو دربارهٔ شیراز"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("گفتگو دربارهٔ شیراز".encode(), self.requests[-1].content)
        self.assertNotIn(b'name="language"', self.requests[-1].content)
        response = self.client.post("/stt", data={"audio": (io.BytesIO(b"audio"), "voice.webm"), "context": "a" * 601})
        self.assertEqual(response.status_code, 400)

    def test_missing_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            for response in (self.client.post("/tts", json={"text": "سلام"}), self.upload()):
                self.assertEqual(response.status_code, 503)
                self.assertIn("OPENAI_API_KEY", response.json["error"])
                self.assertEqual(response.json["code"], "missing_api_key")
        self.assertEqual(self.requests, [])

    def test_invalid_input(self):
        for data in ({}, [], {"text": 3}, {"text": " "}, {"text": "a" * 4097}):
            self.assertEqual(self.client.post("/tts", json=data).status_code, 400)
        self.assertEqual(self.client.post("/tts", data="broken", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/stt").status_code, 400)
        self.assertEqual(self.upload(b"").status_code, 400)
        self.assertEqual(self.upload(filename="file.txt").status_code, 400)
        self.assertEqual(self.requests, [])

    def test_size_limits(self):
        with patch.object(backend, "MAX_AUDIO_BYTES", 10):
            self.assertEqual(self.upload(b"a" * 11).status_code, 413)
        with patch.dict(backend.app.config, {"MAX_CONTENT_LENGTH": 10}):
            response = self.upload()
            self.assertEqual(response.status_code, 413)
            self.assertIn("error", response.json)
        self.assertEqual(self.requests, [])

    def test_provider_errors_are_sanitized(self):
        for code, expected in ((400, 400), (401, 502), (403, 502), (413, 413), (429, 429), (500, 502)):
            self.response = httpx.Response(code, json={"error": {"message": "sensitive-provider-detail", "type": "error"}})
            for response in (self.upload(), self.client.post("/tts", json={"text": "سلام"})):
                self.assertEqual(response.status_code, expected)
                self.assertNotIn(b"sensitive-provider-detail", response.data)
                self.assertNotIn(b"offline-test-only", response.data)

    def test_rate_limit_reason_is_preserved_without_sensitive_details(self):
        for code in ("insufficient_quota", "credit_balance_exhausted", "project_spend_limit_exceeded",
                     "organization_spend_limit_exceeded", "organization_usage_limit_exceeded",
                     "rate_limit_exceeded", "slow_down", "private-unknown-code"):
            self.response = httpx.Response(429, json={"error": {
                "code": code, "type": "error", "message": "sensitive-provider-detail"}})
            response = self.upload()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json["code"], code if code != "private-unknown-code" else "unclassified_429")
            self.assertNotIn(b"sensitive-provider-detail", response.data)
            self.assertNotIn(b"private-unknown-code", response.data)
        self.response = httpx.Response(429, json={"error": {"type": "insufficient_quota"}})
        self.assertEqual(self.upload().json["code"], "insufficient_quota")

    def test_network_errors(self):
        for error, code in ((httpx.ReadTimeout("timeout"), 504), (httpx.ConnectError("offline"), 502)):
            self.response = error
            self.assertEqual(self.upload().status_code, code)

    def test_unexpected_audio(self):
        self.response = httpx.Response(200, content=b"not a wav")
        self.assertEqual(self.client.post("/tts", json={"text": "سلام"}).status_code, 502)

    def test_interface_no_credentials(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"offline-test-only", response.data)
        with self.client.get("/static/script.js") as asset:
            self.assertEqual(asset.status_code, 200)
        self.assertEqual(self.client.get("/.env").status_code, 404)


if __name__ == "__main__":
    unittest.main()
