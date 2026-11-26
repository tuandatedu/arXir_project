#!/usr/bin/env python3
"""One global-5-Range ML experiment: train on group Train, validate on group Valid.

Never reads Test. Two ML models (LR13, LightGBM13) plus B1/B2 ranking controls.
Uses disk-backed memmap to avoid loading a giant pandas Training frame.
Respects pre-declared PRIMARY=LR13. The only result here is Validation.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from pathlib import Path
from collections import defaultdict

FEATURES=["title_levenshtein","title_token_sort","title_token_set","title_jaccard","title_exact","title_len_diff_ratio","author_jaccard","author_first_match","author_any_match","year_diff","year_exact","year_missing","cite_count"]
META=["arxiv_id","citation_key","ref_arxiv_id","groundtruth_arxiv_id","label"]
PRIMARY='LR13'; METHODS=('B1','B2','LR13','LGBM13')

def require(x,msg):
 if not x: raise ValueError(msg)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()

def evaluate_models(df,models):
 import numpy as np
 import pandas as pd
 require(not df.empty, 'Evaluation input empty')
 Xlr=df[FEATURES].to_numpy(dtype=np.float64)
 Xgb=df[FEATURES].to_numpy(dtype=np.float32)
 scores={
  'B1':df['title_levenshtein'].to_numpy(dtype=float),
  'B2':0.7*df['title_levenshtein'].to_numpy(dtype=float)+0.2*df['author_jaccard'].to_numpy(dtype=float)+0.1*df['year_exact'].to_numpy(dtype=float),
  'LR13':models['LR13'].predict_proba(Xlr)[:,list(models['LR13'].classes_).index(1)],
  'LGBM13':models['LGBM13'].predict_proba(pd.DataFrame(Xgb,columns=FEATURES))[:,list(models['LGBM13'].classes_).index(1)]
 }
 for m,v in scores.items():require(np.isfinite(v).all(),f'{m} invalid scores')
 out=[];tops=[];disagree=0
 for (pid,key),inds in df.groupby(['arxiv_id','citation_key'],sort=True).indices.items():
  group=df.iloc[inds]
  gt=[x for x in group['groundtruth_arxiv_id'].unique() if pd.notna(x)]
  require(len(gt)<=1 and (len(gt)==1 or group['groundtruth_arxiv_id'].isna().all()),f'GT mismatch in {pid}/{key}')
  refids=group['ref_arxiv_id'].tolist()
  require(len(refids)==len(set(refids)),f'Duplicate ref in {pid}/{key}')
  labels=group['label'].to_numpy(dtype=int)
  require(np.isin(labels,[0,1]).all() and int(labels.sum())<=1,f'Invalid label {pid}/{key}')
  orig_gt=gt[0] if gt else None
  require(all(int(labels[i])==int(orig_gt is not None and str(refids[i])==str(orig_gt)) for i in range(len(labels))),f'Wrong pair labels {pid}/{key}')
  sample={'arxiv_id':pid,'citation_key':key,'groundtruth_arxiv_id':orig_gt,'positive':int(labels.sum()),'known_gt_outside_pool':int(orig_gt is not None and labels.sum()==0)}
  tops_this={}
  for m in METHODS:
   # groupby.indices produces integer iloc positions, preserving original within-group order.
   score=scores[m][inds]
   rank=np.argsort(-score,kind='stable')
   rankpos=int(np.flatnonzero(labels[rank]==1)[0])+1 if labels.sum()==1 else None
   rr=1/rankpos if rankpos is not None and rankpos<=5 else 0.0
   sample[m+'_rr_at_5']=rr;sample[m+'_rank']=rankpos
   tops_this[m]=str(refids[rank[0]])
   for k,j in enumerate(rank[:5],start=1):tops.append({'method':m,'arxiv_id':pid,'citation_key':key,'rank':k,'ref_arxiv_id':refids[j],'label':int(labels[j]),'score':float(score[j])})
  sample['top1_disagree']=len(set(tops_this.values()))>1
  disagree+=sample['top1_disagree'];out.append(sample)
 metrics={}
 for m in METHODS:
  rr=[x[m+'_rr_at_5'] for x in out]
  pos=[x for x in out if x['positive']==1]
  metrics[m]={'queries':len(out),'positive_queries':len(pos),'gt_null_queries':sum(x['groundtruth_arxiv_id'] is None for x in out),
             'known_gt_outside_pool':sum(x['known_gt_outside_pool'] for x in out),'mrr_at_5_all':math.fsum(rr)/len(rr),
             'mrr_at_5_positive_only':math.fsum(x[m+'_rr_at_5'] for x in pos)/len(pos) if pos else None,
             'hit_at_1_positive_only':sum(x[m+'_rank']==1 for x in pos)/len(pos) if pos else None}
 return metrics,out,tops,disagree

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--prepared-dir',type=Path,required=True)
 p.add_argument('--out-dir',type=Path,required=True)
 p.add_argument('--num-threads',type=int,default=4)
 p.add_argument('--batch-size',type=int,default=100000)
 args=p.parse_args()
 require(not args.out_dir.exists(),'Refusing to overwrite output')
 require(args.num_threads>=1 and args.batch_size>=500,'Invalid batch/threads')
 prep=args.prepared_dir;mp=prep/'global5_prepared_manifest.json'
 require(mp.is_file(),'Global5 prepared manifest missing')
 manifest=json.loads(mp.read_text(encoding='utf-8'))
 require(manifest['status']=='PASS' and manifest['split_protocol']=='M3_GLOBAL5_PUBLICATION_SPLIT_PRETRAIN_v1_2026-11-26','Wrong global 5 dataset')
 tr=prep/'train_pairs.parquet';va=prep/'valid_pairs.parquet'
 for part,f in [('train',tr),('valid',va)]:
  require(f.is_file() and sha(f)==manifest['partition'][part]['sha256'],f'{part} dataset changed since frozen prepare')
 # IMPORTANT: No reference to, open() or use of test_pairs.parquet in this program.
 import numpy as np
 import pandas as pd
 import pyarrow.parquet as pq
 import joblib
 from sklearn.preprocessing import StandardScaler
 from sklearn.linear_model import LogisticRegression
 from sklearn.pipeline import Pipeline
 from lightgbm import LGBMClassifier
 from lightgbm import __version__ as lgb_version
 pf=pq.ParquetFile(tr);n=pf.metadata.num_rows
 require(n>0 and all(k in pf.schema_arrow.names for k in FEATURES+['label']),'Train lacks required features')
 args.out_dir.mkdir(parents=True,exist_ok=False)
 raw=args.out_dir/'temp_train_features.f32';lab=args.out_dir/'temp_train_labels.i8'
 X=np.memmap(raw,dtype=np.float32,mode='w+',shape=(n,len(FEATURES)))
 y=np.memmap(lab,dtype=np.int8,mode='w+',shape=(n,))
 scaler=StandardScaler();ptr=0
 try:
  for b in pf.iter_batches(batch_size=args.batch_size,columns=FEATURES+['label']):
   f=b.to_pandas();sl=len(f)
   x=f[FEATURES].to_numpy(dtype=np.float32,copy=True);yy=f['label'].to_numpy(dtype=np.int8)
   require(np.isfinite(x).all() and np.isin(yy,[0,1]).all(),'Train NaN/Inf/nonbinary')
   X[ptr:ptr+sl]=x;y[ptr:ptr+sl]=yy;scaler.partial_fit(x);ptr+=sl
   if ptr%1000000<args.batch_size:print(f'[TRAIN cache] {ptr:,}/{n:,}',flush=True)
  require(ptr==n and set(np.unique(y))=={0,1},'Train rows/classes invalid')
  positive_count=int(np.count_nonzero(y))
  X.flush();y.flush(); print('[PASS] Prepared disk-backed full Train features / scaler',flush=True)
  cfg=dict(boosting_type='gbdt',objective='binary',n_estimators=300,learning_rate=0.05,num_leaves=31,
           min_child_samples=100,reg_lambda=1.0,class_weight=None,random_state=42,deterministic=True,
           force_col_wise=True,verbosity=-1,n_jobs=args.num_threads)
  print('[TRAIN] LightGBM 13-feature full Train (comparator)',flush=True)
  gb=LGBMClassifier(**cfg)
  gb.fit(X,y,feature_name=FEATURES)
  joblib.dump({'model':gb,'features':FEATURES},args.out_dir/'lgbm13_model.joblib')
  print('[PASS] LightGBM fitted, saved',flush=True)
  # The classifier is trained on standardized features; the saved Pipeline scaler
  # transparently applies that SAME transformation to raw inference features.
  print('[TRAIN] Standardized Logistic Regression 13-feature full Train (primary)',flush=True)
  for start in range(0,n,args.batch_size):
   stop=min(n,start+args.batch_size)
   X[start:stop]=scaler.transform(X[start:stop])
  X.flush()
  logit=LogisticRegression(solver='lbfgs',max_iter=1000,class_weight=None,random_state=42)
  logit.fit(X,y)
  lr=Pipeline([('standardscaler',scaler),('logisticregression',logit)])
  joblib.dump({'pipeline':lr,'features':FEATURES},args.out_dir/'lr13_model.joblib')
  print('[PASS] LR13 fitted, saved',flush=True)
  del X,y
  raw.unlink();lab.unlink()
  valid=pd.read_parquet(va,columns=META+FEATURES)
  scores,query_rows,top5,disagree=evaluate_models(valid,{'LR13':lr,'LGBM13':gb})
  with (args.out_dir/'validation_query_metrics.csv').open('x',newline='',encoding='utf-8') as f:
   w=csv.DictWriter(f,fieldnames=list(query_rows[0]));w.writeheader();w.writerows(query_rows)
  with (args.out_dir/'validation_top5.csv').open('x',newline='',encoding='utf-8') as f:
   w=csv.DictWriter(f,fieldnames=list(top5[0]));w.writeheader();w.writerows(top5)
  report={'status':'PASS','protocol':'M3_GLOBAL5_LR13_PRIMARY_BEFORE_TEST_v1','primary':'LR13',
          'models':{'LR13':{'path':'lr13_model.joblib','sha256':sha(args.out_dir/'lr13_model.joblib'),
                              'pipeline':'StandardScaler -> LogisticRegression', 'lbfgs_n_iter':int(logit.n_iter_[0])},
                    'LGBM13':{'path':'lgbm13_model.joblib','sha256':sha(args.out_dir/'lgbm13_model.joblib'),
                              'trees':int(gb.n_estimators_),'lightgbm_version':lgb_version}},
          'features':FEATURES,'train_sha256':manifest['partition']['train']['sha256'],
          'valid_sha256':manifest['partition']['valid']['sha256'],
          'global5_split_csv_sha256':manifest['split_csv_sha256'],'validation':scores,
          'valid_top1_disagreement_count':int(disagree),'train_pairs':n,
          'groundtruth_limitations':'Automatic labels may be DOI-first/title/author/year heuristic; GT-null RR 0; no abstention',
          'test_was_not_opened':True,'selection_protocol':'LR13 preselected prior to global test. No test tuning.'}
  (args.out_dir/'global5_pretest_model_lock.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
  for method,m in scores.items():print(f'[VALID] {method} MRR@5={m["mrr_at_5_all"]:.6f}; positives={m["positive_queries"]}; null={m["gt_null_queries"]}',flush=True)
  print('[SUCCESS] Global5 LR13 and LightGBM trained; VALID checked; GLOBAL TEST UNOPENED.',flush=True)
 finally:
  for f in [raw,lab]:
   if f.exists():
    try: f.unlink()
    except PermissionError:pass
if __name__=='__main__':main()
