#!/usr/bin/env python3
"""Evaluate globally held-out Test (only after model lock), or export 9-column Parquet.

Separate commands:
  python M3_GLOBAL5_TEST_AND_EXPORT.py --phase test --prepared-dir ... \
      --model-dir ... --split ... --manifest ... --out-dir ...
  python M3_GLOBAL5_TEST_AND_EXPORT.py --phase export --prepared-dir ... \
      --model-dir ... --split ... --manifest ... --out-dir ...

Neither command retrains or edits inputs; model choice LR13 is frozen before Test.
This script NEVER selects a model from Test performance.
"""
from __future__ import annotations
import argparse,collections,csv,hashlib,heapq,json,math
from pathlib import Path
if __package__:
    from .M3_GLOBAL5_TRAIN_VALIDATE import FEATURES, META, evaluate_models, sha, require
else:  # supports 'python scripts/m3_global5/M3_GLOBAL5_TEST_AND_EXPORT.py'
    from M3_GLOBAL5_TRAIN_VALIDATE import FEATURES, META, evaluate_models, sha, require

SCHEMA_COLS=['arxiv_id','partition','citation_key','groundtruth_arxiv_id','cand_1','cand_2','cand_3','cand_4','cand_5']
PARTS=('train','valid','test')

def guard(prep,models,split,manifest,mode,outdir):
 require(not outdir.exists(),'Refusing to overwrite output')
 paths=[prep/'global5_prepared_manifest.json',models/'global5_pretest_model_lock.json',split,manifest]
 require(all(x.is_file() for x in paths),'Missing frozen manifest/lock/split')
 dp=json.loads(paths[0].read_text(encoding='utf-8'))
 ml=json.loads(paths[1].read_text(encoding='utf-8'))
 sm=json.loads(manifest.read_text(encoding='utf-8'))
 require(dp['status']=='PASS' and sm['status']=='PASS' and ml['status']=='PASS','A preflight did not pass')
 require(sm.get('global_holdouts')=={'test':['2604.01323','2603.18656'],'valid':['2604.00125','2604.03553']},'Frozen holdout IDs changed')
 require(dp['split_csv_sha256']==sm['split_csv_sha256']==ml['global5_split_csv_sha256']==sha(split),'Frozen split mismatch')
 require(ml['protocol']=='M3_GLOBAL5_LR13_PRIMARY_BEFORE_TEST_v1' and ml['primary']=='LR13' and ml.get('test_was_not_opened') is True,'Model choice was not locked pre-Test')
 require(ml['train_sha256']==dp['partition']['train']['sha256'] and ml['valid_sha256']==dp['partition']['valid']['sha256'],'Model trained on a different split')
 for p in PARTS:
  path=prep/f'{p}_pairs.parquet'
  require(path.is_file() and sha(path)==dp['partition'][p]['sha256'],f'{p} split changed')
 for name in ('LR13','LGBM13'):
  x=models/ml['models'][name]['path']
  require(x.is_file() and sha(x)==ml['models'][name]['sha256'],f'{name} model changed')
 require(not outdir.resolve().is_relative_to(prep.resolve()),'Output must not be in frozen prepared data')
 require(not outdir.resolve().is_relative_to(models.resolve()),'Output must not be in locked model folder')
 import joblib
 # Only load joblib produced by the user's own local trained script; never untrusted pickles.
 lr=joblib.load(models/ml['models']['LR13']['path'])
 gb=joblib.load(models/ml['models']['LGBM13']['path'])
 require(lr['features']==FEATURES and gb['features']==FEATURES,'Feature order mismatched')
 require(list(lr['pipeline'].classes_)==[0,1] and list(gb['model'].classes_)==[0,1],'Binary model classes mismatched')
 return dp,ml,sm,{'LR13':lr['pipeline'],'LGBM13':gb['model']}

