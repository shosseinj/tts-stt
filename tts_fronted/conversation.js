// GPT-Live WebRTC: credentials and agent instructions stay on the Flask server.
const el = id => document.getElementById(id);
let callActive = false, callMuted = false, callBusy = false, callPhase = 'idle', callEpoch = 0;
let callStream = null, peer = null, events = null, callToken = null, pollTimer = null, startupTimer = null;
let speechStatusTimer=null, silentClock=null;
let sessionStarted = false, backendReady = false, transcriptGroups = [], transcriptSeen = new Set();
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
    if (!callActive || !sessionStarted || !backendReady) return;
    clearTimeout(startupTimer);
    callStream?.getAudioTracks().forEach(track=>track.enabled=!callMuted);
    setCallState(callMuted?'muted':'listening',callMuted?'میکروفون قطع است':'در حال گوش دادن','می‌توانید هنگام صحبت دستیار هم صحبت کنید.');
}
function transcriptEvent(event) {
    if(transcriptSeen.has(event.event_id)) return;
    transcriptSeen.add(event.event_id);
    const role=event.type==='session.input_transcript.delta'?'patient':'assistant';
    const fragment={text:event.delta,start:event.start_ms,end:event.end_ms};
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
    transcriptGroups.forEach(g=>el('callTranscript').append(g.node));
    if(transcriptSeen.size>2000) { callError('این تماس طولانی شده است. لطفاً پایان دهید و تماس تازه‌ای شروع کنید.'); endCall(false); }
}
function handleLiveEvent(event,epoch=callEpoch) {
    if(!callActive || epoch!==callEpoch) return;
    if(event.type==='session.started') { sessionStarted=true; enableListening(); }
    else if(event.type==='session.input_transcript.delta' || event.type==='session.output_transcript.delta') {
        transcriptEvent(event);
        if(event.type==='session.output_transcript.delta') {
            setCallState('speaking','دستیار در حال صحبت است','متن زیر گفتار واقعی دستیار است؛ می‌توانید صحبت او را قطع کنید.');
            clearTimeout(speechStatusTimer);speechStatusTimer=setTimeout(()=>{if(callActive && epoch===callEpoch && !callBusy)enableListening();},2500);
        }
        else setCallState('listening','در حال گوش دادن');
    } else if(event.type==='session.closed') { callError('تماس صوتی پایان یافت. برای ادامه تماس تازه‌ای شروع کنید.'); endCall(false); }
    else if(event.type==='error') { callError('خطای ارتباط زنده؛ تماس را پایان دهید و دوباره شروع کنید.'); endCall(false); }
}
async function pollBackend(epoch) {
    if(!callActive || epoch!==callEpoch || !callToken) return;
    try {
        const status=await apiJSON(await fetch('/live/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken})}));
        if(!callActive || epoch!==callEpoch) return;
        if(status.closed || status.error) throw new Error('ارتباط با راهنما یا دستیار سرور قطع شد. برای جلوگیری از پاسخ بدون راهنما، تماس متوقف شد.');
        if(!backendReady && status.ready) {backendReady=true;enableListening();}
        callBusy=status.working; updateCallControls();
        if(callBusy) setCallState('responding','در حال بررسی راهنما و پاسخ دادن','دستیار ابتدا سند مراقب و قواعد ایمنی را بررسی می‌کند.');
        el('agentAudit').textContent=(status.audit || []).map(a=>
            'گفتار تشخیص‌داده‌شده: '+a.recognized_input+'\n'+
            'بخش‌های بازیابی‌شده: '+(a.passages.map(p=>p.title+' / '+p.id+': '+p.text).join('\n') || 'مورد مرتبطی پیدا نشد')+'\n'+
            'پاسخ آماده‌شده در سرور ('+a.source.kind+'): '+a.reply).join('\n\n────────\n\n');
    } catch(error) { if(epoch===callEpoch && callActive) {callError(error.message);endCall(false);} return; }
    pollTimer=setTimeout(()=>pollBackend(epoch),800);
}
async function startCall() {
    if(callActive || documentBusy) return;
    callActive=true; callMuted=false; callBusy=false; sessionStarted=false;backendReady=false;callError();
    transcriptGroups=[];transcriptSeen.clear();el('callTranscript').replaceChildren();el('emptyCallTranscript').hidden=false;el('agentAudit').textContent='';
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
        pc.ontrack=e=>{
            if(epoch!==callEpoch) return;
            el('replyAudio').srcObject=e.streams[0] || new MediaStream([e.track]);
            el('replyAudio').play().catch(()=>{if(callActive && epoch===callEpoch){el('resumeCall').hidden=false;el('resumeCall').textContent='پخش صدای تماس';}});
        };
        pc.onconnectionstatechange=()=>{if(epoch===callEpoch && callActive && ['failed','disconnected'].includes(pc.connectionState)){callError('ارتباط صوتی قطع شد. دوباره تماس را شروع کنید.');endCall(false);}};
        if(callStream) callStream.getTracks().forEach(t=>pc.addTrack(t,callStream));
        else {
            // GPT-Live's timeline needs ongoing input media even for typed-only calls.
            // This locally generated near-silent clock contains no microphone audio.
            const context=new AudioContext(), destination=context.createMediaStreamDestination();
            const oscillator=context.createOscillator(), gain=context.createGain();
            oscillator.frequency.value=20;gain.gain.value=.0001;
            oscillator.connect(gain).connect(destination);oscillator.start();
            silentClock={context,oscillator,stream:destination.stream};await context.resume();
            destination.stream.getTracks().forEach(t=>pc.addTrack(t,destination.stream));
        }
        const dc=pc.createDataChannel('oai-events');events=dc;
        dc.onmessage=e=>{try{handleLiveEvent(JSON.parse(e.data),epoch);}catch(_){if(epoch===callEpoch){callError('پیام نامعتبر از سرویس تماس دریافت شد.');endCall(false);}}};
        dc.onclose=()=>{if(callActive && epoch===callEpoch){callError('کانال تماس بسته شد.');endCall(false);}};
        const offer=await pc.createOffer();await pc.setLocalDescription(offer);
        if(epoch!==callEpoch || !callActive) return;
        const result=await apiJSON(await fetch('/live/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            sdp:offer.sdp,profile:Object.fromEntries(Object.entries(profileFields).map(([k,id])=>[k,el(id).value.trim()])),document_id:documentId})}));
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
function resumeCall(){el('replyAudio').play().then(()=>el('resumeCall').hidden=true).catch(()=>callError('مرورگر اجازه پخش نمی‌دهد. تنظیمات صدا را بررسی کنید.'));}
async function sendTypedCall() {
    const text=el('callText').value.trim();
    if(!text || !callActive || !backendReady || callBusy) return;
    const epoch=callEpoch;callBusy=true;updateCallControls();
    try {
        const response=await fetch('/live/text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:callToken,text})});
        if(!response.ok) await apiJSON(response);
        if(epoch!==callEpoch) return;
        appendTurn('patient',text);
        const at=Math.max(0,...transcriptGroups.map(g=>g.end))+1;
        transcriptGroups.push({role:'patient',typed:true,start:at,end:at,fragments:[{text,start:at,end:at}],node:el('callTranscript').lastElementChild});
        el('callText').value='';
    }catch(error){if(epoch===callEpoch)callError(error.message);}
    finally{if(epoch===callEpoch){callBusy=false;updateCallControls();}}
}
function closeServer(token){if(token)fetch('/live/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token}),keepalive:true}).catch(()=>{});}
function endCall(clear=true) {
    callActive=false;callEpoch++;callBusy=false;backendReady=false;sessionStarted=false;
    clearTimeout(pollTimer);clearTimeout(startupTimer);clearTimeout(speechStatusTimer);
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
        transcriptGroups=[];transcriptSeen.clear();el('callTranscript').replaceChildren();el('emptyCallTranscript').hidden=false;
        el('agentAudit').textContent='';el('callText').value='';Object.values(profileFields).forEach(id=>el(id).value='');removeDocument();callError();
    }
    setCallState('ended','تماس پایان یافت','برای شروع گفت‌وگوی تازه، شروع تماس را بزنید.');
}
function clearCallTranscript(){endCall(false);transcriptGroups=[];transcriptSeen.clear();el('callTranscript').replaceChildren();el('emptyCallTranscript').hidden=false;el('agentAudit').textContent='';el('callText').value='';setCallState('ended','متن و زمینه تماس پاک شد','برای یک گفت‌وگوی تازه، شروع تماس را بزنید.');}
function appendTurn(role, text, source = null) {
    el('emptyCallTranscript').hidden = true;
    const item = document.createElement('li'); item.className = role; item.dataset.role = role;
    const label = document.createElement('strong'); label.textContent = role === 'patient' ? 'شما' : 'دستیار';
    const words = document.createElement('p'); words.textContent = text; item.append(label, words);
    if (source) {
        const kinds = { document: 'بر اساس سند مراقب', profile: 'بر اساس اطلاعات مراقب', general: 'گفت‌وگوی عمومی؛ پاسخ مرتبطی از سند استفاده نشد', safety: 'راهنمایی احتیاطی؛ کمک از مراقب یا پزشک' };
        const note = document.createElement('small'); note.textContent = kinds[source.kind] || kinds.general; item.append(note);
        if (source.citations?.length) {
            const details = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'بخش‌های مرتبط سند'; details.append(summary);
            for (const citation of source.citations) {
                const title = document.createElement('strong'); title.textContent = citation.title + ' · ' + citation.id;
                const quote = document.createElement('blockquote'); quote.textContent = citation.text; details.append(title, quote);
            }
            item.append(details);
        }
    }
    el('callTranscript').append(item); item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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
document.addEventListener('visibilitychange',()=>{if(document.hidden && callActive){endCall(false);callError('تماس با خروج از صفحه متوقف شد. برای ادامه دوباره شروع کنید.');}});
