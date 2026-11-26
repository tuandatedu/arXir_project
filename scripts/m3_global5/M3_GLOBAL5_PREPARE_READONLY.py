#!/usr/bin/env python3
"""Repartition five immutable M3 Range dataset_pairs.parquet files by publication.

Reads *all 5* full candidate-pair Parquets but does NOT train/evaluate any model.
Writes a new, immutable global Train/Valid/Test snapshot. Never modifies inputs.
The four holdout publication IDs and every other publication assignment are
pinned in global5_publication_split.csv and SHA256-pinned by split manifest.

Usage: python M3_GLOBAL5_PREPARE_READONLY.py --split global5_publication_split.csv \
  --manifest global5_split_manifest.json --r1 RANGE1/dataset_pairs.parquet \
  --r2 RANGE2/dataset_pairs.parquet --r3 ... --r4 ... --r5 ... \
  --out-dir outputs/global5_prepared_01
"""
from __future__ import annotations
import argparse, collections, csv, hashlib, json, math
from pathlib import Path

FEATURES=("title_levenshtein", "title_token_sort", "title_token_set", "title_jaccard", "title_exact",
          "title_len_diff_ratio", "author_jaccard", "author_first_match", "author_any_match", "year_diff", "year_exact", "year_missing", "cite_count")
META=("arxiv_id", "citation_key", "ref_arxiv_id", "groundtruth_arxiv_id", "label")
SIZE_EXPECTED={"R1":41555823,"R2":45996673,"R3":47229007,"R4":43019402,"R5":50228908}
SOURCE_URLS={"R1":"https://drive.google.com/file/d/1D7Pnfx4uqd6kVnfHbqLKSg_O0VLGjieZ/view",
             "R2":"https://drive.google.com/file/d/1lzDzogqbe3aYb1V6mP3QsCzs-T_AwFAi/view",
             "R3":"https://drive.google.com/file/d/13G6r0gEjMuEQXjjA8ZrFLo-JcboLP_kk/view",
             "R4":"https://drive.google.com/file/d/1wvTV4nA17kPGphin58vVCP8lrRdEvug1/view",
             "R5":"https://drive.google.com/file/d/1kAMJxazZnkfiXUY9iM316j36tx_dqBFj/view"}

