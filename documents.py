"""Local, temporary document retrieval. Review status is a caregiver attestation."""
from datetime import date
import io
import re
import secrets
import threading
import time
from pathlib import Path
from pypdf import PdfReader
from werkzeug.exceptions import BadRequest, NotFound, RequestEntityTooLarge, ServiceUnavailable

MAX_BYTES = 2_000_000
MAX_CHARS = 60_000
TTL_SECONDS = 7200
_documents = {}
_lock = threading.Lock()
STOP = set('از به با در را و یا که این آن یک برای است هست من تو ما شما چه چرا چطور چگونه آیا می ها های شده شود کنم کنم بگو درباره طبق راهنما راهنمای کار'.split())


def tokens(text):
    text = text.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')
    text = re.sub('[\u064b-\u065f\u0670]', '', text).lower()
    return {word for word in re.findall(r'[^\W\d_]+', text) if len(word) > 1 and word not in STOP}


def purge():
    now = time.monotonic()
    for key in list(_documents):
        if _documents[key]['expires'] <= now:
            del _documents[key]


def upload_document(upload, reviewed, reviewer, reviewed_on):
    if reviewed != 'true' or not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 100:
        raise BadRequest('Confirm expert review and provide the reviewer name/role.')
    try:
        review_date = date.fromisoformat(reviewed_on)
        if review_date > date.today():
            raise ValueError()
    except (TypeError, ValueError):
        raise BadRequest('Provide a valid review date, not in the future.') from None
    if upload is None or Path(upload.filename or '').suffix.lower() not in {'.txt', '.md', '.pdf'}:
        raise BadRequest('Upload UTF-8 TXT/Markdown or a text-based PDF.')
    raw = upload.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise RequestEntityTooLarge('Document limit is 2 MB.')
    try:
        if Path(upload.filename).suffix.lower() == '.pdf':
            pdf = PdfReader(io.BytesIO(raw), strict=True)
            if pdf.is_encrypted or len(pdf.pages) > 40:
                raise BadRequest('PDF must be unencrypted and at most 40 pages.')
            pages = []
            for page in pdf.pages:
                pages.append(page.extract_text() or '')
                if sum(map(len, pages)) > MAX_CHARS:
                    raise BadRequest('Document text limit is 60000 characters.')
            text = '\n\n'.join(pages)
        else:
            text = raw.decode('utf-8-sig')
    except BadRequest:
        raise
    except Exception:
        raise BadRequest('Could not extract document text. Try a UTF-8 TXT export.') from None
    if '\x00' in text or len(text.strip()) < 20 or len(text) > MAX_CHARS:
        raise BadRequest('Document must contain 20–60000 readable characters. Scanned PDFs need a text export.')
    # Paragraph-based passages; overlap long paragraphs to retain nearby context.
    chunks = []
    for paragraph in re.split(r'\n\s*\n', text):
        paragraph = paragraph.strip()
        if paragraph:
            for offset in range(0, len(paragraph), 650):
                chunk = paragraph[offset:offset + 850]
                chunks.append({'id': f'p{len(chunks) + 1}', 'text': chunk})
    title = Path(upload.filename).name[:160]
    token = secrets.token_urlsafe(32)
    with _lock:
        purge()
        if len(_documents) >= 16:
            raise ServiceUnavailable('Document memory is full. Remove an old document or try later.')
        _documents[token] = {'title': title, 'reviewer': reviewer.strip(), 'reviewed_on': reviewed_on,
                             'chunks': chunks, 'expires': time.monotonic() + TTL_SECONDS}
    expiry = threading.Timer(TTL_SECONDS, remove_document, args=(token,))
    expiry.daemon = True
    expiry.start()
    return {'document_id': token, 'title': title, 'passages': len(chunks), 'reviewer': reviewer.strip(),
            'reviewed_on': reviewed_on, 'expires_in': TTL_SECONDS, 'preview': text[:700]}


def remove_document(token):
    if not isinstance(token, str) or len(token) > 100:
        raise BadRequest('Invalid document ID.')
    with _lock:
        purge()
        _documents.pop(token, None)


def retrieve(token, query):
    if not token:
        return []
    if not isinstance(token, str) or len(token) > 100:
        raise BadRequest('Invalid document ID.')
    with _lock:
        purge()
        document = _documents.get(token)
        if document is None:
            raise NotFound('The uploaded document expired or was removed. Upload it again or remove it from the call.')
        # Copy only matches out of the locked memory store.
        terms = tokens(query)
        if not terms:
            return []
        scored = []
        for passage in document['chunks']:
            common = terms & tokens(passage['text'])
            coverage = len(common) / len(terms)
            if common and (coverage >= .5 or (len(common) >= 2 and coverage >= .25)):
                scored.append((coverage, len(common), passage))
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [{'id': passage['id'], 'text': passage['text'], 'title': document['title']}
                for _, _, passage in scored[:3]]


def retrieve_for_turn(token, query, history):
    """Resolve explicit short follow-ups against the most recent user turn only."""
    passages = retrieve(token, query)
    if passages or not history:
        return passages
    references = {'همان', 'همون', 'دوباره', 'دیگر', 'دیگه', 'آن', 'اون'}
    words = set(query.replace('\u200c', ' ').split())
    if words & references:
        previous = next((item['content'] for item in reversed(history) if item['role'] == 'user'), '')
        if previous:
            return retrieve(token, previous)
    return []
