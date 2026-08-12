from __future__ import annotations
import json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; WORK=ROOT/'work-reference'; EVIDENCE=ROOT/'evidence'
if WORK.exists(): shutil.rmtree(WORK)
WORK.mkdir(); EVIDENCE.mkdir(exist_ok=True)
with zipfile.ZipFile(ROOT/'task/输入数据包.zip') as package: package.extractall(WORK)
completed=subprocess.run([sys.executable,str(ROOT/'implementation/build_delivery.py'),'--input',str(WORK/'input_data'),'--output',str(WORK/'output'),'--helm',os.environ['HELM_PATH']],cwd=ROOT,text=True,capture_output=True,timeout=300)
if completed.returncode: raise SystemExit(completed.stdout+completed.stderr)
candidate=EVIDENCE/'reference-candidate.zip'
with zipfile.ZipFile(candidate,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
 for path in sorted((WORK/'output').rglob('*')):
  if path.is_file(): archive.write(path,path.relative_to(WORK).as_posix())
(EVIDENCE/'reference-generation.json').write_text(json.dumps({'result':'PASS','mode':'reference','commit_sha':os.getenv('GITHUB_SHA'),'workflow_run_id':os.getenv('GITHUB_RUN_ID'),'reference_members':sorted(p.relative_to(WORK).as_posix() for p in (WORK/'output').rglob('*') if p.is_file())},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
