#!/usr/bin/env python3
"""Control-only CAS operation plans. No built-in network, credentials or Git writes."""
import argparse
import base64
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.batch_lifecycle import transition,digest,coherent
from tools.completion_evidence import validate as validate_evidence
from tools.daily_report import render,clean
from tools.validate_control_state import validate_state
from tools.validate_execution_manifest import validate as validate_manifest,ValidationError,require,same,load_json

OWNER="OpenMakerProjects"
REPO="roadmap-cloud-automation"
BRANCH="main"
LOGIN="shrutikbalwan"
MAX_BYTES=2_000_000
MAX_TOTAL=8_000_000
LEASE="state/active-lease.json"
MANIFEST="state/execution-manifest-20261011-ids021-040.json"
PREFLIGHT="state/preflight-20261010-ids021-040.json"
QA="state/execution-manifest-20261011-ids021-040-qa.json"
BATCH="state/run-20261010-batch001-020.json"
READ_PATHS=("roadmap-projects.json","state/completion-verifications.json",MANIFEST,PREFLIGHT,QA,BATCH,
    "state/scheduler-readback-20261010.json","state/cloud-schedule-setup-20261006.json","state/daily-results.csv",
    "state/batch-proposal-20261011-ids021-040.json")
PATTERN=re.compile(r"state/(?:run-[0-9]{8}-batch[0-9]{3,4}-[0-9]{3,4}|recovery-[0-9]{8}-id[0-9]{3,4}|report-intent-[A-Za-z0-9-]{1,80}|completion-evidence/id[0-9]{3,4})\.json")
MUTATION="""mutation ControlStateCAS($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit { oid parents(first: 2) { nodes { oid } } }
    ref { target { oid } }
  }
}"""

def sha(value):
    require(type(value) is str and bool(re.fullmatch("[0-9a-f]{40}",value)),"invalid SHA")

def path_ok(path):
    require(type(path) is str and (path==LEASE or bool(PATTERN.fullmatch(path))),"path outside control-state allowlist")
    require(".." not in path and "\\" not in path and "%" not in path,"unsafe path")

def parse(content):
    require(type(content) is str,"UTF-8 text required")
    try:raw=content.encode("utf-8",errors="strict")
    except UnicodeError:raise ValidationError("invalid UTF-8")
    require(len(raw)<=MAX_BYTES and "\x00" not in content,"binary/oversize content")
    def pairs(items):
        out={}
        for key,value in items:
            require(key not in out,"duplicate JSON key")
            out[key]=value
        return out
    try:
        value=json.loads(content,object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValidationError("non-finite JSON")))
    except (ValueError,RecursionError):raise ValidationError("unparseable JSON")
    require(type(value) in (dict,list),"state must be object/array")
    clean(value)
    def secret_keys(node):
        if type(node) is dict:
            for key,item in node.items():
                require(key.lower() not in {"token","secret","client_secret","credentials","credential","passwd"},"credential field")
                secret_keys(item)
        elif type(node) is list:
            for item in node:secret_keys(item)
    secret_keys(value)
    require(not re.search(r"(?:AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{20,}|[?&](?:token|access_token|sig|signature)=)",content,re.I),"credential pattern")
    return value

def blob_sha(content):
    raw=content.encode("utf-8")
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

def read_file(snapshot,path,allow_absent=False):
    files=snapshot["files"]
    item=files.get(path)
    if item is None:
        require(allow_absent,"missing snapshot file");return None
    # Reject symlink ancestors as well as symlink/submodule target modes.
    ancestors=["/".join(path.split("/")[:i]) for i in range(1,len(path.split("/")))]
    for ancestor in ancestors:
        if ancestor in files:same(files[ancestor].get("mode"),"040000","unsafe ancestor mode")
    same(item.get("mode"),"100644","symlink/executable/non-blob rejected")
    sha(item.get("sha"));same(blob_sha(item["content"]),item["sha"],"snapshot blob hash mismatch")
    return item

