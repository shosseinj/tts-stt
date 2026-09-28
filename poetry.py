"""Small, source-checked public-domain quotation collection; never invent citations.
Source checked 2026-09-28. The text is a snapshot, not a live search result.
Only the listed couplets are supported; an unavailable named excerpt is declined.
"""
import re

SOURCE = 'https://ganjoor.net/ferdousi/shahname/aghaz/sh1'
TITLE = 'فردوسی، شاهنامه، آغاز کتاب — گنجور'
COUPLETS = (
    'به نام خداوندِ جان و خرد\nکز این برتر، اندیشه، بر نگذرد',
    'خداوندِ نام و خداوندِ جای\nخداوندِ روزی‌دِهِ رهنمای',
    'خداوندِ کیوان و گَردان‌سپهر\nفروزندهٔ ماه و ناهید و مِهر',
)
MEANINGS = (
    'این بیت با نام خدا آغاز می‌شود؛ او بخشندهٔ جان و خرد است و اندیشهٔ انسان به شناخت کامل او نمی‌رسد.',
    'این بیت خدا را بخشندهٔ روزی و راهنمای انسان معرفی می‌کند.',
    'این بیت از خدا به‌عنوان آفرینندهٔ آسمان و روشنایی ماه و خورشید یاد می‌کند.',
)
UNAVAILABLE = 'متن معتبر این بخش را در منبعِ در دسترس ندارم؛ نمی‌خواهم بیتی نادرست به فردوسی نسبت بدهم.'


def plain(text):
    return re.sub(r'[^\w\s]', '', re.sub(r'[\u064b-\u065f\u0670]', '', text.replace('\u200c', ' ').replace('ي', 'ی').replace('ك', 'ک'))).strip()


def poetry_reply(query, history):
    text = plain(query).replace('شاه نامه', 'شاهنامه')
    previous = next((item['content'] for item in reversed(history) if item['role'] == 'assistant'
                     and any(plain(verse) in plain(item['content']) for verse in COUPLETS)), '')
    referential = previous and any(word in text.split() for word in ('همان', 'همون', 'دوباره', 'بعدی', 'معنی', 'معنیش', 'معنایش', 'ادامه'))
    named = 'شاهنامه' in text or 'فردوسی' in text
    generic = bool(re.fullmatch(r'(?:لطفا |لطفاً )?(?:یک |یه )?(?:شعر|بیت)(?: کوتاه| زیبا)?(?: برایم| برام)? (?:بخوان|بخون|بگو|می خوانی|می خونی)(?: لطفا)?', text))
    if not previous and ('همان شعر' in text or 'همون شعر' in text) and any('شاهنامه' in item['content'] or 'فردوسی' in item['content'] for item in history):
        return UNAVAILABLE, 'ordinary', {'kind': 'general', 'citations': []}
    if not (named or generic or referential):
        return None
    index = next((i for i, verse in enumerate(COUPLETS) if plain(verse) in plain(previous)), 0)
    if any(word in text for word in ('معنی', 'معنیش', 'معنایش', 'توضیح')):
        if not previous:
            return 'کدام بیت را توضیح بدهم؟', 'ordinary', {'kind': 'general', 'citations': []}
        reply = MEANINGS[index]
    elif referential:
        if 'بعدی' in text or 'ادامه' in text:
            index += 1
        reply = COUPLETS[index] if index < len(COUPLETS) else UNAVAILABLE
    elif named:
        # Restricted vocabulary intentionally fails closed for unsupported named stories.
        words = set(text.split())
        allowed = set('لطفا لطفاً یک یه دو سه بیت شعر کوتاه زیبا از شاهنامه فردوسی برایم برام بخوان بخون بگو آغاز کتاب اول شروع بخوانید می خواهم میخوام برامون برای من بخونید'.split())
        if words - allowed:
            return UNAVAILABLE, 'ordinary', {'kind': 'general', 'citations': []}
        reply = COUPLETS[0]
    else:
        reply = COUPLETS[0]
    citations = [] if reply == UNAVAILABLE else [{'id': 'shahname-opening-' + str(index + 1), 'title': TITLE,
                                                  'text': COUPLETS[index], 'url': SOURCE}]
    return reply, 'ordinary', {'kind': 'reference' if citations else 'general', 'citations': citations}
