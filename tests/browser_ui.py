"""UI regression checks using Chrome; API routes are mocked, with no paid calls."""
import io
import wave
from playwright.sync_api import sync_playwright

buf = io.BytesIO()
with wave.open(buf, 'wb') as audio:
    audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
    audio.writeframes(b'\x00\x00' * 24000)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1050}, permissions=['clipboard-read', 'clipboard-write'])
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.route('**/tts', lambda r: r.fulfill(body=buf.getvalue(), content_type='audio/wav'))
    page.route('**/stt', lambda r: r.fulfill(json={'transcription': 'سلام، امروز روز خوبی است.'}))
    page.goto('http://127.0.0.1:5000/')
    page.evaluate('document.fonts.ready')
    page.screenshot(path='/tmp/ava-desktop.png', full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('.connection-button').click()
    assert 'OPENAI_API_KEY' in page.locator('#keyDialog').inner_text()
    assert page.locator('#apiKeyInput').count() == 0
    page.keyboard.press('Escape')
    page.locator('#uploadTab').click()
    page.locator('#audioInput').set_input_files({'name': 'voice.wav', 'mimeType': 'audio/wav', 'buffer': buf.getvalue()})
    page.locator('#uploadTranscribeButton').click()
    page.wait_for_function('!transcribing')
    page.locator('#transcriptionResult').fill('این متن ویرایش شده است.')
    page.locator('#copyTranscript').click()
    assert page.evaluate('navigator.clipboard.readText()') == 'این متن ویرایش شده است.'
    with page.expect_download() as download:
        page.locator('#downloadTranscript').click()
    assert download.value.suggested_filename == 'ava-transcript.txt'
    page.locator('#readTranscript').click()
    assert page.locator('#ttsWorkspace').is_visible()
    assert page.locator('#textInput').input_value() == 'این متن ویرایش شده است.'
    page.locator('#ttsButton').click()
    page.wait_for_function('!ttsBusy')
    assert page.locator('#audioPlayer').is_visible()
    page.locator('#playbackRate').select_option('1.25')
    assert page.evaluate('document.getElementById("audioPlayer").playbackRate') == 1.25
    with page.expect_download() as download:
        page.locator('#downloadAudio').click()
    assert download.value.suggested_filename == 'ava-speech.wav'
    page.route('**/tts', lambda r: r.fulfill(status=429, json={'error': 'Quota exhausted'}))
    page.locator('#ttsButton').click()
    page.wait_for_function('!ttsBusy')
    assert page.locator('#ttsError').is_visible()
    assert page.locator('#ttsButton').is_enabled()
    page.locator('#nav-stt').click()
    page.locator('#clearTranscript').click()
    assert page.locator('#transcriptEmpty').is_visible()
    page.locator('#recordTab').click()
    for width in [390, 768, 1024]:
        page.set_viewport_size({'width': width, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        if width == 390:
            page.screenshot(path='/tmp/ava-mobile.png', full_page=True)
            assert page.locator('#nav-tts').is_visible()
            page.locator('.connection-button').click()
            assert page.locator('#keyDialog').is_visible()
            page.keyboard.press('Escape')
    assert not errors, errors
    browser.close()
    print('PASS: responsive layout, server settings, editable transcript, clipboard, TXT/WAV downloads, TTS transfer, playback speed, API error recovery; no API calls.')
