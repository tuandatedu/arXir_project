"""Recover names/title from an explicit styled bibliography field.

Do not require ASCII Firstname Lastname: names may have middle initials,
accents, particles, and surnames written before given names.
"""
from __future__ import annotations
import re
import unicodedata

PARTICLES={'de','del','der','van','von','da','dos','di','la','le','du','den','al','et'}
JOURNAL=re.compile(r'(?i)^(?:J\.|Phys\.|Ann\.|Proc\.|Rev\.|Math\.|Journal\b|Nature\b|Science\b|Helvetica\b|SIAM\b|Trans\.)')

def norm(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(text or '')).casefold() if c.isalnum())

def split_explicit_names(value):
    from src.m2_parsing.bibitem import _plain
    original=str(value).strip(' ,;:\n\"\'“”‘’`')
    original=re.sub(r',\s*(?:The|An)\s*$','',original)
    original=re.sub(r'(?<=\.),\s*A\s*$','',original)
    trailing_initial=bool(re.search(r'\b[A-Z]\.\s*$',original))
    value=_plain(original).strip(' ,;:\"\'“”‘’`')
    if trailing_initial and not value.endswith('.'):value+='.'
    if not value or len(value)>180 or re.search(r'[\d$\\]|https?://',value):return None
    if re.search(r'\b[^\W\d_]{2,}\.\s',value):return None
    names=[]
    for segment in re.split(r'\s*;\s*|\s+(?:and|&)\s+',value):
        parts=[part.strip() for part in segment.split(',') if part.strip()]
        i=0
        while i<len(parts):
            part=parts[i]
            words=re.findall(r'[^\W\d_]+',part,re.UNICODE)
            next_is_initials=i+1<len(parts) and bool(re.fullmatch(r'(?:[A-Z]\.?(?:-|\s)*)+',parts[i+1]))
            if (len(words)==1 or next_is_initials) and i+1<len(parts):
                part+=', '+parts[i+1];i+=1
            elif i+1<len(parts) and re.fullmatch(r'(?i)(?:Jr\.?|Sr\.?|II|III|IV)',parts[i+1]):
                part+=', '+parts[i+1];i+=1
            names.append(part);i+=1
    if not 1<=len(names)<=8:return None
    for name in names:
        words=re.findall(r'[^\W\d_]+',name,re.UNICODE)
        if not 2<=len(words)<=7 or any(not w[0].isupper() and w not in PARTICLES for w in words):return None
    return [name.strip(' ,') for name in names]

def parse_explicit_bibitem(raw):
    """Return an explicit author/style-field split, otherwise defer unchanged."""
    from src.m2_parsing.bibitem import _plain
    from src.m2_parsing.tex_spans import group,spans
    # Publisher-provided fields remain authoritative.
    if re.search(r'\\bibinfo\s*\{(?:author|title|journal)\}',raw):return None
    match=re.search(r'\\(?:emph|textit)\s*',raw)
    if match is None:return None
    found=group(raw,match.end())
    authors=split_explicit_names(raw[:match.start()])
    if not found or not authors:return None
    prefix=raw[:match.start()].strip(' ,;:\"\'“”‘’`')
    article=re.search(r',\s*(The|An|A)\s*$',prefix)
    fragments=([(article[1]+' ')] if article else [])+[found[0]];end=found[1]
    # A title can switch between textit/emph and inline math. Preserve the
    # entire contiguous title rather than stop at the first closing brace.
    while end<len(raw):
        next_pos=end
        while next_pos<len(raw) and raw[next_pos].isspace():next_pos+=1
        following=re.match(r'\\(?:emph|textit)\s*',raw[next_pos:])
        if following:
            next_group=group(raw,next_pos+following.end())
            if next_group is None:break
            fragments.extend([raw[end:next_pos],next_group[0]]);end=next_group[1]
        elif raw.startswith(('$',r'\(',r'\ensuremath'),next_pos):
            token=next(iter(spans(raw[next_pos:])),None)
            if token is None or token[0]!='math':break
            fragments.extend([raw[end:next_pos],token[1]]);end=next_pos+len(token[1])
        else:break
    field=_plain(''.join(fragments))
    if not field:return None
    tail=raw[end:].strip(' ,.;')
    venue_locator=_plain(tail).lstrip(' ,.;')
    is_journal=JOURNAL.match(field) and (not venue_locator or re.match(r'(?i)^(?:\d|\(\d{4}|(?:vol|pp?|no)\b)',venue_locator))
    if is_journal:
        # The source gives a journal rather than an article title; keep the
        # supplied names but do not fabricate a missing article title.
        return authors,None,raw[match.start():]
    return authors,field,tail
