"""Bounded, verbatim active-call memory; no inferred patient facts or disk storage."""
import re
from collections import OrderedDict

from documents import tokens

MAX_TURNS = 250
# Match cues, not names: keep the original words and their provenance intact.
NAME_CUE = re.compile(r'(?:(?:اسم(?:م| من)|نام(?:م| من))\s+(?!(?:چیست|چیه|چی|چه|یادت)(?:\s|[؟?]|$))\S+|من\s+.{1,60}?\s+(?:هستم|ام)(?:\s|[.،!؟]|$)|my name|call me)', re.I)


class CallMemory:
    def __init__(self):
        self.turns = OrderedDict()

    def remember(self, version, user, assistant=None):
        if version not in self.turns:
            self.turns[version] = {'user': user}
        if assistant is not None:
            self.turns[version]['assistant'] = assistant
        while len(self.turns) > MAX_TURNS:
            self.turns.popitem(last=False)

    def relevant(self, query):
        rows = list(self.turns.items())
        terms = tokens(query)
        # Recent turns preserve pronouns/topics. Older matches restore earlier facts.
        selected = {key for key, _ in rows[-4:]}
        ranked = sorted(((len(terms & tokens(row['user'] + ' ' + row.get('assistant', ''))), i, key)
                         for i, (key, row) in enumerate(rows[:-4])), reverse=True)
        selected.update(key for score, _, key in ranked[:4] if score)
        # Re-send latest name statements even when the question uses different words.
        names = [key for key, row in rows if NAME_CUE.search(row['user'].replace('\u200c', ' '))]
        selected.update(names[-3:])
        return [{'turn': key, **row} for key, row in rows if key in selected]

    def clear(self):
        self.turns.clear()


def context_chunks(text, byte_limit=400):
    """UTF-8 bytes conservatively bound tokens without a tokenizer/model download.

    Leave room for a short packet label under Live's 500-token append limit.
    Preserve every character and avoid splitting a UTF-8 codepoint.
    """
    chunk, size = [], 0
    for char in text:
        width = len(char.encode('utf-8'))
        if size + width > byte_limit:
            yield ''.join(chunk)
            chunk, size = [], 0
        chunk.append(char)
        size += width
    if chunk:
        yield ''.join(chunk)
