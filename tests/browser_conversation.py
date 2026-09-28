"""No paid calls: mock WebRTC events/API, retain real browser microphone lifecycle."""
from playwright.sync_api import sync_playwright

FAKE_RTC = '''
window.micRequests=0;
const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia=(...args)=>{micRequests++;return original(...args);};
window.sentEvents=[];
window.RTCPeerConnection=class {
  constructor(){window.testPeer=this;this.connectionState='new';}
  addTrack(){} addTransceiver(){}
  createDataChannel(){this.dc={readyState:'open',send:e=>sentEvents.push(JSON.parse(e)),close(){this.readyState='closed';}};return this.dc;}
  async createOffer(){return {type:'offer',sdp:'test-offer'};}
  async setLocalDescription(){}
  async setRemoteDescription(){this.connectionState='connected';this.emit({type:'session.started'});}
  emit(event){this.dc.onmessage({data:JSON.stringify(event)});}
  close(){this.connectionState='closed';}
};
'''
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--use-fake-device-for-media-stream'])
    context=browser.new_context(permissions=['microphone'],viewport={'width':1440,'height':1000})
    context.add_init_script(FAKE_RTC)
    page=context.new_page();errors=[];sessions=[];ends=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def configure(target):
        def create(route):
            sessions.append(route.request.post_data_json)
            route.fulfill(status=201,json={'token':'capability','session':{'id':'live_fake'},'transport':{'type':'webrtc','sdp':'answer'}})
        target.route('**/live/session',create)
        target.route('**/live/status',lambda r:r.fulfill(json={'ready':True,'closed':False,'working':False,'error':None,'audit':[]}))
        target.route('**/live/text',lambda r:r.fulfill(status=204))
        target.route('**/live/end',lambda r:(ends.append(r.request.post_data_json),r.fulfill(status=204)))
    configure(page)
    page.goto('http://127.0.0.1:5000/call');page.wait_for_timeout(100)
    assert page.evaluate('micRequests')==0 and not sessions
    page.locator('#startCall').click();page.wait_for_function('backendReady && sessionStarted')
    assert page.evaluate('micRequests')==1
    assert page.evaluate('callStream.getAudioTracks().every(t=>t.enabled)')
    assert set(sessions[0])=={'sdp','profile','document_id'}
    events=[
      {'type':'session.input_transcript.delta','event_id':'u1','delta':'سلام','start_ms':100,'end_ms':500},
      {'type':'session.output_transcript.delta','event_id':'a1','delta':'بله','start_ms':300,'end_ms':600},
      {'type':'session.input_transcript.delta','event_id':'u2','delta':' دوست دارم صحبت کنیم','start_ms':500,'end_ms':1000},
      {'type':'session.input_transcript.delta','event_id':'u2','delta':' دوست دارم صحبت کنیم','start_ms':500,'end_ms':1000},
    ]
    for event in events:page.evaluate('e=>testPeer.emit(e)',event)
    assert page.locator('#callTranscript li').count()==2
    assert page.locator('#callTranscript li.patient p').inner_text()=='سلام دوست دارم صحبت کنیم'
    assert page.locator('#callTranscript li').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.role)')==['patient','assistant']
    # Full duplex: speech output must not disable the microphone.
    assert page.evaluate('callStream.getAudioTracks().every(t=>t.enabled)')
    page.locator('#muteCall').click();assert page.evaluate('callStream.getAudioTracks().every(t=>!t.enabled)')
    assert page.evaluate('sentEvents.at(-1).type')=='session.input_audio.mute'
    page.locator('#muteCall').click();assert page.evaluate('sentEvents.at(-1).type')=='session.input_audio.unmute'
    page.locator('#clearCallTranscript').click();page.wait_for_timeout(100)
    assert not page.evaluate('callActive') and page.locator('#callTranscript li').count()==0 and ends
    page.locator('#startCall').click();page.wait_for_function('backendReady')
    page.locator('#endCall').click();assert page.evaluate('callStream===null && callToken===null')
    page.evaluate("handleLiveEvent({type:'session.input_transcript.delta',event_id:'late',delta:'late',start_ms:0,end_ms:10})")
    assert page.locator('#callTranscript li').count()==0
    # Microphone denied: receive-only WebRTC and typed backend input remain available.
    denied=context.new_page();configure(denied)
    denied.add_init_script("navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Denied','NotAllowedError')}")
    denied.goto('http://127.0.0.1:5000/call');denied.locator('#startCall').click();denied.wait_for_function('backendReady')
    assert 'میکروفون' in denied.locator('#callError').inner_text()
    denied.locator('.typed-call summary').click();denied.locator('#callText').fill('سلام');denied.locator('#sendCallText').click()
    denied.wait_for_function("document.querySelectorAll('#callTranscript li.patient').length===1")
    denied.locator('#endCall').click();denied.close()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path='/tmp/ava-live-mobile.png',full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS: no capture before Start, WebRTC permissions, full-duplex transcript grouping/dedup/order, mute/unmute, clear closes remote context, End/late events, denied-mic typed fallback, mobile; no paid API calls.')
