"""Opt-in billable Persian interruption test; synthetic data only."""
import base64
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright
from evaluate_live import post, URL, ROOT, GUIDE

if '--live' not in sys.argv:raise SystemExit('Pass --live to authorize billable synthetic tests.')
folder=ROOT/'.cache/live-eval';folder.mkdir(parents=True,exist_ok=True)
text='نه، موسیقی دوست ندارم. انتخاب دیگر چیست؟'
fixture=folder/'followup.wav'
if not fixture.exists():fixture.write_bytes(post('/tts',{'text':text}))
with sync_playwright() as p:
    b=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True)
    c=b.new_context()
    c.add_init_script('''navigator.mediaDevices.getUserMedia=async()=>{
        window.ac=new AudioContext();window.dest=ac.createMediaStreamDestination();
        window.osc=ac.createOscillator();let gain=ac.createGain();gain.gain.value=.0001;osc.connect(gain).connect(dest);osc.start();
        return dest.stream;
    };window.fixture=async text=>{await ac.resume();const bytes=Uint8Array.from(atob(text),c=>c.charCodeAt(0));const source=ac.createBufferSource();source.buffer=await ac.decodeAudioData(bytes.buffer);source.connect(dest);source.start();};''')
    page=c.new_page();audits=[]
    def observe(r):
        if r.url.endswith('/live/status') and r.status==200:
            try:
                for a in r.json().get('audit',[]):
                    if a not in audits:audits.append(a)
            except Exception:pass
    page.on('response',observe)
    page.goto(URL+'/call');page.locator('#caregiverSettings summary').click()
    page.locator('#documentFile').set_input_files({'name':'synthetic-guide.txt','mimeType':'text/plain','buffer':GUIDE.encode()})
    page.locator('#documentReviewer').fill('Software fixture — not clinical');page.locator('#documentReviewDate').fill('2026-01-01');page.locator('#documentReviewed').check();page.locator('#uploadDocument').click()
    page.wait_for_function('documentId !== null && !documentBusy');page.locator('#caregiverSettings summary').click();page.locator('#startCall').click()
    try:
        page.wait_for_function('sessionStarted && backendReady',timeout=35000)
        page.evaluate('fixture',base64.b64encode((folder/'document.wav').read_bytes()).decode())
        page.wait_for_function("callPhase==='speaking' && [...document.querySelectorAll('#callTranscript li.assistant')].some(n=>n.textContent.includes('موسیقی'))",timeout=35000)
        import time
        started=time.monotonic()
        page.evaluate('fixture',base64.b64encode(fixture.read_bytes()).decode())
        page.wait_for_function("bargeWaiting && document.getElementById('replyAudio').muted",timeout=3000)
        interruption_ms=round((time.monotonic()-started)*1000)
        page.wait_for_function('completedHistory.length===2 && !playingReply',timeout=65000)
        result={'local_interruption_ms':interruption_ms,'playback_released':page.evaluate('!bargeWaiting'),'history':page.evaluate('conversationHistory()'),'intended_followup':text,'transcript':page.locator('#callTranscript').inner_text(),'audit':audits,'error':page.locator('#callError').inner_text()}
        assert 'موسیقی دوست ندارم' in result['history'][0]['content']
        assert 'گل' in result['history'][1]['content']
        (folder/'controlled-interruption-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        page.evaluate('endCall()');page.wait_for_timeout(5500);b.close()
