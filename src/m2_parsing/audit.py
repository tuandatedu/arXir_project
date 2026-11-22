"""Read exported rows independently; warnings do not certify semantic correctness."""
from __future__ import annotations
import collections
import csv
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
from src.m2_parsing.tex_spans import spans

CITE = re.compile(r'\\(?:[A-Za-z]*cite[A-Za-z]*|nocite)\*?(?:\s*\[[^\]]*\])*\s*\{([^{}]+)\}', re.I)

def row_citations(text):
    if '\\' not in text: return set()
    if r'\verb' in text or re.search(r'\\begin\s*\{(?:verbatim|Verbatim|lstlisting|minted)',text):
        text = ''.join(raw for kind,raw,_,_ in spans(text) if kind!='literal')
    return {key.strip() for m in CITE.finditer(text) for key in m[1].split(',')
            if key.strip() and key.strip()!='*' and not re.search(r'[#\\{}]',key)}

def audit_zip(path: Path, dest: Path, prefix: str):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    counts=collections.Counter();keys=collections.defaultdict(set);missing=set();blanks=collections.Counter()
    with (dest/f'{prefix}_bibtex_review.csv').open('w',newline='',encoding='utf-8-sig') as out:
        writer=csv.writer(out);writer.writerow(['arxiv_id','citation_key','reason','authors','title'])
        with ZipFile(path) as zipped:
            with zipped.open('bibtex.jsonl') as source:
                for line in source:
                    row=json.loads(line);counts['bib_rows']+=1;keys[row['arxiv_id']].add(row['citation_key'])
                    title=row.get('title') or '';authors=row.get('authors') or []
                    for reason,condition in [('missing_title',not title.strip()),('missing_authors',not authors),
                        ('long_author_string',any(len(a)>160 for a in authors)),
                        ('title_leaks_into_authors',bool(title) and len(title)>=25 and any(title[:25].casefold() in a.casefold() for a in authors))]:
                        if condition:
                            counts[reason]+=1;writer.writerow([row['arxiv_id'],row['citation_key'],reason,' | '.join(authors),title])
            with zipped.open('elements.jsonl') as source:
                for line in source:
                    row=json.loads(line);counts['elements_scanned']+=1;text=row['content']
                    if not text.strip():blanks[row['kind']]+=1
                    missing.update((row['arxiv_id'],key) for key in row_citations(text) if key not in keys[row['arxiv_id']])
    with (dest/f'{prefix}_unresolved_citation_keys.csv').open('w',newline='',encoding='utf-8-sig') as out:
        writer=csv.writer(out);writer.writerow(['arxiv_id','citation_key']);writer.writerows(sorted(missing))
    result={**dict(counts),'blank_content_by_kind':dict(blanks),
            'unresolved_unique_citation_keys':len(missing),'unresolved_publications':len({p for p,k in missing}),
            'note':'REVIEW is not a proven parser error. Blank roots/containers and nocite {*} are not counted as content failures.'}
    (dest/f'{prefix}_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(prefix,result,flush=True)
    return result

def compare_zips(previous: Path, current: Path, dest: Path):
    """List unchanged/changed publications after verification, never infer safety from old PASS."""
    def fingerprints(path):
        result=collections.defaultdict(dict)
        with ZipFile(path) as zipped:
            metrics=json.loads(zipped.read('metrics_m2.json'))
            for item in metrics['coverage']:result[item['arxiv_id']]={}
            for table in ('elements','hierarchy','bibtex'):
                digests={}
                with zipped.open(table+'.jsonl') as source:
                    for line in source:
                        row=json.loads(line);pid=row['arxiv_id']
                        digest=digests.setdefault(pid,hashlib.sha256())
                        digest.update(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
                        digest.update(b'\n')
                for pid,digest in digests.items():result[pid][table]=digest.hexdigest()
        return result
    before,after=fingerprints(previous),fingerprints(current)
    summary=collections.Counter()
    with Path(dest).open('w',newline='',encoding='utf-8-sig') as out:
        writer=csv.writer(out);writer.writerow(['arxiv_id','comparison','changed_tables'])
        for pid in sorted(before.keys()|after.keys()):
            changed=[table for table in ('elements','hierarchy','bibtex') if before.get(pid,{}).get(table)!=after.get(pid,{}).get(table)]
            status='UNCHANGED_UNDER_REV13' if not changed and pid in before and pid in after else 'CHANGED'
            summary[status]+=1;writer.writerow([pid,status,','.join(changed)])
    return dict(summary)
