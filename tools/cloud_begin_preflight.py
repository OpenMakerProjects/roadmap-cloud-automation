#!/usr/bin/env python3
import base64,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.batch_lifecycle import transition,digest
from tools.control_persistence import prepare,READ_PATHS,LEASE,blob_sha

base=os.environ["BASE_SHA"]
def git(*args):
    return subprocess.check_output(["git",*args],text=True).strip()
def read_at(path):
    return subprocess.check_output(["git","show",f"{base}:{path}"]).decode("utf-8")
def parsed(path):
    import csv,io
    content=read_at(path)
    return list(csv.DictReader(io.StringIO(content),strict=True)) if path.endswith(".csv") else json.loads(content)

state=parsed(LEASE)
roadmap=parsed("roadmap-projects.json")
manifest=parsed("state/execution-manifest-20261011-ids021-040.json")
context={
  "roadmap":roadmap,
  "historicalCompletions":parsed("state/completion-verifications.json"),
  "manifest":manifest,
  "preflight":parsed("state/preflight-20261010-ids021-040.json"),
  "plans":manifest["projects"],
  "durableReports":[parsed("state/run-20261010-batch001-020.json")],
  "authoritativeEvidence":[]
}
selected=list(range(21,41))
request={
  "action":"begin",
  "expectedStateDigest":digest(state),
  "expectedContextDigest":digest(context),
  "expectedRevision":0,
  "nowIST":os.environ["NOW_IST"],
  "expiresAtIST":os.environ["EXPIRES_IST"],
  "owner":os.environ["LEASE_OWNER"],
  "requestId":os.environ["REQUEST_ID"],
  "runReference":os.environ["RUN_REFERENCE"],
  "selectedIDs":selected,
  "selectorOutput":selected
}
result=transition(state,context,request)
content=json.dumps(result["state"],indent=2,ensure_ascii=False)+"\n"
old_content=read_at(LEASE)
old_sha=git("rev-parse",f"{base}:{LEASE}")
change={
  "path":LEASE,
  "expectedBlobSHA":old_sha,
  "expectedDigest":digest(state),
  "expectedRevision":0,
  "content":content
}
operation={
  "schemaVersion":1,"owner":"OpenMakerProjects","repo":"roadmap-cloud-automation","branch":"main",
  "expectedMainSHA":base,
  "message":"Begin cloud batch IDs 021-040 for 2026-10-12",
  "transition":{"state":state,"context":context,"request":request},
  "changes":[change]
}
paths=set(READ_PATHS)|{LEASE}
files={}
for path in paths:
    raw=read_at(path)
    entry=git("ls-tree",base,"--",path).split()
    files[path]={"sha":entry[2],"mode":entry[0],"content":raw}
snapshot={"owner":"OpenMakerProjects","repo":"roadmap-cloud-automation","branch":"main",
          "refSHA":base,"treeSHA":git("show","-s","--format=%T",base),"files":files}
plan=prepare(operation,snapshot)
payload={"result":result,"operation":operation,"plan":plan}
encoded=base64.b64encode(json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode()).decode()
print("BEGIN_RESULT_B64="+encoded)
