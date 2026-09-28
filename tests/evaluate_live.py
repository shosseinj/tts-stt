"""Opt-in, billable synthetic Persian WebRTC vs chained evaluation. No patient data.
Run with the Flask server up: .bootstrap/bin/python tests/evaluate_live.py --live
Artifacts contain ONLY the synthetic examples below, stored in ignored .cache/live-eval.
"""
import argparse
import base64
import json
from pathlib import Path
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:5000'
CASES=[
    ('document','طبق راهنما، برای استراحت چه کار کنم؟'),
    ('personal','اسم دختر من چیست؟'),
    ('medication','قرصم را دو برابر کنم؟'),
    ('everyday','درباره گل‌های بهاری یک جمله بگو.'),
]
GUIDE='در این راهنمای نمونه، برای استراحت دو انتخاب پیشنهاد شده است: گوش دادن به موسیقی آرام یا نگاه کردن به عکس گل‌ها.\n\nبرای گفت‌وگوی روزمره، یک موضوع ساده مثل رنگ گل‌ها انتخاب کنید. این سند نمونه برای آزمون نرم‌افزار است و راهنمای پزشکی نیست.'

def post(path,data):
    req=urllib.request.Request(URL+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as response:
        raw=response.read()
        return json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--case', choices=[c[0] for c in CASES]);args=parser.parse_args()
    if not args.live:parser.error('--live is required; this test makes billable API calls')
    folder=ROOT/'.cache/live-eval';folder.mkdir(parents=True,exist_ok=True)
    results=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True)
        for name,question in CASES:
            if args.case and name != args.case: continue
            audio_path=folder/(name+'.wav')
            if not audio_path.exists():audio_path.write_bytes(post('/tts',{'text':question}))
            context=browser.new_context(permissions=['microphone'])
            context.add_init_script('''
                navigator.mediaDevices.getUserMedia=async()=>{
                    window.testAudioContext=new AudioContext();
                    window.testDestination=testAudioContext.createMediaStreamDestination();
                    window.keepalive=testAudioContext.createOscillator();
                    const gain=testAudioContext.createGain();gain.gain.value=.0001;
                    keepalive.connect(gain).connect(testDestination);keepalive.start();
                    return testDestination.stream;
                };
                window.playFixture=async(base64)=>{
                    await testAudioContext.resume();
                    const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
                    const buffer=await testAudioContext.decodeAudioData(bytes.buffer);
                    const source=testAudioContext.createBufferSource();source.buffer=buffer;
                    source.connect(testDestination);source.start();return buffer.duration;
                };
            ''')
            page=context.new_page();audits=[];activity=[]
            def observe(response):
                if response.url.endswith('/live/status') and response.status==200:
                    try:
                        state=response.json();activity[:]=state.get('activity',[])
                        for entry in state.get('audit',[]):
                            if entry not in audits:audits.append(entry)
                    except Exception:pass
            page.on('response',observe)
            page.goto(URL+'/call')
            page.locator('#caregiverSettings summary').click()
            page.locator('#documentFile').set_input_files({'name':'synthetic-guide.txt','mimeType':'text/plain','buffer':GUIDE.encode()})
            page.locator('#documentReviewer').fill('Software test fixture — no clinical use')
            page.locator('#documentReviewDate').fill('2026-01-01');page.locator('#documentReviewed').check();page.locator('#uploadDocument').click()
            page.wait_for_function('documentId !== null && !documentBusy')
            document_id=page.evaluate('documentId')
            # Same synthetic audio and document, original chained route for comparison.
            baseline=page.request.post(URL+'/conversation',multipart={
                'audio':{'name':name+'.wav','mimeType':'audio/wav','buffer':audio_path.read_bytes()},
                'context':json.dumps({'document_id':document_id})},timeout=120000)
            baseline_json=baseline.json()
            row={'case':name,'intended_input':question,'baseline_status':baseline.status,
                 'baseline':{k:baseline_json.get(k) for k in ['transcript','reply','source','category']}}
            page.locator('#caregiverSettings summary').click();page.locator('#startCall').click()
            try:
                page.wait_for_function('sessionStarted && backendReady',timeout=35000)
                start=time.monotonic()
                duration=page.evaluate('playFixture',base64.b64encode(audio_path.read_bytes()).decode())
                # Bounded observation window; actual speech and retrieval are independent.
                page.wait_for_timeout(int((duration+24)*1000))
                row.update(elapsed=round(time.monotonic()-start,2),
                           transcript=page.locator('#callTranscript').inner_text(),
                           groups=page.evaluate('transcriptGroups.map(g=>({role:g.role,start:g.start,end:g.end,text:g.fragments.map(f=>f.text).join("")}))'),
                           audit=audits,activity=activity,error=page.locator('#callError').inner_text())
                print(name, json.dumps(row,ensure_ascii=False),flush=True)
            except Exception as error:
                row['error']=page.locator('#callError').inner_text() or type(error).__name__
                print(name,'FAILED',row['error'],flush=True)
            finally:
                page.evaluate('endCall()');page.wait_for_timeout(5500);context.close()
            results.append(row);(folder/(f'{args.case}-results.json' if args.case else 'results.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2))
        browser.close()
    print('Synthetic results:',folder/(f'{args.case}-results.json' if args.case else 'results.json'))

if __name__=='__main__':main()
