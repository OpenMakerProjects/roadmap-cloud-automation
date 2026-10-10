#!/usr/bin/env python3
"""Pure JSON batch proposals. No clocks, randomness, network, Git or Gmail writes."""
import argparse
import copy
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.validate_execution_manifest import ValidationError,load_json,require,obj,same,text,unique_index
from tools.completion_evidence import validate as validate_evidence,aggregate as aggregate_evidence
from tools.daily_report import render,sent_index
from scripts.select_batch import select

IST=timezone(timedelta(hours=5,minutes=30))

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def stamp(value):
    text(value,"explicit timestamp")
    try:d=datetime.fromisoformat(value)
    except ValueError as exc:raise ValidationError("timestamp") from exc
    require(d.tzinfo is not None and d.utcoffset()==IST.utcoffset(None),"timestamp must be IST")
    return d

def iso(value):return value.isoformat()

def baseline(context):
    roadmap=context["roadmap"];rmap=unique_index(roadmap,"roadmap")
    same([p["id"] for p in roadmap],list(range(1,2201)),"roadmap ordered IDs1–2200")
    same(len({p["slug"] for p in roadmap}),2200,"unique roadmap slugs")
    legacy=context["historicalCompletions"];obj(legacy,"historicalCompletions")
    same(sorted(map(int,legacy)),list(range(1,21)),"preserved historical baseline IDs1–20")
    verified=set()
    for key,record in legacy.items():
        ident=int(key);same(key,str(ident),"historical key")
        require(record.get("status") in ("verified_complete","merged_verified"),"historical verified status")
        same(record.get("id"),ident,"historical ID")
        repo="https://github.com/OpenMakerProjects/"+rmap[ident]["slug"]
        same(record.get("repository"),repo,"historical repository")
        for flag in ("verifiedComplete","merged","requiredMainTreeVerified"):
            same(record.get(flag),True,"historical."+flag)
        audit=record.get("currentMainAudit");obj(audit,"historical main audit")
        for field,value in (("public",True),("prMerged",True),("sourceTestsCI",True),
                            ("requiredMainTreeVerified",True),("transportChunksRemaining",0),
                            ("repository",repo),("mainCommit",record.get("mainCommit"))):
            same(audit.get(field),value,"historical audit."+field)
        require(bool(re.fullmatch("[0-9a-f]{40}",str(record.get("mainCommit")))),"historical main SHA")
        require(bool(re.fullmatch("[0-9a-f]{40}",str(audit.get("imageGitBlob")))),"historical image")
        require(bool(record.get("tests")),"historical tests")
        verified.add(ident)
    return rmap,verified

def validated_ids(context,state):
    rmap,verified=baseline(context)
    plans=unique_index(context["plans"],"authoritative plans")
    records={}
    supplied=list(context.get("authoritativeEvidence",[]))
    if state and state.get("kind")=="batch_lifecycle_proposal":
        supplied += [v["evidence"] for v in state["results"].values() if v["status"]=="verified_complete"]
    for record in supplied:
        ident=record.get("identity",{}).get("id")
        require(ident in rmap and ident in plans and ident not in verified,"unsupported/conflicting evidence ID")
        validate_evidence(record,rmap[ident],plans[ident])
        if ident in records:same(record,records[ident],"conflicting reconciliation evidence")
        records[ident]=record
    assessed=aggregate_evidence(list(records.values()),context["roadmap"],context["plans"])
    same(assessed["invalidOrPending"],{},"invalid batch evidence aggregation")
    same(assessed["verifiedIDs"],sorted(records),"batch evidence counts")
    verified.update(records)
    return rmap,verified,plans,records

def totals(roadmap,verified):
    unfinished=[p["id"] for p in roadmap if p["id"] not in verified]
    return {"verifiedTotal":len(verified),"remainingTotal":len(unfinished),
            "nextStartingID":unfinished[0] if unfinished else None}