def validate_inputs(data,snapshot):
    same({k:data.get(k) for k in ("owner","repo","branch")},
         {"owner":OWNER,"repo":REPO,"branch":BRANCH},"scope")
    same(set(data),{"schemaVersion","owner","repo","branch","expectedMainSHA","message","transition","changes"},"operation fields")
    same(data["schemaVersion"],1,"operation schema")
    same(snapshot.get("owner"),OWNER,"snapshot owner")
    same(snapshot.get("repo"),REPO,"snapshot repo")
    same(snapshot.get("branch"),BRANCH,"snapshot branch")
    sha(data["expectedMainSHA"]);same(snapshot.get("refSHA"),data["expectedMainSHA"],"stale main ref")
    sha(snapshot.get("treeSHA"))
    require(type(data["message"]) is str and 1<=len(data["message"])<=200 and "\n" not in data["message"],"commit message")
    clean(data["message"])
    bundle=data["transition"];same(set(bundle),{"state","context","request"},"transition input fields")
    context=bundle["context"]
    observed={}
    for path in READ_PATHS:
        item=read_file(snapshot,path)
        observed[path]=list(csv.DictReader(io.StringIO(item["content"]),strict=True)) if path.endswith(".csv") else parse(item["content"])
    for key,path in (("roadmap","roadmap-projects.json"),("historicalCompletions","state/completion-verifications.json"),
                     ("manifest",MANIFEST),("preflight",PREFLIGHT)):
        same(context[key],observed[path],"context differs from fresh main snapshot")
    same(context["plans"],observed[MANIFEST]["projects"],"plans drift")
    same(context["durableReports"],[observed[BATCH]],"durable report sources")
    # Every extra v1 completion must be backed by a current control-tree file.
    for evidence in context["authoritativeEvidence"]:
        ident=evidence["identity"]["id"];path=f"state/completion-evidence/id{ident:03d}.json"
        same(parse(read_file(snapshot,path)["content"]),evidence,"authoritative evidence source")
    prior_file=read_file(snapshot,LEASE,allow_absent=True)
    prior=parse(prior_file["content"]) if prior_file else None
    same(bundle["state"],prior,"prior lease differs from fresh main")
    validate_manifest(observed[MANIFEST],observed[QA],observed["roadmap-projects.json"],observed[PREFLIGHT])
    # Current frozen historical checkpoint; future proposal state uses lifecycle/evidence gates.
    historic=prior
    while historic and historic.get("kind")=="batch_lifecycle_proposal":
        historic=historic.get("previousStateSnapshot")
    if historic is None:
        historic=observed["state/batch-proposal-20261011-ids021-040.json"]["proposal"]["state"]["previousStateSnapshot"]
        require(historic is not None and historic.get("status")=="completed","absent validated historical baseline")
    validate_state(context["roadmap"],context["historicalCompletions"],historic,
        observed[BATCH],observed["state/scheduler-readback-20261010.json"],
        observed["state/cloud-schedule-setup-20261006.json"],observed["state/daily-results.csv"])
    output=transition(prior,context,bundle["request"])
    require(not output["replayed"],"already persisted transition; reconcile without another commit")
    proposed=output["state"];coherent(proposed,context)
    changes=data["changes"]
    require(type(changes) is list and 1<=len(changes)<=24,"bounded nonempty changes")
    require(len({c["path"] for c in changes})==len(changes),"duplicate changed path")
    require(any(c["path"]==LEASE for c in changes),"atomic transition must include lease")
    validated=[];size=0
    rmap={e["id"]:e for e in context["roadmap"]};plans={p["id"]:p for p in context["plans"]}
    for change in changes:
        same(set(change),{"path","expectedBlobSHA","expectedDigest","expectedRevision","content"},"change fields")
        path=change["path"];path_ok(path)
        old=read_file(snapshot,path,allow_absent=True)
        if old:
            sha(change["expectedBlobSHA"]);same(old["sha"],change["expectedBlobSHA"],"stale target blob")
            old_value=parse(old["content"])
        else:
            same(change["expectedBlobSHA"],None,"absence must be explicit");old_value=None
        same(change["expectedDigest"],digest(old_value),"stale canonical digest")
        same(change["expectedRevision"],old_value.get("revision",0) if type(old_value) is dict else 0,"stale revision")
        new=parse(change["content"]);size+=len(change["content"].encode())
        if path==LEASE:same(new,proposed,"lease differs from validated transition")
        elif "/completion-evidence/" in path or "/recovery-" in path:
            ident=new.get("identity",{}).get("id")
            require(ident in plans,"missing evidence plan")
            validate_evidence(new,rmap[ident],plans[ident])
            suffix=f"id{ident:03d}.json"
            require(path.endswith(suffix),"evidence filename identity")
            same(new,proposed["results"][str(ident)]["evidence"],"evidence not in transition")
            if old:same(new,old_value,"historical evidence immutable")
        elif "/run-" in path:
            require(proposed.get("report") is not None,"ledger before report intent")
            same(new,proposed["report"]["ledger"],"ledger differs from transition")
            render(new,context["roadmap"])
            require(path==f"state/run-{new['timestampIST'][:10].replace('-','')}-batch{new['selectedIDs'][0]:03d}-{new['selectedIDs'][-1]:03d}.json","ledger filename identity")
            if old:same(new,old_value,"historical ledger immutable")
        else:
            same(new,proposed.get("report"),"report-intent differs from transition")
            require(new is not None,"missing report intent")
            same(path,"state/report-intent-"+new["reportReference"]+".json","intent filename identity")
            rendered=render(new["ledger"],context["roadmap"])
            same(new["htmlSha256"],rendered["htmlSha256"],"report hash")
            if old:
                same(new["reportReference"],old_value["reportReference"],"intent identity")
                require(old_value["status"]=="prepared" and new["status"]=="sent","intent append-only receipt")
        validated.append({"path":path,"content":change["content"],"blobSHA":blob_sha(change["content"])})
    require(size<=MAX_TOTAL,"total content too large")
    return output,validated

