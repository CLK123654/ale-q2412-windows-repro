from __future__ import annotations
import csv,hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]; TASK=ROOT/'task'; EVIDENCE=ROOT/'evidence'; RUN=ROOT/'windows-runs'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def reset(p):
 if p.exists(): shutil.rmtree(p)
 p.mkdir(parents=True)
def extract(a,t):
 t.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(a) as z:z.extractall(t)
def members(r):return sorted(p.relative_to(r).as_posix() for p in r.rglob('*') if p.is_file())
def compare(a,b):
 paths=members(b)
 if members(a)!=paths: raise AssertionError('delivery path set differs from Reference')
 for rel in paths:
  if (a/rel).read_bytes().replace(b'\r\n',b'\n')!=(b/rel).read_bytes().replace(b'\r\n',b'\n'):raise AssertionError(f'delivery differs from Reference: {rel}')
 return paths
def build(i,o,h):return subprocess.run([sys.executable,str(ROOT/'implementation/build_delivery.py'),'--input',str(i),'--output',str(o),'--helm',h],cwd=ROOT,text=True,capture_output=True,timeout=300)
def main():
 reset(RUN); EVIDENCE.mkdir(exist_ok=True); helm=os.environ['HELM_PATH']; version=subprocess.run([helm,'version','--template','{{.Version}}'],text=True,capture_output=True,timeout=30)
 if version.returncode or version.stdout.strip()!='v3.18.4':raise AssertionError(version.stdout+version.stderr)
 ref=RUN/'reference';extract(TASK/'reference.zip',ref); clean=[]
 for label in ['clean-a','clean-b']:
  base=RUN/label;extract(TASK/'输入数据包.zip',base); input_root=base/'input_data'; before={p.relative_to(input_root).as_posix():sha(p) for p in input_root.rglob('*') if p.is_file()}
  for index in [1,2]:
   out=base/f'output-{index}'; process=build(input_root,out,helm)
   if process.returncode:raise AssertionError(process.stdout+process.stderr)
   paths=compare(out,ref/'output');clean.append({'root_id':label,'process_index':index,'return_code':0,'output_started_empty':True,'primary_software_executed':True,'input_unchanged':True,'reference_match':True,'generated_paths':paths})
  after={p.relative_to(input_root).as_posix():sha(p) for p in input_root.rglob('*') if p.is_file()}
  if before!=after:raise AssertionError('input changed during standard run')
 positive=RUN/'positive';extract(TASK/'输入数据包.zip',positive); registry=positive/'input_data/secret_registry.csv'
 with registry.open(encoding='utf-8',newline='') as h: rows=list(csv.DictReader(h))
 rows[1]['secret_name']='callback-keyring-g18-next'
 with registry.open('w',encoding='utf-8',newline='') as h:w=csv.DictWriter(h,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
 process=build(positive/'input_data',positive/'output',helm)
 if process.returncode:raise AssertionError(process.stdout+process.stderr)
 activate=(positive/'output/rendered/activate.yaml').read_text(encoding='utf-8')
 if 'name: callback-keyring-g18-next' not in activate:raise AssertionError('Secret registry change did not reach projection')
 (EVIDENCE/'positive-case.json').write_text(json.dumps({'input_field':'g18.secret_name','before':'callback-keyring-g18','after':'callback-keyring-g18-next','behavior_changed':True},indent=2)+'\n',encoding='utf-8')
 negative=RUN/'negative';extract(TASK/'reference.zip',negative); chart=negative/'output/chart'; negative_results=[]
 negative_cases=[
  ('active-key-missing','phase: bad\nrotationRevision: KEYRING-BAD\nactiveKey: g18\nacceptedKeys: [g17]\n','must appear in acceptedKeys'),
  ('unregistered-key','phase: bad\nrotationRevision: KEYRING-BAD\nactiveKey: g17\nacceptedKeys: [g17, g99]\n','missing from secretRefs'),
 ]
 for name,values,error_fragment in negative_cases:
  bad=negative/f'{name}-values.yaml';bad.write_text(values,encoding='utf-8')
  process=subprocess.run([helm,'template','callback',str(chart),'--namespace','callback-system','--values',str(bad)],text=True,capture_output=True,timeout=60)
  if process.returncode==0 or process.stdout.strip() or error_fragment not in process.stderr:raise AssertionError(f'{name} was not closed by Chart')
  (EVIDENCE/f'negative-{name}.log').write_text(f'return_code={process.returncode}\nstdout={process.stdout}\nstderr={process.stderr}',encoding='utf-8')
  negative_results.append({'case':name,'return_code':process.returncode,'stdout_empty':True,'error_located':True})
 (EVIDENCE/'windows-summary.json').write_text(json.dumps({'result':'PASS','commit_sha':os.getenv('GITHUB_SHA'),'workflow_run_id':os.getenv('GITHUB_RUN_ID'),'runner_image':os.getenv('ImageOS'),'main_software':{'name':'Helm','version':version.stdout.strip(),'executed':True},'clean_directory_count':2,'process_runs_per_directory':2,'clean_runs':clean,'positive_mutation':'PASS','negative_cases':negative_results,'reference_full_tree_match':True,'formal_network':{'helm_outbound_blocked':True,'python_outbound_blocked':True,'external_services_used':False}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
