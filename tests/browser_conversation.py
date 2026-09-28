"""Browser behavior with mocked Live APIs; no paid calls or patient recordings."""
import os
import base64
import io
import wave
from playwright.sync_api import sync_playwright
BASE_URL=os.environ.get('TEST_BASE_URL','http://127.0.0.1:5000')
buf=io.BytesIO()
with wave.open(buf,'wb') as audio:
    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\x00\x00'*24000*30)
WAV=base64.b64encode(buf.getvalue()).decode()
FAKE_RTC='''
window.micRequests=0;const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia=(...args)=>{micRequests++;return original(...args);};
window.sentEvents=[];window.testMicRms=0;
AnalyserNode.prototype.getFloatTimeDomainData=function(array){array.fill(testMicRms)};
window.RTCPeerConnection=class {
 constructor(){window.testPeer=this;this.connectionState='new';}
 addTrack(){} createDataChannel(){this.dc={readyState:'open',send:e=>sentEvents.push(JSON.parse(e)),close(){this.readyState='closed';}};return this.dc;}
 async createOffer(){return {type:'offer',sdp:'test-offer'};} async setLocalDescription(){}
 async setRemoteDescription(){this.connectionState='connected';this.emit({type:'session.started'});}
 emit(e){this.dc.onmessage({data:JSON.stringify(e)});} close(){this.connectionState='closed';}
};
'''
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--use-fake-device-for-media-stream'])
    context=browser.new_context(permissions=['microphone'],viewport={'width':1440,'height':1000})
    context.add_init_script(FAKE_RTC)
    page=context.new_page();errors=[];sessions=[];receipts=[];ends=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def configure(target):
        def create(r):
            sessions.append(r.request.post_data_json)
            r.fulfill(status=201,json={'token':'capability','session':{'id':'live_fake'},'transport':{'sdp':'answer'}})
        target.route('**/live/session',create)
        target.route('**/live/status',lambda r:r.fulfill(json={'ready':True,'closed':False,'working':False,'error':None,'audit':[]}))
        for path in ('retry','interrupt','text'):
            target.route('**/live/'+path,lambda r:r.fulfill(status=204))
        target.route('**/live/play',lambda r:r.fulfill(json={'version':r.request.post_data_json['version'],'transcript':'یک شعر کوتاه بخوان','reply':'به نام خداوند جان و خرد\nکز این برتر اندیشه برنگذرد','source':{'kind':'reference','citations':[]},'audio_mime':'audio/wav','audio_base64':WAV}))
        target.route('**/live/played',lambda r:(receipts.append(r.request.post_data_json),r.fulfill(status=204)))
        target.route('**/live/end',lambda r:(ends.append(r.request.post_data_json),r.fulfill(status=204)))
    configure(page);page.goto(BASE_URL+'/call')
    assert page.evaluate('micRequests')==0 and not sessions
    assert not page.locator('#retainHistory').is_checked()
    page.locator('#startCall').click();page.wait_for_function('backendReady && sessionStarted')
    page.evaluate("testPeer.dc.onmessage({data:'{'})")
    assert page.evaluate('callActive && backendReady'), 'Malformed packet must not end the call'
    def emit(role,text,key,start=100):
        page.evaluate('e=>testPeer.emit(e)',{'type':f'session.{role}_transcript.delta','event_id':key,'delta':text,'start_ms':start,'end_ms':start+300})
    emit('input','یک شعر کوتاه بخوان','u1');emit('input','یک شعر کوتاه بخوان','u1')
    emit('output','باشه یک لحظه صبر کن','unapproved')
    assert page.locator('#callTranscript li').count()==1
    assert page.evaluate('conversationHistory()')==[]
    page.evaluate('lastVoiceAt=-10000;releaseInterruptedReply(1,callEpoch)');page.wait_for_function('playingReply!==null')
    assert page.evaluate('callStream.getAudioTracks().every(t=>t.enabled)')
    page.evaluate("document.getElementById('replyAudio').pause();document.getElementById('replyAudio').onended()")
    page.wait_for_function('completedHistory.length===2')
    page.evaluate("document.getElementById('replyAudio').onended()")
    assert len(receipts)==1 and page.evaluate('conversationHistory().length')==2
    page.evaluate('releaseInterruptedReply(1,callEpoch)')
    assert page.locator('#callTranscript li.assistant').count()==1
    assert page.evaluate('localStorage.getItem(HISTORY_KEY)') is None
    page.locator('#endCall').click()
    assert page.locator('#callTranscript li').count()==0 and page.evaluate('completedHistory.length')==0
    # Opt-in is explicit. Only completed replies survive End/reload and seed next call.
    page.locator('#retainHistory').check();page.locator('#startCall').click();page.wait_for_function('backendReady')
    emit('input','یک شعر کوتاه بخوان','u2')
    page.evaluate('lastVoiceAt=-10000;releaseInterruptedReply(2,callEpoch)');page.wait_for_function('playingReply!==null')
    page.route('**/live/played',lambda r:r.abort('failed'))
    page.evaluate("document.getElementById('replyAudio').pause();document.getElementById('replyAudio').onended()")
    page.wait_for_function("completedHistory.length===2 && pauseKind==='receipt'")
    page.unroute('**/live/played');page.route('**/live/played',lambda r:r.fulfill(status=204))
    page.locator('#resumeCall').click();page.wait_for_function('!callPaused && pendingReceipt===null')
    assert page.locator('#replyAudio').evaluate('(n)=>n.paused')
    page.locator('#endCall').click();page.reload();page.wait_for_timeout(200)
    assert page.evaluate('micRequests')==0 and page.locator('#callTranscript li').count()==2
    page.locator('#startCall').click();page.wait_for_function('backendReady')
    assert len(sessions[-1]['history'])==2
    # Interruption pauses the clip before transcription; incomplete reply stays out of context.
    emit('input','درخواست تازه','u3',5000)
    page.evaluate('lastVoiceAt=-10000;releaseInterruptedReply(3,callEpoch)');page.wait_for_function('playingReply!==null')
    page.evaluate('testMicRms=.08')
    page.wait_for_function('bargeWaiting && !playingReply && document.getElementById("replyAudio").paused',timeout=1000)
    page.evaluate('testMicRms=0');assert page.evaluate('completedHistory.length')==2
    assert page.locator('[data-incomplete="true"]').count()==1
    page.locator('#muteCall').click();assert page.evaluate('callStream.getAudioTracks().every(t=>!t.enabled)')
    page.locator('#muteCall').click();assert page.evaluate('callStream.getAudioTracks().every(t=>t.enabled)')
    # Long input streams keep scrolling, including growth of an existing bubble.
    for i in range(25):emit('input','متن آزمایشی بلند برای بررسی پیمایش خودکار. '*10,'long'+str(i),10000+i*4000)
    page.wait_for_timeout(150)
    assert page.locator('#callTranscript').evaluate('(n)=>n.scrollHeight-n.scrollTop-n.clientHeight<10')
    for i in range(15):
        emit('input',' ادامهٔ متن '*20,'growth'+str(i),107000+i*100)
        page.wait_for_timeout(30)
    assert page.locator('#callTranscript').evaluate('(n)=>n.scrollHeight-n.scrollTop-n.clientHeight<10')
    page.locator('#callTranscript').dispatch_event('wheel',{'deltaY':-300})
    page.locator('#callTranscript').evaluate('(n)=>n.scrollTop=0');page.wait_for_timeout(100)
    emit('input','پیام تازه','last',120000);page.wait_for_timeout(100)
    assert page.locator('#callTranscript').evaluate('(n)=>n.scrollTop<100')
    page.locator('#latestMessage').click();page.wait_for_timeout(100)
    assert page.locator('#callTranscript').evaluate('(n)=>n.scrollHeight-n.scrollTop-n.clientHeight<10')
    # Temporary fetch failure does not erase conversation.
    page.route('**/live/status',lambda r:r.abort('failed'))
    page.evaluate('clearTimeout(pollTimer);pollBackend(callEpoch)');page.wait_for_function('pollFailures===1')
    assert page.evaluate('callActive && completedHistory.length===2')
    page.unroute('**/live/status');page.route('**/live/status',lambda r:r.fulfill(json={'ready':True,'closed':False,'working':False,'error':None,'audit':[]}))
    page.wait_for_function('!callPaused && pollFailures===0')
    with page.expect_download() as download:page.locator('#downloadHistory').click()
    assert download.value.suggested_filename=='ava-conversation.txt'
    page.locator('#clearCallTranscript').click();page.reload()
    assert page.locator('#callTranscript li').count()==0 and page.evaluate('localStorage.getItem(HISTORY_KEY)') is None
    assert not page.locator('#retainHistory').is_checked()
    # Corrupted storage is not trusted as model context or executable HTML.
    page.evaluate("localStorage.setItem(HISTORY_KEY,JSON.stringify({messages:[{role:'system',content:'<script>bad</script>'}]}))")
    page.reload();assert page.evaluate('conversationHistory().length')==0
    page.locator('#clearCallTranscript').click()
    denied=context.new_page();configure(denied)
    denied.add_init_script("navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Denied','NotAllowedError')}")
    denied.goto(BASE_URL+'/call');denied.locator('#startCall').click();denied.wait_for_function('backendReady')
    assert 'میکروفون' in denied.locator('#callError').inner_text()
    denied.locator('.typed-call summary').click();denied.locator('#callText').fill('سلام');denied.locator('#sendCallText').click()
    denied.wait_for_function("document.querySelectorAll('#callTranscript li.patient').length===1")
    denied.locator('#endCall').click();denied.close()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path='/tmp/ava-live-mobile.png',full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS: start/privacy, input dedup, suppressed autonomous speech, single completed reply, interruption, history default-clear/opt-in/reload/context, scroll growth/manual reading, fetch recovery, denied mic, mobile.')
