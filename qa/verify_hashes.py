from __future__ import annotations
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; TASK=ROOT/'task'; EVIDENCE=ROOT/'evidence'; EVIDENCE.mkdir(exist_ok=True)
expected=json.loads((ROOT/'qa/expected_hashes.json').read_text(encoding='utf-8'))
actual={name:hashlib.sha256((TASK/name).read_bytes()).hexdigest() for name in expected}
if actual!=expected: raise SystemExit(f'attachment hash mismatch: {actual}')
(EVIDENCE/'attachment-hashes.json').write_text(json.dumps({'result':'PASS','commit_sha':os.getenv('GITHUB_SHA'),'workflow_run_id':os.getenv('GITHUB_RUN_ID'),'attachment_sha256':actual},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