def prepare(data,snapshot):
    output,changes=validate_inputs(data,snapshot)
    graphql={"branch":{"repositoryNameWithOwner":OWNER+"/"+REPO,"refName":BRANCH},
        "expectedHeadOid":data["expectedMainSHA"],"message":{"headline":data["message"]},
        "clientMutationId":digest(data),"fileChanges":{"additions":[
            {"path":c["path"],"contents":base64.b64encode(c["content"].encode()).decode()} for c in changes]}}
    return {"schemaVersion":1,"kind":"control_state_cas_plan","dryRun":True,
        "expectedMainSHA":data["expectedMainSHA"],"stateDigest":output["stateDigest"],
        "account":LOGIN,"authorOverride":False,"force":False,"deletions":[],
        "baseTreeSHA":snapshot["treeSHA"],"changes":changes,
        "gitDataPlan":["read fresh main ref","read base commit/tree","validate target blobs/modes/digests/revisions",
            "create UTF-8 blobs","create tree with base_tree preserving unrelated paths",
            "create single commit with exactly expected main as parent; omit author/committer overrides",
            "conditional ref update ONLY with server-side expected-old-SHA; force=false",
            "read ref/commit/files back; compare bytes/blob hashes and parent"],
        "restRefUpdateHasExpectedOldSHA":False,
        "atomicConnectorOperation":{"query":MUTATION,"variables":{"input":graphql}},
        "readbackRequired":True,"mutationRetryAllowed":False}

def execute(data,adapter,*,apply=False,protected_runtime=False):
    # Adapter owns authentication; no token is an input, output, log or persisted source.
    try:
        snapshot=adapter.snapshot(OWNER,REPO,BRANCH)
        plan=prepare(data,snapshot)
        if not apply:return plan
        require(protected_runtime is True,"explicit protected runtime required")
        same(adapter.authenticated_login(),LOGIN,"authenticated account")
        same(adapter.atomic_expected_head_supported,True,"atomic CAS capability unavailable")
        # Refresh and revalidate every input immediately before the single mutation.
        plan=prepare(data,adapter.snapshot(OWNER,REPO,BRANCH))
        result=adapter.atomic_commit(plan["atomicConnectorOperation"])
        commit=result["commitSHA"];sha(commit)
        same(result["parents"],[data["expectedMainSHA"]],"non-fast-forward/unexpected parent")
        same(result["refSHA"],commit,"mutation ref mismatch")
        after=adapter.snapshot(OWNER,REPO,BRANCH)
        same(after["refSHA"],commit,"post-write ref mismatch: reconciliation required")
        for change in plan["changes"]:
            item=read_file(after,change["path"])
            same(item["sha"],change["blobSHA"],"post-write blob mismatch: reconciliation required")
            same(item["content"],change["content"],"post-write content mismatch: reconciliation required")
        return {"applied":True,"commitSHA":commit,"readbackVerified":True,
            "stateDigest":plan["stateDigest"],"mutationRetryAllowed":False}
    except Exception:
        # Do not reflect transport errors/URLs/request headers/tokens.
        raise ValidationError("control persistence refused or delivery uncertain; read-only reconciliation required; no mutation retry") from None

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True,help="Explicit operation plus fresh snapshot JSON")
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    try:
        require(not args.apply,"CLI has no authenticated CAS adapter; --apply refuses before reading input")
        require(not args.input.is_symlink(),"symlink input")
        require(args.input.stat().st_size<=16_000_000,"oversize input envelope")
        bundle=load_json(args.input)
        print(json.dumps(prepare(bundle["operation"],bundle["snapshot"]),sort_keys=True))
    except Exception:
        parser.exit(1,"INVALID CONTROL PERSISTENCE PLAN; no write performed\n")

if __name__=="__main__":main()