def coherent(state,context):
    if state is None:return
    obj(state,"prior state")
    if state.get("kind")!="batch_lifecycle_proposal":
        for key in ("owner","status","originalSelectedIDs","completedIDs","remainingIDs","activeProject","expiresAt"):
            require(key in state,"legacy lease missing "+key)
        original=state["originalSelectedIDs"];completed=state["completedIDs"];remaining=state["remainingIDs"]
        for ids in (original,completed,remaining):require(type(ids) is list and ids==sorted(set(ids)),"legacy ordered IDs")
        require(not set(completed)&set(remaining) and set(original)==set(completed)|set(remaining),"legacy partition")
        if state["status"]=="completed":
            same(remaining,[],"legacy completed remaining");same(state["activeProject"],None,"legacy completed active")
        _,verified,_,_=validated_ids(context,None)
        require(set(completed)<=verified,"legacy unverified completion")
        for key,value in totals(context["roadmap"],verified).items():same(state.get(key),value,"legacy totals."+key)
        return
    same(state.get("schemaVersion"),1,"state schema")
    same(state.get("nonAuthoritativePlanningOutput"),True,"proposal-only output")
    original=state["originalSelectedIDs"];completed=state["completedIDs"];remaining=state["remainingIDs"]
    for ids in (original,completed,remaining):
        require(type(ids) is list and ids==sorted(set(ids)),"state ordered unique IDs")
    require(not set(completed)&set(remaining) and set(original)==set(completed)|set(remaining),"state partition")
    results=state["results"];obj(results,"state.results")
    require(set(map(int,results))<=set(original),"result outside selection")
    expected_completed=sorted(int(k) for k,v in results.items() if v["status"]=="verified_complete")
    same(completed,expected_completed,"completed result arithmetic")
    for key,result in results.items():
        require(result["status"] in ("verified_complete","blocked","failed"),"terminal status")
        if result["status"]!="verified_complete":text(result.get("blocker"),"terminal blocker")
    active=state["activeProject"]
    if active is not None:
        require(active in remaining and str(active) not in results,"active project terminal/conflict")
        same(state["status"],"active","inactive lease has project")
    if state["status"]=="completed":
        same(remaining,[],"completed lease remaining")
        same(active,None,"completed active project")
    require(state["status"] in ("active","expired","completed"),"lease lifecycle")
    _,verified,_,_=validated_ids(context,state)
    same(state["totals"],totals(context["roadmap"],verified),"authoritative totals")
    same(state["completedIDs"],sorted(set(original)&verified),"completion not inferred")
    integer=state["revision"];require(type(integer) is int and integer>=1,"revision")

def plan_match(context,selected):
    same(context["manifest"]["selectedIDs"],selected,"manifest selected IDs")
    same(context["preflight"]["selectedIDs"],selected,"preflight selected IDs")
    plans=unique_index(context["manifest"]["projects"],"manifest projects")
    pf=unique_index(context["preflight"]["projects"],"preflight projects")
    supplied=unique_index(context["plans"],"supplied plans")
    rmap=unique_index(context["roadmap"],"roadmap")
    for ident in selected:
        require(ident in supplied,"missing supplied plan")
        same(supplied[ident],plans[ident],"supplied/manifest plan drift")
        for field in ("id","title","slug","category","platform","connectivity","components","scope"):
            same(plans[ident].get(field),rmap[ident][field],"roadmap/plan "+field)
        same(plans[ident].get("keyDeliverable"),rmap[ident]["deliverable"],"roadmap deliverable")
        require(ident in plans and ident in pf,"missing selected plan/preflight")
        same(plans[ident]["currentMainSHA"],pf[ident]["mainHead"],"plan/preflight SHA")
        same(plans[ident]["existingEntrypoint"],pf[ident]["entrypoint"],"plan/preflight entrypoint")

