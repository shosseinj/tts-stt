const $ = id => document.getElementById(id);
const fa = value => Number(value).toLocaleString('fa-IR');
let recorder = null, microphone = null, recording = null, recordingUrl = null;
let recordingTimer = null, clockTimer = null, requestingMicrophone = false, transcribing = false;
let selectedFile = null, uploadUrl = null, speechUrl = null, ttsBusy = false;
let audioContext = null, meterFrame = null, recordingStarted = 0, toastTimer = null;
let source = 'record', pageLeaving = false;

// All API credentials are read from the server environment, never the browser.
function apiHeaders(extra = {}) { return extra; }
function toast(message) {
    $('toast').textContent = message; $('toast').hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 3500);
}
function showError(id, message = '') { $(id).textContent = message; $(id).hidden = !message; }
function setWorkspace(mode) {
    if (requestingMicrophone || recorder) { toast('ابتدا ضبط صدا را متوقف کنید.'); return; }
    const headings = {
        stt: ['گفتار به متن', 'هر صدایی، یک نوشته.', 'صحبت کنید یا فایل صوتی بیاورید؛ متن فارسی‌تان را اینجا تحویل بگیرید.'],
        tts: ['متن به گفتار', 'هر نوشته‌ای، یک صدا.', 'متن فارسی بنویسید و با یک صدای طبیعی، به آن جان بدهید.'],
    };
    for (const item of Object.keys(headings)) {
        $(item + 'Workspace').hidden = item !== mode;
        $('nav-' + item).classList.toggle('active', item === mode);
        if (item === mode) $('nav-' + item).setAttribute('aria-current', 'page');
        else $('nav-' + item).removeAttribute('aria-current');
    }
    [$('breadcrumbTitle').textContent, $('pageTitle').textContent, $('pageSubtitle').textContent] = headings[mode];
    $('audioPlayer').pause(); $('recordingPreview').pause(); $('uploadPreview').pause();
}
function setSource(next) {
    if (requestingMicrophone || recorder || transcribing) {
        toast('ابتدا ضبط یا پردازش فعلی را تمام کنید.'); return;
    }
    source = next;
    for (const item of ['record', 'upload']) {
        $(item + 'Panel').hidden = item !== next;
        $(item + 'Tab').classList.toggle('selected', item === next);
        $(item + 'Tab').setAttribute('aria-selected', String(item === next));
    }
    $('recordingTranscribeButton').hidden = next !== 'record';
    $('uploadTranscribeButton').hidden = next !== 'upload';
    showError('sttError');
}
for (const id of ['recordTab', 'uploadTab']) $(id).addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const next = event.key === 'Home' ? 'record' : event.key === 'End' ? 'upload' : source === 'record' ? 'upload' : 'record';
        setSource(next); $(source + 'Tab').focus();
    }
});
function updateRecordingButtons() {
    const busy = Boolean(requestingMicrophone || recorder);
    $('recordButton').disabled = busy || transcribing;
    $('stopRecordButton').disabled = !recorder || recorder.state !== 'recording';
    $('stopRecordButton').hidden = !recorder;
    $('recordingTranscribeButton').disabled = !recording || busy || transcribing;
    $('uploadTranscribeButton').disabled = !selectedFile || busy || transcribing;
    $('recordTab').disabled = busy || transcribing;
    $('uploadTab').disabled = busy || transcribing;
    $('audioInput').disabled = transcribing;
}
const bars = Array.from({ length: 39 }, (_, i) => {
    const bar = document.createElement('span');
    bar.style.height = (4 + Math.sin(i * 1.7) ** 2 * 13) + 'px';
    $('waveform').append(bar); return bar;
});
function startMeter(stream) {
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioContext.createAnalyser(); analyser.fftSize = 128;
        audioContext.createMediaStreamSource(stream).connect(analyser);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const draw = () => {
            analyser.getByteFrequencyData(data);
            bars.forEach((bar, i) => bar.style.height = Math.max(4, data[i + 2] / 8) + 'px');
            meterFrame = requestAnimationFrame(draw);
        };
        draw();
    } catch (_) { /* The level display is optional; recording can still work. */ }
}
function releaseMicrophone() {
    clearTimeout(recordingTimer); clearInterval(clockTimer); cancelAnimationFrame(meterFrame);
    if (microphone) microphone.getTracks().forEach(track => track.stop());
    microphone = null;
    if (audioContext) { audioContext.close().catch(() => {}); audioContext = null; }
    $('recordStage').classList.remove('recording');
}
async function startRecording() {
    if (requestingMicrophone || transcribing || recorder) return;
    showError('sttError');
    const status = $('recordingStatus');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        showError('sttError', 'ضبط در این مرورگر در دسترس نیست. از localhost یا HTTPS استفاده کنید یا فایل صوتی آپلود کنید.'); return;
    }
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) { showError('sttError', 'فرمت ضبط مرورگر پشتیبانی نمی‌شود. فایل صوتی آپلود کنید.'); return; }
    requestingMicrophone = true; updateRecordingButtons();
    status.textContent = 'در انتظار اجازه دسترسی به میکروفون…';
    try {
        microphone = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (pageLeaving) { releaseMicrophone(); return; }
        recorder = new MediaRecorder(microphone, { mimeType });
        const chunks = []; let size = 0, failed = false;
        recorder.ondataavailable = event => {
            if (event.data.size) {
                chunks.push(event.data); size += event.data.size;
                if (size > 24000000) { failed = true; showError('sttError', 'حجم ضبط بیش از ۲۴ مگابایت است. ضبط کوتاه‌تری انجام دهید.'); stopRecording(); }
            }
        };
        recorder.onerror = () => { failed = true; showError('sttError', 'ضبط ناموفق بود. میکروفون را بررسی کنید.'); stopRecording(); };
        recorder.onstop = () => {
            releaseMicrophone();
            if (!failed && size && !pageLeaving) {
                const extension = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm';
                recording = new File(chunks, 'recording.' + extension, { type: mimeType });
                recordingUrl = URL.createObjectURL(recording);
                $('recordingPreview').src = recordingUrl; $('recordingPreview').hidden = false;
                $('stageCaption').textContent = 'صدای شما آماده است';
                status.textContent = 'گوش دهید و برای ارسال، تبدیل صدا به متن را بزنید.';
            } else if (!failed) status.textContent = 'صدایی ضبط نشد. دوباره تلاش کنید.';
            recorder = null; updateRecordingButtons();
        };
        recorder.start(1000);
        recording = null; $('recordingPreview').pause(); $('recordingPreview').removeAttribute('src'); $('recordingPreview').hidden = true;
        if (recordingUrl) URL.revokeObjectURL(recordingUrl); recordingUrl = null;
        $('recordStage').classList.add('recording'); $('stageCaption').textContent = 'صدای شما را می‌شنویم';
        status.textContent = 'در حال ضبط… راحت و طبیعی صحبت کنید.';
        recordingStarted = Date.now();
        const tick = () => {
            const secs = Math.min(120, Math.floor((Date.now() - recordingStarted) / 1000));
            $('recordTime').innerHTML = String(Math.floor(secs / 60)).padStart(2, '0') + ':' + String(secs % 60).padStart(2, '0') + ' <span>/ 02:00</span>';
        };
        tick(); clockTimer = setInterval(tick, 250); recordingTimer = setTimeout(stopRecording, 120000);
        startMeter(microphone);
    } catch (error) {
        releaseMicrophone(); recorder = null;
        status.textContent = error.name === 'NotAllowedError' ? 'دسترسی به میکروفون رد شد. از تنظیمات مرورگر اجازه دهید.' : 'میکروفون در دسترس نیست. اتصال و تنظیمات آن را بررسی کنید.';
    } finally { requestingMicrophone = false; updateRecordingButtons(); }
}
function stopRecording() {
    if (recorder && recorder.state === 'recording') recorder.stop();
    releaseMicrophone(); $('stopRecordButton').disabled = true;
}
function selectFile(file) {
    if (!file || transcribing) return;
    const supported = /\.(wav|mp3|mp4|m4a|mpeg|mpga|webm|ogg|flac)$/i.test(file.name);
    if (!supported || !file.size || file.size > 24000000) {
        clearFile(); showError('sttError', 'یک فایل صوتی معتبر با حجم حداکثر ۲۴ مگابایت انتخاب کنید.'); return;
    }
    showError('sttError'); selectedFile = file;
    if (uploadUrl) URL.revokeObjectURL(uploadUrl);
    uploadUrl = URL.createObjectURL(file); $('uploadPreview').src = uploadUrl; $('uploadPreview').hidden = false;
    $('fileName').textContent = file.name; $('fileSize').textContent = fa((file.size / 1024 / 1024).toFixed(2)) + ' مگابایت';
    $('selectedFile').hidden = false; updateRecordingButtons();
}
function clearFile() {
    if (transcribing) return;
    selectedFile = null; $('audioInput').value = ''; $('selectedFile').hidden = true;
    $('uploadPreview').pause(); $('uploadPreview').removeAttribute('src'); $('uploadPreview').hidden = true;
    if (uploadUrl) URL.revokeObjectURL(uploadUrl); uploadUrl = null; updateRecordingButtons();
}
for (const type of ['dragover', 'dragenter']) $('dropZone').addEventListener(type, event => { event.preventDefault(); $('dropZone').classList.add('dragging'); });
for (const type of ['dragleave', 'drop']) $('dropZone').addEventListener(type, event => { event.preventDefault(); $('dropZone').classList.remove('dragging'); });
$('dropZone').addEventListener('drop', event => selectFile(event.dataTransfer.files[0]));
function transcribeAudio() { if (selectedFile) return submitAudio(selectedFile); }
function transcribeRecording() { if (recording) return submitAudio(recording); }
async function readResponse(response) {
    let data; try { data = await response.json(); } catch (_) { throw new Error('پاسخ سرور قابل خواندن نیست. دوباره تلاش کنید.'); }
    if (!response.ok) {
        const messages = {
            400: 'ورودی پذیرفته نشد. فایل صوتی، متن یا واژه‌های راهنما را بررسی کنید.',
            413: 'فایل بیش از حد بزرگ است. حداکثر حجم مجاز ۲۴ مگابایت است.',
            429: 'سهمیه یا محدودیت درخواست OpenAI پر شده است. اعتبار حساب را بررسی کنید.',
            503: 'مراقب باید OPENAI_API_KEY را روی سرور تنظیم و برنامه را دوباره راه‌اندازی کند.',
            504: 'پاسخ سرویس طول کشید. کمی بعد دوباره تلاش کنید.'
        };
        if (response.status === 502 && /authentication|access/i.test(data.error || '')) throw new Error('کلید API یا دسترسی حساب به مدل معتبر نیست. تنظیمات را بررسی کنید.');
        throw new Error(messages[response.status] || data.error || 'خطایی رخ داد. دوباره تلاش کنید.');
    }
    return data;
}
async function submitAudio(file) {
    if (transcribing) return;
    transcribing = true; updateRecordingButtons(); showError('sttError');
    $('sttLoadingMessage').hidden = false; $('transcriptBadge').textContent = 'در حال تبدیل…';
    try {
        const formData = new FormData(); formData.append('audio', file);
        formData.append('context', $('transcriptionContext').value.trim());
        const response = await fetch('/stt', { method: 'POST', headers: apiHeaders(), body: formData });
        const data = await readResponse(response);
        $('transcriptionResult').value = data.transcription || '';
        $('transcriptEmpty').hidden = true; $('transcriptEditor').hidden = false;
        $('transcriptBadge').textContent = data.transcription ? 'تبدیل شد' : 'گفتاری پیدا نشد';
        updateTranscriptActions();
        if (window.innerWidth < 621) $('transcriptEditor').scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (error) { showError('sttError', error.message); $('transcriptBadge').textContent = 'دوباره تلاش کنید'; }
    finally { $('sttLoadingMessage').hidden = true; transcribing = false; updateRecordingButtons(); }
}
function updateTranscriptActions() {
    const text = $('transcriptionResult').value.trim();
    ['copyTranscript', 'downloadTranscript', 'readTranscript', 'clearTranscript'].forEach(id => $(id).disabled = !text);
    $('wordCount').textContent = fa(text ? text.split(/\s+/).length : 0) + ' کلمه';
}
function clearTranscript() {
    $('transcriptionResult').value = ''; updateTranscriptActions();
    $('transcriptEmpty').hidden = false; $('transcriptEditor').hidden = true; $('transcriptBadge').textContent = 'آماده نوشتن';
}
async function copyTranscript() {
    try { await navigator.clipboard.writeText($('transcriptionResult').value); toast('متن کپی شد.'); }
    catch (_) { $('transcriptionResult').focus(); $('transcriptionResult').select(); toast('متن انتخاب شد؛ برای کپی Ctrl+C را بزنید.'); }
}
function downloadTranscript() {
    const url = URL.createObjectURL(new Blob(['\uFEFF', $('transcriptionResult').value], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = 'ava-transcript.txt'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}
function useTranscript() {
    const text = $('transcriptionResult').value;
    if (text.length > 4096) { toast('برای ساخت صدا، متن را به کمتر از ۴۰۹۶ نویسه کوتاه کنید.'); return; }
    $('textInput').value = text; updateTextCount(); setWorkspace('tts'); $('textInput').focus();
}
function insertSample() { $('textInput').value = 'سلام! به آوا خوش آمدید. اینجا هر صدایی به یک نوشته تبدیل می‌شود و هر نوشته‌ای، صدای خودش را پیدا می‌کند.'; updateTextCount(); }
function updateTextCount() { $('textCount').textContent = fa($('textInput').value.length) + ' / ۴۰۹۶ نویسه'; }
async function convertTextToSpeech() {
    if (ttsBusy) return;
    const text = $('textInput').value.trim(); showError('ttsError');
    if (!text) { showError('ttsError', 'اول متنی بنویسید یا از متن نمونه استفاده کنید.'); $('textInput').focus(); return; }
    ttsBusy = true; $('ttsButton').disabled = true; $('loadingMessage').hidden = false;
    try {
        const response = await fetch('/tts', { method: 'POST', headers: apiHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ text }) });
        if (!response.ok) await readResponse(response);
        const blob = await response.blob();
        if (speechUrl) URL.revokeObjectURL(speechUrl); speechUrl = URL.createObjectURL(blob);
        $('audioPlayer').src = speechUrl; $('audioPlayer').hidden = false;
        $('audioPlayer').playbackRate = Number($('playbackRate').value);
        $('downloadAudio').href = speechUrl; $('audioActions').hidden = false;
        $('audioTitle').textContent = 'صدای شما آماده شنیدن است.'; $('audioDescription').textContent = 'گوش دهید، سرعت پخش را تنظیم کنید یا فایل را بگیرید.';
    } catch (error) { showError('ttsError', error.message); }
    finally { ttsBusy = false; $('ttsButton').disabled = false; $('loadingMessage').hidden = true; }
}
window.addEventListener('pagehide', () => {
    pageLeaving = true; stopRecording();
    for (const url of [recordingUrl, uploadUrl, speechUrl]) if (url) URL.revokeObjectURL(url);
});
window.addEventListener('pageshow', () => { pageLeaving = false; });
