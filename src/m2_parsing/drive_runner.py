"""M2 only: fresh full range processing of existing M1 checkpoints.

Run via Colab notebook or:
 python -m src.m2_parsing.drive_runner --ranges 1 2 --m1-parent-id <shared-folder-id> \\
      --output /content/drive/MyDrive/M2_CLEAN_FINAL

Use --local-checkpoints /path/to/checkpoints for offline smoke tests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .diagnostics import save_diagnostics
from src.m2_parsing.batch_pipeline import discover_checkpoint_batches, PIPELINE_REVISION
from src.m2_parsing.cache import code_fingerprint
from src.m2_parsing.quality_checks import (validate_range_output, verify_tables_zip,
                                          combine_verified_range_zips)

M1_DEFAULT = '1LVKMyNXHzPgOQS3tufc5-PIDHzcMZqxu'
TABLES = ('elements.jsonl', 'hierarchy.jsonl', 'bibtex.jsonl', 'metrics_m2.json')


def log(message):
    print(f'[{datetime.now(timezone.utc).isoformat(timespec="seconds")}] {message}', flush=True)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def connect_drive():
    import google.auth
    from googleapiclient.discovery import build
    cred, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
    return build('drive', 'v3', credentials=cred, cache_discovery=False)


def children(service, parent):
    found, token = [], None
    while True:
        result = service.files().list(q=f"'{parent}' in parents and trashed=false",
            fields='nextPageToken,files(id,name,mimeType,size,md5Checksum)',pageSize=1000,
            pageToken=token,supportsAllDrives=True,includeItemsFromAllDrives=True).execute()
        found.extend(result.get('files', []))
        token=result.get('nextPageToken')
        if not token: return found


def download(service, src, target, *, force=False):
    from googleapiclient.http import MediaIoBaseDownload
    target=Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    size=int(src['size']) if src.get('size') else None
    if not force and target.is_file() and size and target.stat().st_size==size:
        return
    temp=target.with_name(target.name+'.download_incomplete')
    for attempt in range(4):
        try:
            temp.unlink(missing_ok=True)
            request=service.files().get_media(fileId=src['id'],supportsAllDrives=True)
            with temp.open('wb') as dest:
                transfer=MediaIoBaseDownload(dest,request,chunksize=8*1024*1024)
                done=False
                last=0.
                while not done:
                    progress,done=transfer.next_chunk(num_retries=3)
                    if time.monotonic()-last>30:
                        log(f"Downloading {src['name']} {int(progress.progress()*100) if progress else '?'}%")
                        last=time.monotonic()
            if size is not None and temp.stat().st_size!=size:
                raise IOError(f"M1 download size mismatch: {src['name']}")
            if src.get('md5Checksum'):
                h=hashlib.md5()
                with temp.open('rb') as stream:
                    for block in iter(lambda: stream.read(4*1024*1024),b''):
                        h.update(block)
                if h.hexdigest()!=src['md5Checksum']:
                    raise IOError(f"M1 download MD5 mismatch: {src['name']}")
            os.replace(temp,target)
            return
        except Exception:
            if attempt==3:
                raise
            time.sleep(2**attempt)


def download_checkpoints(service,parent,range_no,target):
    folders={x['name']:x['id'] for x in children(service,parent)
             if x['mimeType']=='application/vnd.google-apps.folder'}
    name=f'range_{range_no}_dev'
    if name not in folders:
        raise FileNotFoundError(f'M1 checkpoints folder missing: {name} under {parent}')
    items={f['name']:f for f in children(service,folders[name])
           if f['name'].startswith('batch_') and f['name'].endswith(('.tar.gz','.json'))}
    tars={k for k in items if k.endswith('.tar.gz')}
    if not tars:
        raise FileNotFoundError(f'No M1 tar archives for {name}')
    for name in tars:
        if name[:-7]+'.json' not in items:
            raise FileNotFoundError(f'M1 manifest not found for {name}')
    log(f'range_{range_no}: downloading {len(items)} M1 files')
    for i,(name,item) in enumerate(sorted(items.items()),1):
        download(service,item,target/name)
        if i%10==0 or i==len(items):
            log(f'range_{range_no}: {i}/{len(items)} checkpoint files ready')
    return items


def verify_checkpoints(directory, remote=None, service=None, expected_papers=5000):
    batches=discover_checkpoint_batches(directory)
    # Every input archive is verified BEFORE parsing; no silently accepted truncation.
    count=0
    for _,archive,manifest in batches:
        count+=len(manifest['ids'])
        size=manifest['archive_bytes']
        checksum=manifest['archive_sha256']
        if archive.stat().st_size!=size or sha256(archive)!=checksum:
            name=archive.name
            if remote and service and name in remote:
                log(f'Archive integrity mismatch, redownloading {name} once')
                download(service,remote[name],archive,force=True)
            if archive.stat().st_size!=size or sha256(archive)!=checksum:
                raise IOError(f'Invalid M1 archive checksum: {name}')
    if count!=expected_papers:
        raise ValueError(f'Expected {expected_papers} unique paper IDs, found {count}. Refusing incomplete M1 range.')
    return batches


def checkpoint_identity(source, range_no, remote=False, service=None):
    if remote:
        folders = [x for x in children(service, source) if x['name'] == f'range_{range_no}_dev'
                   and x['mimeType'] == 'application/vnd.google-apps.folder']
        if len(folders) != 1: raise ValueError(f'Expected exactly one range_{range_no}_dev folder')
        files = [x for x in children(service, folders[0]['id'])
                 if x['name'].startswith('batch_') and x['name'].endswith(('.json','.tar.gz'))]
        if len({x['name'] for x in files}) != len(files): raise ValueError('Duplicate checkpoint names')
        if any(not x.get('md5Checksum') for x in files):
            raise ValueError('Drive did not return content checksums for all M1 checkpoint files')
        return {x['name']: {'id':x['id'],'size':x.get('size'),'md5':x['md5Checksum']} for x in files}
    folder = Path(source) / f'range_{range_no}_dev'
    return {p.name: {'sha256':sha256(p),'size':p.stat().st_size} for p in sorted(folder.iterdir())
            if p.is_file() and p.name.startswith('batch_') and p.name.endswith(('.json','.tar.gz'))}


def already_done(output,range_no,source_identity=None):
    directory=Path(output)/f'range_{range_no}'
    if not directory.exists(): return False
    zip_path=directory/f'M2_range_{range_no}_tables.zip'
    benchmark=directory/'benchmark_summary.json'
    qa=directory/'quality_report.json'
    if not all(f.is_file() for f in (zip_path,benchmark,qa,directory/'paper_status.jsonl')):
        raise RuntimeError(f'Incomplete existing output: {directory}. Inspect before retrying.')
    b=json.loads(benchmark.read_text(encoding='utf-8'))
    q=json.loads(qa.read_text(encoding='utf-8'))
    if not q.get('passed') or q.get('pipeline_revision')!=PIPELINE_REVISION:
        raise RuntimeError(f'Range {range_no} has non-passing QA')
    if sha256(zip_path)!=b.get('zip_sha256'):
        raise RuntimeError(f'Range {range_no}: ZIP sha mismatch')
    verify_tables_zip(zip_path)
    with zipfile.ZipFile(zip_path) as zipped:
        metrics = json.loads(zipped.read('metrics_m2.json'))
    if metrics.get('code_fingerprint') != code_fingerprint():
        raise RuntimeError(f'Range {range_no}: code/dependency fingerprint changed. Use a new output directory; old results are preserved.')
    if source_identity is not None:
        integrity=json.loads((directory/'input_integrity.json').read_text(encoding='utf8'))
        if integrity.get('source_identity') != source_identity:
            raise RuntimeError(f'Range {range_no}: M1 checkpoint identity changed. Use a new output directory.')
    log(f'range_{range_no}: existing output QA/SHA/ZIP verified, SKIP')
    return True


def parse_range(rangen,checkpoint,output,workspace,workers,remote,service,expected_papers=5000,source_identity=None):
    name=f'range_{rangen}'
    w=Path(workspace)/name
    batch_dir=w/'checkpoints'
    tables_dir=w/'tables'
    working_dir=w/'working'
    batch_dir.mkdir(parents=True,exist_ok=True)
    if remote:
        remote_files=download_checkpoints(service,checkpoint,rangen,batch_dir)
    else:
        remote_files=None
        source=Path(checkpoint)/f'{name}_dev'
        if not source.is_dir(): raise FileNotFoundError(source)
        for item in source.iterdir():
            if item.name.startswith('batch_') and item.name.endswith(('.json','.tar.gz')):
                dest=batch_dir/item.name
                if not dest.exists() or dest.stat().st_size!=item.stat().st_size:
                    shutil.copy2(item,dest)
    batches=verify_checkpoints(batch_dir,remote_files,service,expected_papers)
    log(f'{name}: verified {len(batches)} M1 batch archives; starting M2 CPU parser (workers={workers})')
    cmd=[sys.executable,'-u','-m','src.m2_parsing.run_m2',
        '--batch-dir',str(batch_dir),'--working-dir',str(working_dir),
        '--tables-dir',str(tables_dir),'--workers',str(workers),'--resume']
    logpath=w/'parser_full.log'
    started=time.monotonic()
    import threading
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(60):
            log(f'{name}: parsing still running, elapsed {int(time.monotonic()-started)}s; see parser_full.log')
    monitor=threading.Thread(target=heartbeat,daemon=True)
    monitor.start()
    try:
        with logpath.open('a',encoding='utf-8') as stream:
            stream.write('\n### M2 invocation: '+repr(cmd)+'\n')
            stream.flush()
            process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                     text=True,bufsize=1)
            for line in process.stdout:
                stream.write(line)
                stream.flush()
                # All details in file, batch progress and failures also on Colab output.
                if ('M2 batch ' in line or 'ERROR' in line or 'Traceback' in line
                    or 'failed to parse' in line or 'failed to finalize' in line):
                    print(line.rstrip(),flush=True)
            rc=process.wait()
    finally:
        stop.set()
        monitor.join(timeout=2)
    if rc not in (0,2):
        raise RuntimeError(f'{name} parser exited {rc}, see {logpath}')
    metrics=json.loads((tables_dir/'metrics_m2.json').read_text(encoding='utf-8'))
    if metrics.get('n_publications')!=expected_papers or metrics.get('pipeline_revision')!=PIPELINE_REVISION:
        raise RuntimeError(f'{name}: mismatched parser revision or M1 coverage')
    qa=validate_range_output(tables_dir,batch_dir,check_rows=True)
    if not qa['passed']:
        raise RuntimeError(f'{name}: QA did not pass')
    qa['verification']='FULL_M2_REBUILD_FROM_M1'
    qa['warning_policy']='Filename-only template alarms disabled; status in paper_status.jsonl'
    report_dir=w/'reports'
    report_dir.mkdir(parents=True,exist_ok=True)
    status=save_diagnostics(metrics,report_dir)
    write_json(report_dir/'quality_report.json',qa)
    write_json(report_dir/'input_integrity.json',{
        'range':rangen,'archive_count':len(batches),'unique_papers':expected_papers,
        'archive_size_sha256_verified':True,'input_scope':'Existing M1; no source modifications',
        'source_identity': source_identity if source_identity is not None else checkpoint_identity(checkpoint,rangen,remote,service),
        'archive_sha256_by_name': {archive.name: manifest['archive_sha256'] for _,archive,manifest in batches},
        'manifest_sha256_by_name': {archive.name.removesuffix('.tar.gz')+'.json': sha256(archive.with_name(archive.name.removesuffix('.tar.gz')+'.json')) for _,archive,manifest in batches},
    })
    zip_path=w/f'M2_range_{rangen}_tables.zip'
    with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
        for file_name in TABLES:
            z.write(tables_dir/file_name,arcname=file_name)
    verify_tables_zip(zip_path,metrics)
    zip_sha=sha256(zip_path)
    write_json(report_dir/'benchmark_summary.json',{
        'range':rangen,'pipeline_revision':PIPELINE_REVISION,
        'n_publications':metrics['n_publications'],
        'n_versions_total':metrics['n_versions_total'],
        'n_versions_parsed':metrics['n_versions_parsed'],
        'n_versions_empty':metrics['n_versions_empty'],
        'n_versions_partial':metrics['n_versions_partial'],
        'n_versions_failed':metrics['n_versions_failed'],
        'zip_sha256':zip_sha,'zip_bytes':zip_path.stat().st_size,
        'elapsed_sec':round(time.monotonic()-started,2),
        'semantic_review_is_not_equivalent_to_QA_failure':True,
        'code_fingerprint': code_fingerprint(),
        'reused_batches': metrics.get('reused_batches', 0),
        'n_publications_reused': metrics.get('n_publications_reused', 0),
    })
    publish=w/'publish'
    publish.mkdir(parents=True,exist_ok=True)
    shutil.copy2(zip_path,publish/zip_path.name)
    for f in report_dir.iterdir():
        if f.is_file(): shutil.copy2(f,publish/f.name)
    for file_name in ('semantic_review.jsonl',):
        candidate=tables_dir/file_name
        if candidate.exists(): shutil.copy2(candidate,publish/candidate.name)
    shutil.copy2(logpath,publish/logpath.name)
    destination=Path(output)/name
    if destination.exists(): raise FileExistsError(f'Output already exists: {destination}')
    pending=destination.parent/f'.{name}.incomplete'
    if pending.exists():
        raise FileExistsError(f'Interrupted Drive publish exists: {pending}. Inspect and remove if safe.')
    pending.mkdir(parents=True)
    for file in publish.iterdir():
        dest=pending/file.name
        shutil.copy2(file,dest)
        if sha256(file)!=sha256(dest):
            raise IOError(f'Output copy verification failed: {file.name}')
    os.rename(pending,destination)
    log(f'{name}: output published; versions={metrics["n_versions_total"]} status={status["status_counts"]}')
    # Keep verified batch/publication receipts so a later interrupted run can
    # resume. The notebook lets the user choose persistent or ephemeral storage.
    return status


def build_master_if_complete(output):
    output=Path(output)
    if not all((output/f'range_{n}').is_dir() for n in range(1,6)):
        log('Master not created: some ranges missing. This is normal when running a subset.')
        return
    for n in range(1,6):
        already_done(output,n)
    dest=output/'M2_master_PROVISIONAL_tables.zip'
    if dest.exists():
        log('Master ZIP already exists; preserving it.')
        return
    temp=output/'.M2_master.incomplete.zip'
    if temp.exists(): raise FileExistsError(temp)
    manifest=combine_verified_range_zips(output,range(1,6),temp)
    with zipfile.ZipFile(temp) as z:
        invalid=z.testzip()
        if invalid: raise RuntimeError('Master CRC failed: '+invalid)
    os.replace(temp,dest)
    manifest['sha256']=sha256(dest)
    manifest['status']='PROVISIONAL_REVIEW_NOT_FULL_SEMANTIC_CERTIFICATION'
    write_json(output/'M2_master_manifest.json',manifest)
    log('Master ZIP verified and published')


def main(argv=None):
    p=argparse.ArgumentParser(description='M2: source/code/output-verified resume')
    p.add_argument('--ranges',type=int,nargs='+',required=True)
    p.add_argument('--m1-parent-id',default=M1_DEFAULT)
    p.add_argument('--local-checkpoints',default=None)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workspace',type=Path,default=Path('/content/m2_clean_workspace'))
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--master',action='store_true')
    p.add_argument('--expected-papers',type=int,default=5000,help='Expected paper IDs per range (default: 5000)')
    args=p.parse_args(argv)
    if len(set(args.ranges))!=len(args.ranges) or not set(args.ranges).issubset({1,2,3,4,5}):
        p.error('ranges must be unique values between 1 and 5')
    if args.workers<1: p.error('workers must be >= 1')
    args.output.mkdir(parents=True,exist_ok=True)
    args.workspace.mkdir(parents=True,exist_ok=True)
    service=None if args.local_checkpoints else connect_drive()
    source=args.local_checkpoints if args.local_checkpoints else args.m1_parent_id
    for no in args.ranges:
        try:
            identity=checkpoint_identity(source,no,not args.local_checkpoints,service)
            if already_done(args.output,no,identity): continue
            parse_range(no,source,args.output,args.workspace,args.workers,
                        remote=(not args.local_checkpoints),service=service,
                        expected_papers=args.expected_papers,source_identity=identity)
        except Exception:
            log(f'range_{no} ABORTED; preserving workspace and traceback')
            write_json(args.output/f'FAILED_range_{no}_{int(time.time())}.json',{
                'range':no,'traceback':traceback.format_exc(),
                'workspace':str(args.workspace/f'range_{no}')})
            raise
    if args.master:
        build_master_if_complete(args.output)
    summary={}
    for no in range(1,6):
        path=args.output/f'range_{no}'/'status_summary.json'
        if path.exists():summary[str(no)]=json.loads(path.read_text(encoding='utf-8'))
    write_json(args.output/'RUN_SUMMARY.json',summary)
    log(f'COMPLETE. Output: {args.output}')


if __name__=='__main__':
    main()