def report_ledger(state,context,now):
    rmap,verified,_,_=validated_ids(context,state)
    rows=[];audits=[];errors=[]
    for ident in state["originalSelectedIDs"]:
        result=state["results"][str(ident)]
        repo="https://github.com/OpenMakerProjects/"+rmap[ident]["slug"]
        if result["status"]=="verified_complete":
            evidence=result["evidence"];main=evidence["main"]
            rows.append({"id":ident,"repository":repo,"pr":evidence["pr"]["url"],
                "status":"verified_complete","mainCommit":main["commit"],"headCommit":evidence["finalHead"],
                "tests":{"host":evidence["validation"]["host"],"target":evidence["validation"]["target"]},
                "hardwareTesting":{"status":evidence["hardware"]["status"],"evidence":json.dumps(evidence["hardware"]["evidence"],sort_keys=True) if evidence["hardware"]["status"]=="performed" else None}})
            audits.append({"id":ident,"repository":repo,"pr":evidence["pr"]["url"],"mainCommit":main["commit"],
                "public":True,"prMerged":True,"requiredMainTreeVerified":True,"sourceTestsCI":True,
                "transportChunksRemaining":0,"imageGitBlob":evidence["assets"]["image"]["gitBlob"]})
        else:
            rows.append({"id":ident,"repository":repo,"status":result["status"],"blocker":result["blocker"],
                         "hardwareTesting":{"status":"not_performed"}})
            errors.append({"id":ident,"resolved":False,"detail":result["blocker"]})
    t=totals(context["roadmap"],verified)
    success=len(state["completedIDs"])
    ref=state["runReference"];day=ref.rsplit("-",1)[-1]
    day=day[:4]+"-"+day[4:6]+"-"+day[6:]
    return {"runId":ref,"status":"completed" if success==len(rows) else ("failed" if not success else "partial"),
        "timestampIST":day+"T04:00:00+05:30","cloudOnly":True,"selectedIDs":state["originalSelectedIDs"],
        "attemptedIDs":state["originalSelectedIDs"],"projects":rows,"finalMainAudit":audits,"errors":errors,
        "unresolvedBlockers":[e["detail"] for e in errors],
        "totals":{"roadmap":len(context["roadmap"]),"verifiedComplete":t["verifiedTotal"],
                  "remainingToVerifyAndComplete":t["remainingTotal"],"nextStartingID":t["nextStartingID"]},
        "gmail":{"status":"pending","reportReference":ref,"subject":"OpenMakerProjects daily build report - "+day,
                 "to":"me","resolvedProfile":"balwanshrutik@gmail.com","cc":[],"bcc":[]}}

