// GPT-Live WebRTC: API credentials and configuration authority stay on Flask.
const el = id => document.getElementById(id);
// Native Live speech pace is set in the server instructions.
let callActive = false, callMuted = false, callBusy = false, callPhase = 'idle', callEpoch = 0;
let callStream = null, peer = null, events = null, callToken = null, pollTimer = null, startupTimer = null;
let silentClock=null, disconnectTimer=null;
let remoteStream=null, remoteAnalyser=null, nativeTimer=null, lastRemoteVoiceAt=0, nativeFinishBusy=false;
let vadTimer=null, lastVoiceAt=0, bargeWaiting=false, releaseBusy=false, sessionBaseMs=0;
let callPaused=false, pauseKind=null, pollFailures=0, lastWarningId=0, followTranscript=true;
let sessionStarted = false, backendReady = false, transcriptGroups = [], transcriptSeen = new Set();
let receivedReplyVersions=new Set();
let completedHistory=[], playingReply=null, replyGeneration=0;
let documentId = null, documentBusy = false, documentEpoch = 0;
const profileFields = {preferred_name:'profileName', trusted_contacts:'profileContacts', orientation_facts:'profileFacts', routine:'profileRoutine'};
function setCallState(phase, text, hint='') { callPhase=phase; el('callState').textContent=text; el('callHint').textContent=hint; updateCallControls(); }
function callError(message='') { el('callError').textContent=message; el('callError').hidden=!message; }
function updateCallControls() {
    el('startCall').disabled=callActive || documentBusy;
    el('endCall').disabled=!callActive;
    el('muteCall').disabled=!callActive || !sessionStarted || !backendReady || !callStream;
    el('muteCall').textContent=callMuted ? 'وصل میکروفون' : 'قطع میکروفون';
    el('muteCall').setAttribute('aria-pressed',String(callMuted));
    el('callText').disabled=!callActive || !backendReady;
    el('sendCallText').disabled=!callActive || !backendReady || callBusy;
    for(const node of el('caregiverSettings').querySelectorAll('input,textarea,button')) node.disabled=callActive || documentBusy;
}
function sendEvent(event) { if(events?.readyState==='open') events.send(JSON.stringify(event)); }
function enableListening() {
    if (!callActive || !sessionStarted || !backendReady || callPaused) return;
    clearTimeout(startupTimer);
    callStream?.getAudioTracks().forEach(track=>track.enabled=!callMuted);
    setCallState(callMuted?'muted':'listening',callMuted?'میکروفون قطع است':'در حال گوش دادن','می‌توانید هنگام صحبت دستیار هم صحبت کنید.');
}
function transcriptEvent(event) {
    if(transcriptSeen.has(event.event_id)) return;
    transcriptSeen.add(event.event_id);
    const role=event.type==='session.input_transcript.delta'?'patient':'assistant';
    const fragment={text:event.delta,start:event.start_ms+sessionBaseMs,end:event.end_ms+sessionBaseMs};
    if(typeof fragment.text!=='string' || !Number.isFinite(fragment.start) || !Number.isFinite(fragment.end)) return;
    // Timing, not packet arrival order, determines independent speaker bubbles.
    let group=transcriptGroups.find(g=>!g.typed && g.role===role && fragment.start<=g.end+1500 && fragment.end>=g.start-1500);
    if(!group) {
        group={role,start:fragment.start,end:fragment.end,fragments:[],node:null};
        transcriptGroups.push(group);
        appendTurn(role,''); group.node=el('callTranscript').lastElementChild;
    }
    group.fragments.push(fragment); group.fragments.sort((a,b)=>a.start-b.start);
    group.start=Math.min(group.start,fragment.start); group.end=Math.max(group.end,fragment.end);
    group.node.querySelector('p').textContent=group.fragments.map(f=>f.text).join('');
    transcriptGroups.sort((a,b)=>a.start-b.start);
    const list=el('callTranscript');
    transcriptGroups.forEach((g,i)=>{if(list.children[i]!==g.node)list.insertBefore(g.node,list.children[i] || null);});
    saveHistory();followLatest();
    // Bound deduplication memory, not conversation duration or the visible transcript.
    if(transcriptSeen.size>2000) transcriptSeen.delete(transcriptSeen.values().next().value);
}
function receiveLiveMessage(raw,epoch){
    if(!callActive || epoch!==callEpoch)return;
    let event;
    try{event=JSON.parse(raw);}catch(_){
        callError('یک پیام تماس قابل خواندن نبود؛ تماس ادامه دارد.');return;
    }
    if(!event || typeof event.type!=='string')return;
    try{handleLiveEvent(event,epoch);}catch(_){
        // A DOM/runtime failure is not malformed provider JSON. Preserve the text.
        pauseForRecovery('نمایش صفحه با نسخهٔ برنامه هماهنگ نیست. صفحه را با Ctrl+Shift+R تازه کنید.','interface');
    }
}
function handleLiveEvent(event,epoch=callEpoch) {
    if(!callActive || epoch!==callEpoch) return;
    if(event.type==='session.started') { sessionStarted=true; enableListening(); }
    else if(event.type==='session.input_transcript.delta' || event.type==='session.output_transcript.delta') {
        if(event.type==='session.output_transcript.delta'){
            if(playingReply?.native_live && !bargeWaiting && !transcriptSeen.has(event.event_id)){
                transcriptSeen.add(event.event_id);setNativeTranscript(playingReply.spoken + event.delta);
            }
            return;
        }
        if(playingReply) interruptCall();
        transcriptEvent(event);
        setCallState('listening','در حال گوش دادن');
    } else if(event.type==='session.closed') { callError('تماس صوتی پایان یافت. برای ادامه تماس تازه‌ای شروع کنید.'); endCall(false); }
    else if(event.type==='error') pauseForRecovery('یکی از درخواست‌های تماس پذیرفته نشد. متن حفظ شده؛ برای تلاش دوباره ادامه تماس را بزنید.');
}
function pauseForRecovery(message,kind='command') {
    callPaused=true;pauseKind=kind;backendReady=false;
    callStream?.getAudioTracks().forEach(t=>t.enabled=false);
    el('replyAudio').pause();callError(message);
    el('resumeCall').textContent='ادامه تماس / تلاش دوباره';el('resumeCall').hidden=false;
    setCallState('paused','تماس مکث شده؛ متن محفوظ است');
}
async function pollBackend(epoch) {
    if(!callActive || epoch!==callEpoch || !callToken) return;
    try {
        const response=await fetch('/live/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken}),signal:AbortSignal.timeout(8000)});
        if(response.status===404) {if(epoch===callEpoch){callError('سرور این تماس را دیگر در حافظه ندارد؛ ممکن است دوباره اجرا شده باشد. متن محفوظ است.');endCall(false);}return;}
        const status=await apiJSON(response);
        if(!callActive || epoch!==callEpoch) return;
        pollFailures=0;
        if(callPaused && pauseKind==='network' && status.ready && !status.warning && peer?.connectionState==='connected'){
            callPaused=false;pauseKind=null;backendReady=true;callError();el('resumeCall').hidden=true;enableListening();
            if(playingReply)el('replyAudio').play().catch(()=>{el('resumeCall').hidden=false;});
        }
        if(playingReply?.native_live && status.speaking_version===playingReply.version && status.spoken_text?.length>playingReply.spoken.length)setNativeTranscript(status.spoken_text);
        if(status.pending_speech!==null && status.pending_speech!==undefined) releaseInterruptedReply(status.pending_speech,epoch);
        if(status.closed || status.error) {callError('ارتباط اصلی تماس پایان یافت. متن محفوظ است؛ برای ادامه تماس تازه‌ای شروع کنید.');endCall(false);return;}
        if(status.warning && status.warning_id!==lastWarningId) {
            lastWarningId=status.warning_id;
            pauseForRecovery(status.warning==='backend_unavailable' ? 'پاسخ راهنما آماده نشد؛ متن محفوظ است. برای تلاش دوباره ادامه تماس را بزنید.' : 'یک فرمان تماس پذیرفته نشد؛ متن محفوظ است. ادامه تماس را بزنید.');
        }
        if(!callPaused && !backendReady && status.ready) {backendReady=true;enableListening();}
        callBusy=status.working; updateCallControls();
        if(callBusy && !callPaused && !playingReply) setCallState('responding','در حال بررسی راهنما و پاسخ دادن');
        el('agentAudit').textContent=(status.audit || []).map(a=>
            'گفتار تشخیص‌داده‌شده: '+a.recognized_input+'\n'+
            'بخش‌های بازیابی‌شده: '+(a.passages.map(p=>p.title+' / '+p.id+': '+p.text).join('\n') || 'مورد مرتبطی پیدا نشد')+'\n'+
            'گفتار ثبت‌شدهٔ دستیار ('+a.source.kind+'): '+a.reply).join('\n\n────────\n\n');
    } catch(error) {
        if(epoch!==callEpoch || !callActive) return;
        pollFailures++;
        pauseForRecovery('ارتباط با سرور ناپایدار است؛ دوباره بررسی می‌شود. متن تماس پاک نشده است.','network');
        if(pollFailures>=5) {callError('سرور پس از چند تلاش در دسترس نبود. متن محفوظ است؛ اتصال را بررسی و تماس تازه‌ای شروع کنید.');endCall(false);return;}
    }
    pollTimer=setTimeout(()=>pollBackend(epoch),pollFailures ? 2000 : 800);
}
async function startCall() {
    if(callActive || documentBusy) return;
    callActive=true; callPaused=false;pollFailures=0;lastWarningId=0;followTranscript=true; callMuted=false; callBusy=false; sessionStarted=false;backendReady=false;callError();
    const history=conversationHistory();
    sessionBaseMs=Math.max(0,...transcriptGroups.map(g=>g.end))+1000;
    transcriptSeen.clear();receivedReplyVersions.clear();bargeWaiting=false;releaseBusy=false;el('replyAudio').muted=false;el('agentAudit').textContent='';
    const epoch=++callEpoch; setCallState('starting','در حال اتصال تماس زنده');
    try {
        if(!window.RTCPeerConnection) throw new Error('این مرورگر WebRTC ندارد. از مرورگر جدید استفاده کنید.');
        try {
            const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
            if(!callActive || epoch!==callEpoch) {stream.getTracks().forEach(t=>t.stop());return;}
            callStream=stream;stream.getAudioTracks().forEach(t=>{t.enabled=false;t.onended=()=>{if(callActive){callMuted=true;callError('میکروفون قطع شد؛ پیام بنویسید یا تماس تازه‌ای شروع کنید.');updateCallControls();}};});
        } catch(error) {
            if(!callActive || epoch!==callEpoch) return;
            callMuted=true;callError('میکروفون در دسترس نیست یا اجازه داده نشده است؛ پس از اتصال می‌توانید پیام بنویسید.');
        }
        const pc=new RTCPeerConnection(); peer=pc;
        pc.ontrack=event=>{
            if(epoch!==callEpoch)return;
            remoteStream=event.streams[0] || new MediaStream([event.track]);
            const audio=el('replyAudio');audio.srcObject=remoteStream;audio.muted=true;
            audio.play().catch(()=>{el('resumeCall').hidden=false;});
            remoteAnalyser=silentClock.context.createAnalyser();remoteAnalyser.fftSize=1024;
            silentClock.context.createMediaStreamSource(remoteStream).connect(remoteAnalyser);
        };
        pc.onconnectionstatechange=()=>{
            if(epoch!==callEpoch || !callActive) return;
            if(pc.connectionState==='connected'){clearTimeout(disconnectTimer);return;}
            if(pc.connectionState==='disconnected'){
                pauseForRecovery('ارتباط صوتی لحظه‌ای قطع شده است؛ فرصت اتصال دوباره داده می‌شود.','network');
                clearTimeout(disconnectTimer);disconnectTimer=setTimeout(()=>{if(callActive && epoch===callEpoch && pc.connectionState==='disconnected'){callError('ارتباط صوتی بازیابی نشد. متن محفوظ است.');endCall(false);}},15000);
            } else if(pc.connectionState==='failed'){callError('ارتباط صوتی از دست رفت. متن محفوظ است.');endCall(false);}
        };
        // A continuous near-silent clock keeps Live context flowing during mute or
        // typed-only use. Only the original microphone track carries patient audio.
        const context=new AudioContext(), destination=context.createMediaStreamDestination();
        const oscillator=context.createOscillator(), gain=context.createGain();
        oscillator.frequency.value=20;gain.gain.value=.0001;
        oscillator.connect(gain).connect(destination);oscillator.start();
        const microphone=callStream ? context.createMediaStreamSource(callStream) : null;
        microphone?.connect(destination);
        if(microphone){
            const analyser=context.createAnalyser();analyser.fftSize=1024;microphone.connect(analyser);
            const samples=new Float32Array(analyser.fftSize);let loudFrames=0;
            vadTimer=setInterval(()=>{
                if(!callActive || callMuted || callPaused || !backendReady) {loudFrames=0;return;}
                analyser.getFloatTimeDomainData(samples);
                const rms=Math.sqrt(samples.reduce((sum,x)=>sum+x*x,0)/samples.length);
                if(rms>.025){lastVoiceAt=performance.now();loudFrames++;}else loudFrames=0;
                if(loudFrames>=3 && playingReply && !bargeWaiting) interruptCall();
            },25);
        }
        silentClock={context,oscillator,stream:destination.stream,microphone};await context.resume();
        const remoteSamples=new Float32Array(1024);
        nativeTimer=setInterval(()=>{
            if(!remoteAnalyser || !playingReply?.native_live || callPaused || el('replyAudio').paused)return;
            remoteAnalyser.getFloatTimeDomainData(remoteSamples);
            if(Math.sqrt(remoteSamples.reduce((sum,x)=>sum+x*x,0)/remoteSamples.length)>.004){
                lastRemoteVoiceAt=performance.now();playingReply.heardAudio=true;
            }
            if(playingReply.heardAudio && performance.now()-lastRemoteVoiceAt>2000 && performance.now()-playingReply.lastCaptionAt>2000 && /[.!؟?…]$/.test(playingReply.spoken.trim()))finishNativeReply(epoch);
        },150);
        destination.stream.getTracks().forEach(t=>pc.addTrack(t,destination.stream));
        const dc=pc.createDataChannel('oai-events');events=dc;
        dc.onmessage=e=>receiveLiveMessage(e.data,epoch);
        dc.onclose=()=>{if(callActive && epoch===callEpoch){callError('کانال تماس بسته شد.');endCall(false);}};
        const offer=await pc.createOffer();await pc.setLocalDescription(offer);
        if(epoch!==callEpoch || !callActive) return;
        const result=await apiJSON(await fetch('/live/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            sdp:offer.sdp,history,profile:Object.fromEntries(Object.entries(profileFields).map(([k,id])=>[k,el(id).value.trim()])),document_id:documentId})}));
        if(!callActive || epoch!==callEpoch){closeServer(result.token);return;}
        callToken=result.token;
        await pc.setRemoteDescription({type:'answer',sdp:result.transport.sdp});
        startupTimer=setTimeout(()=>{if(callActive && epoch===callEpoch && (!sessionStarted || !backendReady)){callError('اتصال تماس آماده نشد. دسترسی مدل و ارتباط شبکه را بررسی کنید.');endCall(false);}},20000);
        pollBackend(epoch);
    } catch(error) {if(epoch===callEpoch){callError(error.message || 'اتصال تماس ناموفق بود.');endCall(false);}}
}
function toggleMute() {
    if(!callActive || !callStream) return;
    callMuted=!callMuted;
    callStream.getAudioTracks().forEach(t=>t.enabled=!callMuted);
    sendEvent({type:callMuted?'session.input_audio.mute':'session.input_audio.unmute',event_id:crypto.randomUUID()});
    setCallState(callMuted?'muted':'listening',callMuted?'میکروفون قطع است':'در حال گوش دادن');
}
async function resumeCall(){
    if(!callActive) return;
    const epoch=callEpoch;
    if(callPaused){
        if(playingReply){callPaused=false;pauseKind=null;backendReady=true;callError();enableListening();}
        else try{
            const response=await fetch('/live/retry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken})});
            if(!response.ok) await apiJSON(response);
            if(epoch!==callEpoch) return;
            callPaused=false;pauseKind=null;backendReady=true;callError();enableListening();
        }catch(error){if(epoch===callEpoch)callError(error.message);return;}
    }
    el('resumeCall').hidden=true;
    if(playingReply)el('replyAudio').play().catch(()=>{if(epoch===callEpoch){el('resumeCall').hidden=false;callError('برای پخش صدای تماس دوباره دکمه را بزنید.');}});
}
async function sendTypedCall() {
    const text=el('callText').value.trim();
    if(!text || !callActive || !backendReady || callBusy) return;
    if(playingReply) await interruptCall();
    const epoch=callEpoch;callBusy=true;updateCallControls();
    try {
        const response=await fetch('/live/text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken,text})});
        if(!response.ok) await apiJSON(response);
        if(epoch!==callEpoch) return;
        appendTurn('patient',text);
        const at=Math.max(0,...transcriptGroups.map(g=>g.end))+1;
        transcriptGroups.push({role:'patient',typed:true,start:at,end:at,fragments:[{text,start:at,end:at}],node:el('callTranscript').lastElementChild});
        saveHistory();el('callText').value='';
    }catch(error){if(epoch===callEpoch)callError(error.message);}
    finally{if(epoch===callEpoch){callBusy=false;updateCallControls();}}
}
function closeServer(token){if(token)fetch('/live/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),keepalive:true}).catch(()=>{});}
function endCall(clear=true) {

    callActive=false;callEpoch++;replyGeneration++;playingReply=null;callBusy=false;backendReady=false;sessionStarted=false;
    clearTimeout(pollTimer);clearTimeout(startupTimer);clearTimeout(disconnectTimer);clearInterval(vadTimer);clearInterval(nativeTimer);remoteStream=null;remoteAnalyser=null;
    callStream?.getTracks().forEach(t=>t.stop());callStream=null;
    if(silentClock){silentClock.oscillator.stop();silentClock.stream.getTracks().forEach(t=>t.stop());silentClock.context.close().catch(()=>{});silentClock=null;}
    el('replyAudio').pause();el('replyAudio').srcObject=null;el('resumeCall').hidden=true;
    const dc=events,pc=peer;events=null;peer=null;
    // Keep the transport briefly for session.closed while microphone/playback stop now.
    if(dc?.readyState==='open'){
        dc.onmessage=e=>{try{if(JSON.parse(e.data).type==='session.closed'){dc.close();pc?.close();}}catch(_){}};
        dc.send(JSON.stringify({type:'session.close'}));setTimeout(()=>{dc.close();pc?.close();},5000);
    }else pc?.close();
    closeServer(callToken);callToken=null;
    if(clear){
        // Keep visible chat available for saving/resuming; only Clear erases it.
        el('agentAudit').textContent='';el('callText').value='';Object.values(profileFields).forEach(id=>el(id).value='');removeDocument();callError();
    }
    if(clear && !el('retainHistory').checked) resetHistory();
    else saveHistory();
    setCallState('ended',transcriptGroups.length?'تماس پایان یافت؛ متن محفوظ است':'تماس پایان یافت؛ تاریخچه پاک شد');
}
function resetHistory(){
    completedHistory=[];transcriptGroups=[];transcriptSeen.clear();saveHistory();
    el('callTranscript').replaceChildren();el('emptyCallTranscript').hidden=false;
    el('agentAudit').textContent='';el('callText').value='';followTranscript=true;el('latestMessage').hidden=true;
}
function clearCallTranscript(){endCall(false);resetHistory();setCallState('ended','متن و زمینه تماس پاک شد','برای یک گفت‌وگوی تازه، شروع تماس را بزنید.');}

function appendTurn(role, text, source = null) {
    el('emptyCallTranscript').hidden = true;
    const item = document.createElement('li'); item.className = role; item.dataset.role = role;
    const label = document.createElement('strong'); label.textContent = role === 'patient' ? 'شما' : 'دستیار';
    const words = document.createElement('p'); words.textContent = text; item.append(label, words);
    if (source) {
        const kinds = { reference:'نقل‌قول منبع‌دار', document: 'بر اساس سند مراقب', profile: 'بر اساس اطلاعات مراقب', general: 'گفت‌وگوی عمومی؛ پاسخ مرتبطی از سند استفاده نشد', safety: 'راهنمایی احتیاطی؛ کمک از مراقب یا پزشک' };
        const note = document.createElement('small'); note.textContent = kinds[source.kind] || kinds.general; item.append(note);
        if (source.citations?.length) {
            const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'بخش‌های مرتبط سند'; details.append(summary);
            for (const citation of source.citations) {
                const title = document.createElement('strong'); title.textContent = citation.title + ' · ' + citation.id;
                const quote = document.createElement('blockquote'); quote.textContent = citation.text; details.append(title, quote);
                if(citation.url==='https://ganjoor.net/ferdousi/shahname/aghaz/sh1'){const link=document.createElement('a');link.href=citation.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='مشاهده منبع در گنجور';details.append(link);}
            }
            item.append(details);
        }
    }
    el('callTranscript').append(item);followLatest();
}
async function apiJSON(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        if (data.code === 'missing_api_key') throw new Error('کلید API روی سرور تنظیم نشده است. مراقب باید OPENAI_API_KEY را در محیط سرور تنظیم و برنامه را دوباره اجرا کند؛ برای خواندن فایل .env از ./run.sh استفاده کنید.');
        const limits = {
            insufficient_quota: 'OpenAI برای پروژه یا سازمان این کلید خطای سهمیه داده است. اعتبار و محدودیت‌های همان پروژه و سازمان را بررسی کنید؛ این خطا به‌تنهایی موجودی کل حساب را مشخص نمی‌کند.',
            credit_balance_exhausted: 'OpenAI موجودی پیش‌پرداخت سازمانِ این کلید را تمام‌شده گزارش کرده است. بررسی کنید اعتبار شما متعلق به همین سازمان باشد.',
            project_spend_limit_exceeded: 'سقف هزینه پروژه این کلید رسیده است؛ حتی با داشتن اعتبار، محدودیت پروژه باید بررسی شود.',
            organization_spend_limit_exceeded: 'سقف هزینه سازمان این کلید رسیده است؛ محدودیت هزینه سازمان را بررسی کنید.',
            organization_usage_limit_exceeded: 'سقف استفاده مجاز سازمان رسیده است؛ محدودیت استفاده سازمان را بررسی کنید.',
            rate_limit_exceeded: 'محدودیت موقت تعداد درخواست یا توکن است، نه لزوماً کمبود اعتبار. کمی صبر کنید و محدودیت مدل و پروژه را بررسی کنید.',
            slow_down: 'سرویس درخواست کرده سرعت درخواست‌ها کمتر شود. کمی صبر کنید و دوباره تلاش کنید.',
            unclassified_429: 'سرویس خطای 429 داده اما علت دقیق مشخص نیست؛ نمی‌توان نتیجه گرفت اعتبار کافی نیست.',
        };
        if (response.status === 429) throw new Error((limits[data.code] || limits.unclassified_429) + (limits[data.code] ? ' [' + data.code + ']' : ''));
        const messages = { 503: 'کلید سرور یا سرویس در دسترس نیست. از مراقب کمک بخواهید.', 404: 'سند منقضی یا حذف شده است. تماس را پایان دهید و سند را دوباره بارگذاری کنید.', 504: 'پاسخ سرویس طول کشید. دوباره تلاش کنید.' };
        throw new Error(messages[response.status] || data.error || 'ارتباط با سرویس ناموفق بود.');
    }
    return data;
}
async function uploadDocument() {
    if (callActive || documentBusy) return;
    const file = el('documentFile').files[0];
    if (!file || !el('documentReviewed').checked || !el('documentReviewer').value.trim() || !el('documentReviewDate').value) {
        el('documentStatus').textContent = 'سند، مشخصات بازبین، تاریخ و تأیید بازبینی لازم است.'; return;
    }
    if (file.size > 2000000) { el('documentStatus').textContent = 'حجم سند باید کمتر از ۲ مگابایت باشد.'; return; }
    documentBusy = true; const epoch = ++documentEpoch; updateCallControls(); el('documentStatus').textContent = 'در حال آماده‌سازی سند…';
    const body = new FormData(); body.append('document', file); body.append('reviewed', 'true'); body.append('reviewer', el('documentReviewer').value.trim()); body.append('reviewed_on', el('documentReviewDate').value);
    try {
        const data = await apiJSON(await fetch('/documents', { method: 'POST', body }));
        if (epoch !== documentEpoch) { deleteDocumentOnServer(data.document_id); return; }
        if (documentId) deleteDocumentOnServer(documentId); documentId = data.document_id;
        el('documentStatus').textContent = data.title + ' — آماده؛ بازبین اعلام‌شده: ' + data.reviewer;
        el('documentPreview').textContent = data.preview; el('documentPreview').hidden = false; el('removeDocument').hidden = false;
    } catch (error) { if (epoch === documentEpoch) el('documentStatus').textContent = error.message; }
    finally { if (epoch === documentEpoch) { documentBusy = false; updateCallControls(); } }
}
function deleteDocumentOnServer(id) {
    if (id) fetch('/documents/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ document_id: id }), keepalive: true }).catch(() => {});
}
function removeDocument() {
    documentEpoch++; documentBusy = false; deleteDocumentOnServer(documentId); documentId = null;
    el('documentFile').value = ''; el('documentReviewer').value = ''; el('documentReviewDate').value = ''; el('documentReviewed').checked = false;
    el('documentPreview').textContent = ''; el('documentPreview').hidden = true; el('removeDocument').hidden = true;
    el('documentStatus').textContent = 'سندی بارگذاری نشده است.'; updateCallControls();
}
window.addEventListener('pagehide',()=>endCall());
document.addEventListener('visibilitychange',()=>{
    if(document.hidden && callActive){
        callMuted=true;callStream?.getAudioTracks().forEach(t=>t.enabled=false);
        sendEvent({type:'session.input_audio.mute',event_id:crypto.randomUUID()});
        el('replyAudio').pause();el('resumeCall').textContent='پخش صدای تماس';el('resumeCall').hidden=false;
        setCallState('muted','میکروفون با خروج از صفحه قطع شد','تماس و متن حفظ شده‌اند. برای صحبت، میکروفون را وصل کنید.');
    }
});
function followLatest(force=false){
    if(force) followTranscript=true;
    if(!followTranscript) {el('latestMessage').hidden=false;return;}
    requestAnimationFrame(()=>{if(followTranscript){const list=el('callTranscript');list.scrollTop=list.scrollHeight;el('latestMessage').hidden=true;}});
}
// Layout changes and growing bubbles also fire scroll events. Only an intentional
// upward gesture should suspend following; otherwise long streaming text unpins itself.
const transcriptList=el('callTranscript');
transcriptList.addEventListener('wheel',event=>{if(event.deltaY<0){followTranscript=false;el('latestMessage').hidden=false;}},{passive:true});
let touchY=null;
transcriptList.addEventListener('touchstart',e=>{touchY=e.touches[0]?.clientY;},{passive:true});
transcriptList.addEventListener('touchmove',e=>{if(touchY!==null && e.touches[0].clientY>touchY+8){followTranscript=false;el('latestMessage').hidden=false;}},{passive:true});
transcriptList.addEventListener('keydown',e=>{if(['ArrowUp','PageUp','Home'].includes(e.key)){followTranscript=false;el('latestMessage').hidden=false;}});
transcriptList.addEventListener('scroll',()=>{
    if(transcriptList.scrollHeight-transcriptList.scrollTop-transcriptList.clientHeight<20){followTranscript=true;el('latestMessage').hidden=true;}
});
new ResizeObserver(()=>followLatest()).observe(transcriptList);

const HISTORY_KEY='ava.call.history.v2';
function saveHistory(){
    try{
        localStorage.removeItem('ava.call.history.v1');
        if(!el('retainHistory').checked || !completedHistory.length)localStorage.removeItem(HISTORY_KEY);
        else localStorage.setItem(HISTORY_KEY,JSON.stringify({messages:completedHistory.slice(-500)}));
        el('historyStatus').textContent=el('retainHistory').checked
            ? 'فقط نوبت‌های کامل در این مرورگر نگه داشته می‌شوند (تا ۵۰۰ پیام). ده تبادل اخیر در تماس بعد استفاده می‌شود.'
            : 'تاریخچه فقط در تماس جاری است؛ با پایان تماس یا بستن صفحه پاک می‌شود.';
    }catch(_){el('historyStatus').textContent='مرورگر اجازه ذخیره نداد. پیش از بستن صفحه، «ذخیره متن گفت‌وگو» را بزنید.';}
}
function restoreHistory(){
    try{
        const raw=localStorage.getItem(HISTORY_KEY);if(!raw){saveHistory();return;}
        const saved=JSON.parse(raw).messages;
        if(!Array.isArray(saved) || saved.length%2 || saved.length>500)throw new Error('Invalid history');
        if(saved.some((g,i)=>g.role!==(i%2?'assistant':'user') || typeof g.content!=='string' || !g.content.trim() || g.content.length>2000))throw new Error('Invalid history');
        completedHistory=saved;el('retainHistory').checked=true;
        saved.forEach((g,i)=>{
            const role=g.role==='user'?'patient':'assistant',at=i*3000,text=g.content;
            appendTurn(role,text);transcriptGroups.push({role,typed:true,start:at,end:at,fragments:[{text,start:at,end:at}],node:transcriptList.lastElementChild});
        });
        saveHistory();followLatest(true);
    }catch(_){el('historyStatus').textContent='بازیابی متن ذخیره‌شده ممکن نشد؛ می‌توانید آن را پاک کنید.';}
}
restoreHistory();
function conversationHistory(){return completedHistory.slice(-20);}
function downloadHistory(){
    const text=[...el('callTranscript').querySelectorAll('li')].map(n=>n.querySelector('strong').textContent+': '+n.querySelector('p').textContent).join('\n\n');
    if(!text)return;
    const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='ava-conversation.txt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function interruptCall(){
    if(!callActive || bargeWaiting || callPaused)return;
    const epoch=callEpoch;bargeWaiting=true;replyGeneration++;
    // Stop local clip immediately. A partial answer never enters completed history.
    el('replyAudio').muted=true;
    if(playingReply){playingReply.node.dataset.incomplete='true';const note=document.createElement('small');note.textContent='پاسخ قطع شد — در تاریخچه استفاده نمی‌شود';playingReply.node.append(note);}
    playingReply=null;
    setCallState('listening','حرف شما را می‌شنوم','پاسخ قبلی قطع شد؛ صحبت کنید.');
    try{
        const response=await fetch('/live/interrupt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken})});
        if(!response.ok)await apiJSON(response);
    }catch(error){if(epoch===callEpoch)pauseForRecovery('فرمان قطع پاسخ به سرور نرسید. برای ادامه تلاش دوباره را بزنید.');}
}
async function releaseInterruptedReply(version,epoch){
    if(receivedReplyVersions.has(version) || releaseBusy || callPaused || playingReply || performance.now()-lastVoiceAt<650)return;
    releaseBusy=true;const generation=replyGeneration;
    try{
        const response=await fetch('/live/play',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken,version})});
        if(response.status===409)return;
        const result=await apiJSON(response);
        if(epoch!==callEpoch || generation!==replyGeneration || !callActive)return;
        if(receivedReplyVersions.has(version))return;
        receivedReplyVersions.add(version);bargeWaiting=false;
        appendTurn('assistant','',result.source);
        const node=transcriptList.lastElementChild,at=Math.max(0,...transcriptGroups.map(g=>g.end))+1;
        const group={role:'assistant',typed:true,start:at,end:at,fragments:[{text:'',start:at,end:at}],node};
        transcriptGroups.push(group);
        playingReply={...result,node,group,spoken:'',lastCaptionAt:performance.now(),heardAudio:false};
        const audio=el('replyAudio');audio.srcObject=remoteStream;audio.muted=false;audio.playbackRate=1;
        setCallState('responding','در انتظار پاسخ صوتی زنده');
        await audio.play().catch(()=>{if(epoch===callEpoch){el('resumeCall').hidden=false;el('resumeCall').textContent='پخش صدای زنده';}});
    }catch(error){if(epoch===callEpoch)pauseForRecovery('ارتباط پاسخ زنده ناموفق بود؛ متن محفوظ است.');}
    finally{if(epoch===callEpoch)releaseBusy=false;}
}
function setNativeTranscript(text){
    if(!playingReply?.native_live)return;
    playingReply.spoken=text;playingReply.lastCaptionAt=performance.now();
    playingReply.node.querySelector('p').textContent=text;
    playingReply.group.fragments[0].text=text;
    setCallState('speaking','دستیار در حال صحبت است');followLatest();
}
async function finishNativeReply(epoch){
    if(nativeFinishBusy || !playingReply?.native_live)return;
    nativeFinishBusy=true;const finished=playingReply,generation=replyGeneration;
    try{
        const response=await fetch('/live/played',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken,version:finished.version})});
        if(response.status===409)return;
        if(!response.ok)throw new Error('Completion not recorded');
        if(epoch!==callEpoch || generation!==replyGeneration || playingReply!==finished)return;
        completedHistory.push({role:'user',content:finished.transcript.slice(0,2000)},{role:'assistant',content:finished.spoken.slice(0,2000)});
        completedHistory=completedHistory.slice(-500);playingReply=null;saveHistory();
        el('replyAudio').muted=true;enableListening();
    }catch(_){if(epoch===callEpoch)callError('ثبت زمینهٔ تماس موقتاً ناموفق بود؛ دوباره بررسی می‌شود.');}
    finally{nativeFinishBusy=false;}
}
