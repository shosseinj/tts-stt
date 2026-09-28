"""Optional Chrome test with a simulated microphone and mocked /stt (no API calls).
Run: .bootstrap/bin/pip install playwright
     .bootstrap/bin/python tests/browser_recording.py
"""
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path="/usr/bin/google-chrome", headless=True,
        args=["--use-fake-device-for-media-stream"],
    )
    context = browser.new_context(permissions=["microphone"])
    page = context.new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def transcribe(route):
        requests.append(route.request)
        route.fulfill(json={"transcription": "سلام، این یک آزمایش است."})

    page.route("**/stt", transcribe)
    page.goto("http://127.0.0.1:5000/")
    page.locator(".context-options summary").click()
    page.locator("#transcriptionContext").fill("گفتگو دربارهٔ شیراز")
    page.locator("#recordButton").click()
    page.wait_for_function("recorder && recorder.state === 'recording'")
    page.wait_for_timeout(1500)
    assert page.locator("#recordingTranscribeButton").is_disabled()
    assert not requests, "Recording must not upload automatically"
    page.locator("#stopRecordButton").click()
    page.wait_for_function("recording !== null && microphone === null")
    assert page.locator("#recordingPreview").is_visible()
    assert page.evaluate("recording.size") > 0
    assert page.evaluate("recording.type").startswith("audio/webm")
    page.locator("#recordingTranscribeButton").click()
    page.wait_for_function("!transcribing")
    assert "سلام" in page.locator("#transcriptionResult").input_value()
    assert "x-openai-api-key" not in requests[-1].headers
    assert b'filename="recording.webm"' in requests[-1].post_data_buffer
    assert b"\x1a\x45\xdf\xa3" in requests[-1].post_data_buffer, "Expected real WebM bytes"
    # Existing upload uses the same endpoint and key.
    page.locator("#uploadTab").click()
    page.locator("#audioInput").set_input_files({"name": "upload.wav", "mimeType": "audio/wav", "buffer": b"test-upload"})
    page.locator("#uploadTranscribeButton").click()
    page.wait_for_function("!transcribing")
    assert b'filename="upload.wav"' in requests[-1].post_data_buffer
    assert "گفتگو دربارهٔ شیراز".encode() in requests[-1].post_data_buffer
    assert len(requests) == 2
    page.locator("#recordTab").click()
    # New recording replaces the previous preview and re-enables submission on stop.
    page.locator("#recordButton").click()
    page.wait_for_function("recorder && recorder.state === 'recording'")
    assert page.locator("#recordingTranscribeButton").is_disabled()
    page.wait_for_timeout(300)
    page.locator("#stopRecordButton").click()
    page.wait_for_function("recording !== null && microphone === null")
    denied = context.new_page()
    denied.add_init_script("navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Denied', 'NotAllowedError'); }")
    denied.goto("http://127.0.0.1:5000/")
    denied.locator("#recordButton").click()
    denied.wait_for_function("!requestingMicrophone")
    assert "رد شد" in denied.locator("#recordingStatus").inner_text()
    assert denied.locator("#recordButton").is_enabled()
    assert not errors, errors
    browser.close()
    print("PASS: microphone recording, preview, WebM upload, server-only credentials, repeat recording, file upload, permission denial; no API calls.")
