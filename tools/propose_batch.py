#!/usr/bin/env python3
"""Read explicitly named root files and print a NON-AUTHORITATIVE proposal only."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.batch_lifecycle import transition,digest,stamp,iso
from tools.validate_execution_manifest import load_json
from scripts.select_batch import select
from datetime import timedelta

def propose(root,now_ist,owner):
    root=Path(root)
    manifest=load_json(root/"state/execution-manifest-20261011-ids021-040.json")
    roadmap=load_json(root/"roadmap-projects.json")
    historical=load_json(root/"state/completion-verifications.json")
    lease=load_json(root/"state/active-lease.json")
    preflight=load_json(root/"state/preflight-20261010-ids021-040.json")
    durable=load_json(root/"state/run-20261010-batch001-020.json")
    context={"roadmap":roadmap,"historicalCompletions":historical,"authoritativeEvidence":[],
        "plans":manifest["projects"],"manifest":manifest,"preflight":preflight,"durableReports":[durable]}
    selected=[p["id"] for p in select(roadmap,historical,20)]
    now=stamp(now_ist)
    request={"action":"begin","requestId":"dry-run-begin-"+now.strftime("%Y%m%d")+"-ids021-040",
        "nowIST":iso(now),"owner":owner,"expiresAtIST":iso(now+timedelta(hours=4)),
        "selectedIDs":selected,"selectorOutput":selected,
        "runReference":f"OMP-{selected[0]:03d}-{selected[-1]:03d}-{now.strftime('%Y%m%d')}",
        "expectedStateDigest":digest(lease),"expectedContextDigest":digest(context),"expectedRevision":0}
    output=transition(lease,context,request)
    return {"schemaVersion":1,"kind":"non_authoritative_batch_dry_run","planningOnly":True,
        "warning":"NOT an active lease. No Git, network, project or Gmail action was performed.",
        "inputStateDigest":digest(lease),"inputContextDigest":digest(context),"request":request,
        "proposal":output,"actualLeaseUnchanged":True}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--now-ist",required=True)
    parser.add_argument("--owner",required=True)
    args=parser.parse_args()
    print(json.dumps(propose(args.root,args.now_ist,args.owner),sort_keys=True))

if __name__=="__main__":main()