def transition(state,context,request):
    obj(context,"context");obj(request,"request")
    request_id=request.get("requestId");text(request_id,"requestId")
    now=stamp(request.get("nowIST"));action=request.get("action")
    request_hash=digest(request);prior_hash=digest(state);context_hash=digest(context)
    if state and state.get("kind")=="batch_lifecycle_proposal":
        for event in state["history"]:
            if event.get("requestId")==request_id:
                same(event["requestDigest"],request_hash,"retry payload changed")
                same(event["contextDigest"],context_hash,"retry context changed")
                return {"state":copy.deepcopy(state),"stateDigest":prior_hash,"replayed":True,
                        "nonAuthoritativePlanningOutput":True}
    same(request.get("expectedStateDigest"),prior_hash,"stale prior digest")
    same(request.get("expectedContextDigest"),context_hash,"stale context digest")
    revision=state.get("revision",0) if state else 0
    same(request.get("expectedRevision"),revision,"stale revision")
    coherent(state,context)
    if state and state.get("kind")=="batch_lifecycle_proposal" and state["history"]:
        require(now>=stamp(state["history"][-1]["timestampIST"]),"timestamp regression")
    rmap,verified,plans,_=validated_ids(context,state)
    old_totals=totals(context["roadmap"],verified)
    out=copy.deepcopy(state)
    if action=="begin":
        owner=request.get("owner");text(owner,"unique owner")
        prior_owners=set()
        def owners(node):
            if type(node) is dict:
                if type(node.get("owner")) is str:prior_owners.add(node["owner"])
                for value in node.values():owners(value)
            elif type(node) is list:
                for value in node:owners(value)
        owners(state)
        require(owner not in prior_owners,"owner must be unique across history")
        require(type(owner) is str and bool(re.fullmatch("[A-Za-z0-9-]+",owner)),"owner format")
        expires=stamp(request.get("expiresAtIST"));require(now<expires<=now+timedelta(hours=12),"bounded lease expiry")
        if state:
            status=state.get("status")
            require(status in ("completed","expired","active"),"begin lifecycle")
            if status in ("active","expired"):
                expiration=datetime.fromisoformat(state["expiresAt"])
                require(expiration.tzinfo is not None and expiration<=now,"unexpired lease")
            if state.get("report") and state["report"].get("status")!="sent":
                raise ValidationError("unresolved report intent blocks new begin")
        resuming=bool(state and state.get("kind")=="batch_lifecycle_proposal" and
                      state["status"] in ("active","expired") and not state.get("releasedAtIST"))
        selected=request.get("selectedIDs")
        effective={str(i):{"status":"verified_complete"} for i in verified}
        first=[p["id"] for p in select(context["roadmap"],effective,20)]
        same(request.get("selectorOutput"),first,"selector output first unfinished")
        if resuming:
            same(selected,state["originalSelectedIDs"],"takeover preserves interrupted selection")
            unfinished=[i for i in selected if i not in verified]
            same(unfinished,first[:len(unfinished)],"takeover cannot skip lower unfinished")
            out=copy.deepcopy(state);out["previousOwner"]=state["owner"]
            out["owner"]=owner;out["activeProject"]=None
        else:
            same(selected,first,"selected IDs first unfinished")
            require(type(selected) is list and 1<=len(selected)<=20 and selected==sorted(set(selected)),"selection max20/order")
            plan_match(context,selected)
            ref=request.get("runReference")
            same(ref,f"OMP-{selected[0]:03d}-{selected[-1]:03d}-{now.strftime('%Y%m%d')}","stable run reference")
            sent,pending=sent_index([context.get("durableReports",[]),state])
            require(ref not in sent and ref not in pending,"report reference already used/unresolved")
            out={"schemaVersion":1,"kind":"batch_lifecycle_proposal","nonAuthoritativePlanningOutput":True,
                "owner":owner,"runReference":ref,"originalSelectedIDs":selected,"completedIDs":[],
                "remainingIDs":selected[:],"activeProject":None,"results":{},"report":None,
                "history":[],"previousStateSnapshot":copy.deepcopy(state)}
        out.update(status="active",acquiredAtIST=iso(now),expiresAt=iso(expires),totals=old_totals)
    else:
        require(state is not None and state.get("kind")=="batch_lifecycle_proposal","explicit proposal state required")
        same(request.get("owner"),state["owner"],"lease owner")
        if action in ("activate","checkpoint","report-intent"):
            same(state["status"],"active","active lease required")
            require(datetime.fromisoformat(state["expiresAt"])>now,"expired lease needs takeover")
        if action=="activate":
            same(state["activeProject"],None,"only one active project")
            available=[i for i in state["remainingIDs"] if str(i) not in state["results"]]
            require(bool(available),"no pending project")
            same(request.get("projectID"),available[0],"ascending active project")
            out["activeProject"]=available[0]
        elif action=="checkpoint":
            ident=request.get("projectID")
            same(ident,state["activeProject"],"checkpoint exactly active project")
            require(str(ident) not in state["results"],"duplicate completion")
            status=request.get("status")
            if status=="verified_complete":
                evidence=request.get("evidence")
                require(ident in plans,"missing project plan")
                validate_evidence(evidence,rmap[ident],plans[ident])
                same(evidence["runReference"],state["runReference"],"evidence planned run")
                require(stamp(evidence["result"]["timestampIST"])<=now,"completion evidence from future")
                out["results"][str(ident)]={"status":status,"evidence":copy.deepcopy(evidence),"timestampIST":iso(now)}
                out["completedIDs"]=sorted(out["completedIDs"]+[ident])
                out["remainingIDs"].remove(ident)
            else:
                require(status in ("failed","blocked"),"terminal failure status")
                text(request.get("blocker"),"blocker required")
                out["results"][str(ident)]={"status":status,"blocker":request["blocker"],"timestampIST":iso(now)}
            out["activeProject"]=None
            _,new_verified,_,_=validated_ids(context,out)
            require(verified<=new_verified,"verified counts cannot regress")
            out["totals"]=totals(context["roadmap"],new_verified)
        elif action=="report-intent":
            same(state["activeProject"],None,"active project before report")
            same(set(map(int,state["results"])),set(state["originalSelectedIDs"]),"all selected IDs terminal")
            same(state["report"],None,"duplicate/unresolved report intent")
            ledger=report_ledger(state,context,now);prepared=render(ledger,context["roadmap"])
            sent,pending=sent_index(context.get("durableReports",[]))
            require(prepared["reportReference"] not in sent and prepared["reportReference"] not in pending,"existing report delivery/intent")
            out["report"]={"status":"prepared","reportReference":prepared["reportReference"],
                "idempotencyKey":prepared["idempotencyKey"],"htmlSha256":prepared["htmlSha256"],
                "subject":prepared["subject"],"to":"me","resolvedProfile":prepared["resolvedProfile"],
                "cc":[],"bcc":[],"succeededCount":prepared["succeededCount"],
                "html":prepared["html"],"ledger":ledger,"intentAtIST":iso(now)}
        elif action=="reconcile-sent":
            require(state.get("report") is not None,"missing intent")
            receipt=request.get("receipt");obj(receipt,"receipt")
            report=state["report"]
            for key in ("reportReference","htmlSha256","subject","to","resolvedProfile","cc","bcc"):
                same(receipt.get(key),report[key],"receipt."+key)
            same(receipt.get("status"),"sent","sent receipt")
            require("SENT" in receipt.get("labelIds",[]),"SENT reconciliation evidence")
            require(type(receipt.get("messageId")) is str and bool(re.fullmatch("[0-9a-f]+",receipt["messageId"])),"message ID")
            require(stamp(report["intentAtIST"])<=stamp(receipt.get("sentAtIST"))<=now,"receipt time outside intent/current time")
            sent,_=sent_index(context.get("durableReports",[]))
            if report["reportReference"] in sent:same(sent[report["reportReference"]],{receipt["messageId"]},"conflicting sent message")
            if report["status"]=="sent":same(report["receipt"],receipt,"second receipt differs")
            else:out["report"].update(status="sent",messageId=receipt["messageId"],receipt=copy.deepcopy(receipt))
            if "deliveryPending" in out:out["deliveryPending"]=False
        elif action=="release":
            same(state["activeProject"],None,"release active project")
            same(set(map(int,state["results"])),set(state["originalSelectedIDs"]),"release before all terminal")
            report=state.get("report");obj(report,"release report")
            rendered=render(report["ledger"],context["roadmap"])
            same(rendered["htmlSha256"],report["htmlSha256"],"report integrity")
            same(rendered["html"],report["html"],"report HTML integrity")
            same(report["ledger"],report_ledger(state,context,now),"report totals/evidence stale")
            if request.get("path")=="zero_success_failure_report":
                same(len(state["completedIDs"]),0,"failure path must have zero successes")
                same(rendered["succeededCount"],0,"validated failure report")
                require(report["status"] in ("prepared","sent"),"valid failure intent")
            else:same(report["status"],"sent","release requires reconciled sent receipt")
            out["activeProject"]=None;out["releasedAtIST"]=iso(now);out["expiresAt"]=iso(now)
            out["status"]="completed" if not state["remainingIDs"] else "expired"
            out["deliveryPending"]=report["status"]!="sent"
        else:raise ValidationError("unknown transition")
    require(out["totals"]["verifiedTotal"]>=old_totals["verifiedTotal"],"count regression")
    out["revision"]=revision+1
    out.setdefault("history",[]).append({"requestId":request_id,"requestDigest":request_hash,
        "contextDigest":context_hash,"priorStateDigest":prior_hash,"priorRevision":revision,
        "action":action,"owner":request.get("owner"),"timestampIST":iso(now)})
    coherent(out,context)
    return {"state":out,"stateDigest":digest(out),"replayed":False,"nonAuthoritativePlanningOutput":True}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True,help="JSON containing state/context/request")
    args=parser.parse_args()
    try:
        data=load_json(args.input)
        print(json.dumps(transition(data["state"],data["context"],data["request"]),sort_keys=True))
    except (ValidationError,OSError,ValueError,TypeError,KeyError) as exc:
        parser.exit(1,"INVALID BATCH TRANSITION: "+str(exc)+"\n")

if __name__=="__main__":main()