def require(condition,message):
    if not condition: raise ValueError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--split',required=True,type=Path)
    p.add_argument('--manifest',required=True,type=Path)
    for i in range(1,6): p.add_argument(f'--r{i}',required=True,type=Path)
    p.add_argument('--out-dir',required=True,type=Path)
    p.add_argument('--batch-size',type=int,default=75000)
    a=p.parse_args(); require(a.batch_size>0,'batch_size > 0');require(not a.out_dir.exists(),'Refusing to overwrite existing output')
    require(a.split.is_file() and a.manifest.is_file(),'Missing frozen split manifest/CSV')
    man=json.loads(a.manifest.read_text(encoding='utf-8-sig'))
    require(man.get('status')=='PASS' and man.get('protocol_id')=='M3_GLOBAL5_PUBLICATION_SPLIT_PRETRAIN_v1_2026-11-26','Wrong split manifest')
    require(sha(a.split)==man['split_csv_sha256'],'Split CSV hash differs! Refusing changed split')
    require(man.get('global_holdouts')=={'test':['2604.01323','2603.18656'],'valid':['2604.00125','2604.03553']},'Frozen global holdout IDs changed')
    with a.split.open(encoding='utf-8-sig',newline='') as f: records=list(csv.DictReader(f))
    require(len(records)==18523 and len({x['arxiv_id'] for x in records})==18523,'Incorrect or duplicate pub mapping')
    pub={x['arxiv_id']:x for x in records}
    byran={ran:set(x['arxiv_id'] for x in records if x['range']==ran) for ran in SIZE_EXPECTED}
    parts={p:set(x['arxiv_id'] for x in records if x['partition']==p) for p in ('train','valid','test')}
    require(len(parts['test'])==2 and len(parts['valid'])==2,'Holdout size invalid')
    for part in ('test','valid'):
        require({pub[k]['label_source'] for k in parts[part]}=={'manual','auto'},'Holdout source composition wrong')
        require(all(pub[k]['old_partition']=='train' and pub[k]['range']!='R1' for k in parts[part]),'Test/Valid is not fresh')
    paths={f'R{i}':getattr(a,f'r{i}').resolve() for i in range(1,6)}
    require(len(set(paths.values()))==5,'Input dataset paths not distinct')
    for ran,src in paths.items():
        require(src.is_file(),f'Missing input {ran}: {src}')
        require(src.name=='dataset_pairs.parquet',f'{ran} input must be FULL dataset_pairs.parquet, not train/valid/test')
        require(src.stat().st_size==SIZE_EXPECTED[ran],f'{ran} source size differs from frozen Drive snapshot; check file version')
        require(not a.out_dir.resolve().is_relative_to(src.parent), 'Never create output inside source directory')
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    required=list(META+FEATURES)
    a.out_dir.mkdir(parents=True,exist_ok=False)
    writers={};input_summ={};partition_pairs=collections.Counter();pub_query_counts=collections.Counter();pub_pair_counts=collections.Counter()
    query_last=None;seen_queries=set();row_count=0;current_ref_ids=set()
    try:
        for ran,src in paths.items():
            pf=pq.ParquetFile(src)
            missing=set(required+['partition'])-set(pf.schema_arrow.names)
            require(not missing,f'{ran} missing columns: {sorted(missing)}')
            source_count=0;old_test={x for x in byran[ran] if pub[x]['old_partition']=='test'};old_valid={x for x in byran[ran] if pub[x]['old_partition']=='valid'}
            allowed=pa.array(sorted(byran[ran]),type=pa.string())
            valold=pa.array(sorted(old_valid),type=pa.string());testold=pa.array(sorted(old_test),type=pa.string())
            valnew=pa.array(sorted(parts['valid']),type=pa.string());testnew=pa.array(sorted(parts['test']),type=pa.string())
            for batch in pf.iter_batches(batch_size=a.batch_size,columns=['partition']+required):
                t=pa.Table.from_batches([batch]);n=t.num_rows;source_count+=n;row_count+=n
                ids=t.column('arxiv_id')
                require(pc.all(pc.is_in(ids,value_set=allowed)).as_py(), f'{ran} contains publication not in split')
                # The source Parquet still records its OLD per-Range partition; verify it exactly.
                expected_old=pc.if_else(pc.is_in(ids,value_set=testold),'test',pc.if_else(pc.is_in(ids,value_set=valold),'valid','train'))
                require(pc.all(pc.equal(t.column('partition'),expected_old)).as_py(),f'{ran} old partition disagrees with reconstructed M3 split.py')
                orig_labels=t.column('label').to_numpy(zero_copy_only=False)
                require(np.isin(orig_labels,[0,1]).all(),f'{ran} label outside [0,1]')
                refs=t.column('ref_arxiv_id').to_pylist();gts=t.column('groundtruth_arxiv_id').to_pylist()
                pubids=ids.to_pylist();keys=t.column('citation_key').to_pylist()
                for i,(pid,key,ref,gt,y) in enumerate(zip(pubids,keys,refs,gts,orig_labels)):
                    require(pid and key and ref,f'{ran} blank ids in candidate row {source_count-n+i}')
                    require(int(y)==int(gt is not None and ref==gt),f'{ran} inconsistent candidate label for {pid}/{key}')
                    q=(pid,key)
                    if q!=query_last:
                        current_ref_ids=set()
                        require(q not in seen_queries, f'{ran} query not contiguous, cannot safely retain stable original ranking order: {q}')
                        seen_queries.add(q);pub_query_counts[pid]+=1;query_last=q
                    require(ref not in current_ref_ids,f'{ran} duplicate candidate reference {ref} for {q}')
                    current_ref_ids.add(ref);pub_pair_counts[pid]+=1
                for feature in FEATURES:
                    v=t.column(feature).to_numpy(zero_copy_only=False)
                    require(np.isfinite(v).all(),f'{ran} NaN/Inf feature {feature}')
                keep=t.select(required)
                imtest=pc.is_in(ids,value_set=testnew);imvalid=pc.is_in(ids,value_set=valnew)
                imtrain=pc.invert(pc.or_(imtest,imvalid))
                for part,mask in [('train',imtrain),('valid',imvalid),('test',imtest)]:
                    chunk=keep.filter(mask)
                    if not chunk.num_rows:continue
                    chunk=chunk.append_column('partition',pa.array([part]*chunk.num_rows,type=pa.string()))
                    if part not in writers:
                        writers[part]=pq.ParquetWriter(a.out_dir/f'{part}_pairs.parquet',chunk.schema,compression='zstd')
                    writers[part].write_table(chunk)
                    partition_pairs[part]+=chunk.num_rows
            input_summ[ran]={'path':str(src),'size_bytes':src.stat().st_size,'sha256':sha(src),'pairs':source_count,'publications':len(byran[ran])}
            print(f'[PASS] {ran}: {source_count:,} candidate pairs; all source memberships/old partitions checked',flush=True)
        for writer in writers.values():writer.close()
        writers.clear()
        for pid,entry in pub.items():
            require(pub_query_counts[pid]==int(entry['labeled_queries']),f'{pid}: dataset queries {pub_query_counts[pid]} != label entries {entry["labeled_queries"]}')
            require(pub_pair_counts[pid]>=pub_query_counts[pid],f'{pid}: missing candidate pairs')
        part_queries={p:sum(pub_query_counts[x] for x in parts[p]) for p in parts}
        require(part_queries['test']==59 and part_queries['valid']==64 and part_queries['train']==790739,'Unexpected global query count')
        output={p:{'path':str(a.out_dir/f'{p}_pairs.parquet'),'pairs':partition_pairs[p],'queries':part_queries[p],'publications':len(parts[p]),'sha256':sha(a.out_dir/f'{p}_pairs.parquet')} for p in parts}
        report={'status':'PASS','split_protocol':man['protocol_id'],'split_csv_sha256':man['split_csv_sha256'],'source_parquet':input_summ,'partition':output,'all_pairs':row_count,'all_queries':sum(part_queries.values()),'no_model_or_test_evaluation':True,'frozen_holdouts':man['global_holdouts'],'features':list(FEATURES)}
        (a.out_dir/'global5_prepared_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('[SUCCESS] Repartition 5 Range / one Group Train-Valid-Test: '+json.dumps(part_queries),flush=True)
    finally:
        for writer in writers.values():writer.close()
if __name__=='__main__':main()