def test_eval(a,dp,ml,sm,models):
 import pandas as pd
 df=pd.read_parquet(a.prepared_dir/'test_pairs.parquet',columns=META+FEATURES)
 metrics,rows,top5,disagree=evaluate_models(df,models)
 src={r['arxiv_id']:r for r in csv.DictReader(a.split.open(encoding='utf-8-sig',newline=''))}
 groups={}
 for origin in ['manual','auto']:
  ids=[x for x in sm['global_holdouts']['test'] if src[x]['label_source']==origin]
  require(len(ids)==1,'Test must have one manual and one auto')
  pid=ids[0]
  arr=[r for r in rows if r['arxiv_id']==pid]
  require(len(arr)==int(src[pid]['labeled_queries']),f'Test {pid} query count differs from frozen labels')
  groups[origin]={'publication':pid,'queries':len(arr),'positive':sum(x['positive']==1 for x in arr),
                  'gt_null':sum(x['groundtruth_arxiv_id'] is None for x in arr),
                  'known_gt_outside_pool':sum(x['known_gt_outside_pool'] for x in arr),
                  'MRR@5':{m:math.fsum(x[m+'_rr_at_5'] for x in arr)/len(arr) for m in metrics}}
 a.out_dir.mkdir(parents=True,exist_ok=False)
 report={'status':'PASS','protocol':ml['protocol'],'primary':'LR13',
         'test_sha256':dp['partition']['test']['sha256'],'per_source_publication':groups,
         'by_method':metrics,'top1_disagreement_queries':disagree,'test_decision_tuning':False}
 (a.out_dir/'global5_test_metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 for name,data in [('global5_test_query_metrics.csv',rows),('global5_test_top5.csv',top5)]:
  with (a.out_dir/name).open('x',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 for origin,v in groups.items(): print(f'[TEST] {origin}: {v["publication"]} queries={v["queries"]} MRR(LR13)={v["MRR@5"]["LR13"]:.6f}',flush=True)
 print('[SUCCESS] Global 5-Range TEST evaluated with FROZEN LR13 primary; no refit, no tuning',flush=True)

def export_predictions(a,dp,ml,sm,models):
 import pandas as pd
 import numpy as np
 import pyarrow as pa
 import pyarrow.parquet as pq
 pubmap={r['arxiv_id']:r for r in csv.DictReader(a.split.open(encoding='utf-8-sig',newline=''))}
 import pyarrow.compute as pc
 fields=[pa.field('arxiv_id',pa.string(),nullable=False),pa.field('partition',pa.dictionary(pa.int8(),pa.string()),nullable=False),
         pa.field('citation_key',pa.string(),nullable=False),pa.field('groundtruth_arxiv_id',pa.string(),nullable=True)]
 fields.extend(pa.field(f'cand_{i}',pa.string(),nullable=True) for i in range(1,6))
 schema=pa.schema(fields)
 a.out_dir.mkdir(parents=True,exist_ok=False)
 target=a.out_dir/'predictions.parquet';writer=pq.ParquetWriter(target,schema,compression='zstd')
 buffer=[];part_queries=collections.Counter();exceptions=[];preds_written=0
 def flush_buffer():
  nonlocal preds_written
  if not buffer:return
  dat={c:[r[c] for r in buffer] for c in SCHEMA_COLS}
  arrays=[]
  for c in SCHEMA_COLS:
   if c=='partition':
    # Normalize to dictionary Arrow type, exactly as required in statement.
    arr=pa.array(dat[c],type=pa.string()).dictionary_encode()
    arr=arr.cast(pa.dictionary(pa.int8(),pa.string()))
   else:arr=pa.array(dat[c],type=pa.string())
   arrays.append(arr)
  writer.write_table(pa.Table.from_arrays(arrays,schema=schema))
  preds_written+=len(buffer);buffer.clear()
 try:
  for part in PARTS:
   pf=pq.ParquetFile(a.prepared_dir/f'{part}_pairs.parquet')
   current_q=None;current_gt=None;heap=[];pos=0;refs=set();order=0;candidate_count=0
   def flush_query():
    nonlocal current_q,current_gt,heap,pos,refs,order,candidate_count
    if current_q is None:return
    require(pos<=1,f'Multiple positives {current_q}')
    if current_gt is not None and pos==0:
     exceptions.append({'partition':part,'arxiv_id':current_q[0],'citation_key':current_q[1],
                        'groundtruth_arxiv_id':current_gt,'candidate_count':candidate_count})
    rank=sorted(heap,reverse=True)  # score desc, -original_order desc: earlier input wins ties
    tops=[x[2] for x in rank]
    row={'arxiv_id':current_q[0],'partition':part,'citation_key':current_q[1],
         'groundtruth_arxiv_id':current_gt}
    row.update({f'cand_{j}':tops[j-1] if j<=len(tops) else None for j in range(1,6)})
    buffer.append(row);part_queries[part]+=1
    if len(buffer)>=3000:flush_buffer()
    current_q=None;current_gt=None;heap=[];pos=0;refs=set();order=0;candidate_count=0
   for batch in pf.iter_batches(batch_size=a.batch_size,columns=META+FEATURES):
    f=batch.to_pandas()
    x=f[FEATURES].to_numpy(dtype=np.float64,copy=True)
    require(np.isfinite(x).all(),f'{part} feature invalid')
    prob=models['LR13'].predict_proba(x)[:,1]
    require(np.isfinite(prob).all(),f'{part} bad model score')
    for i,r in enumerate(f.itertuples(index=False,name=None)):
     row=dict(zip(META+FEATURES,r))
     pid=row['arxiv_id'];key=row['citation_key'];ref=row['ref_arxiv_id'];gt=row['groundtruth_arxiv_id']
     gt=None if pd.isna(gt) else str(gt)
     require(pid in pubmap and pubmap[pid]['partition']==part,f'Wrong partition for {pid}')
     q=(pid,key)
     if q!=current_q:
      flush_query();current_q=q;current_gt=gt
     require(current_gt==gt,f'GT differs in {q}')
     require(ref not in refs,f'Duplicate candidate {q}/{ref}');refs.add(ref)
     require(int(row['label'])==int(gt is not None and ref==gt),f'Label mismatch {q}')
     pos+=int(row['label']);candidate_count+=1
     tup=(float(prob[i]),-order,str(ref));order+=1
     if len(heap)<5:heapq.heappush(heap,tup)
     elif tup>heap[0]:heapq.heapreplace(heap,tup)
   flush_query();flush_buffer()
   expected=dp['partition'][part]['queries']
   require(part_queries[part]==expected,f'{part} query rows {part_queries[part]} != {expected}')
   print(f'[PASS] Exported {part}: {part_queries[part]:,} predictions',flush=True)
  writer.close()
  with (a.out_dir/'known_gt_outside_pool.csv').open('x',encoding='utf-8',newline='') as f:
   w=csv.DictWriter(f,fieldnames=['partition','arxiv_id','citation_key','groundtruth_arxiv_id','candidate_count']);w.writeheader();w.writerows(exceptions)
  report={'status':'PASS','scope':'5 ranges unified','primary':'LR13','model_sha256':ml['models']['LR13']['sha256'],
          'split_csv_sha256':sm['split_csv_sha256'],'prepared_manifest':dp['partition'],
          'schema':SCHEMA_COLS,'predictions_rows':preds_written,'partition_query_counts':dict(part_queries),
          'known_gt_outside_pool_count':len(exceptions),'predictions_sha256':sha(target),
          'no_data_change_or_model_tuning':True}
  (a.out_dir/'global5_predictions_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print('[SUCCESS] 5-Range unified predictions Parquet exported',flush=True)
 finally:
  try:writer.close()
  except Exception:pass

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--phase',choices=['test','export'],required=True)
 p.add_argument('--prepared-dir',type=Path,required=True)
 p.add_argument('--model-dir',type=Path,required=True)
 p.add_argument('--split',type=Path,required=True)
 p.add_argument('--manifest',type=Path,required=True)
 p.add_argument('--out-dir',type=Path,required=True)
 p.add_argument('--batch-size',type=int,default=75000)
 a=p.parse_args();require(a.batch_size>0,'batch_size >0')
 dp,ml,sm,models=guard(a.prepared_dir,a.model_dir,a.split,a.manifest,a.phase,a.out_dir)
 if a.phase=='test':test_eval(a,dp,ml,sm,models)
 else:export_predictions(a,dp,ml,sm,models)
if __name__=='__main__':main()
