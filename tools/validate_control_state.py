#!/usr/bin/env python3
"""Offline validation of the completed IDs1–20 checkpoint and IDs21–40 plan.
This snapshot gate intentionally needs an explicit update when the batch advances.
Historical CSV rows are append-only; repeated references to one message are not sends.
"""
import argparse
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.select_batch import select
from tools.validate_execution_manifest import (ValidationError, load_json, require,
    same, obj, text, unique_index, validate_files as validate_manifest)

BATCH = "state/run-20261010-batch001-020.json"
COMPLETE = {"verified_complete", "merged_verified"}
NONCOMPLETE = {"pending", "blocked", "failed", "in_progress", "not_verified"}
DONE = list(range(1,21))
NEXT = list(range(21,41))

def sha(value, path):
    require(type(value) is str and bool(re.fullmatch("[0-9a-f]{40}", value)), path)

def date(value, path):
    text(value, path)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(path) from exc
    require(parsed.tzinfo is not None, path + ".timezone")
    return parsed

def ids(value, path):
    require(type(value) is list and all(type(i) is int and 1 <= i <= 2200 for i in value), path)
    require(len(set(value)) == len(value) and value == sorted(value), path + ".uniqueOrdered")
    return set(value)

def mail(value, path, explicit_recipients=False):
    obj(value, path)
    same(value.get("status"), "sent", path + ".status")
    same(value.get("to"), "me", path + ".to")
    recipient = value.get("resolvedProfile", value.get("resolvedRecipient"))
    same(recipient, "balwanshrutik@gmail.com", path + ".profile")
    for field in ("cc", "bcc"):
        if explicit_recipients or field in value:
            same(value.get(field), [], path + "." + field)
    ident = value.get("messageId")
    require(type(ident) is str and bool(re.fullmatch("[0-9a-f]+",ident)), path + ".messageId")
    text(value.get("reportReference"), path + ".reportReference")
    date(value.get("sentAtIST"), path + ".sentAtIST")
    return ident

def validate_state(roadmap, completion, lease, batch, scheduler, setup, rows, selector=select):
    rmap = unique_index(roadmap, "roadmap")
    same([p["id"] for p in roadmap], list(range(1,2201)), "roadmap.IDs1–2200")
    slugs = []
    for p in roadmap:
        slug = p.get("slug")
        require(type(slug) is str and bool(re.fullmatch("[a-z0-9]+(?:-[a-z0-9]+)*",slug)), "roadmap.slug")
        slugs.append(slug)
    same(len(set(slugs)),2200,"roadmap.uniqueSlugs")
    obj(completion,"completion")
    verified = set()
    for key, record in completion.items():
        require(type(key) is str and key.isdigit() and str(int(key)) == key and int(key) in rmap,"completion.key")
        obj(record,"completion." + key)
        same(record.get("id"),int(key),"completion.id")
        require(record.get("status") in COMPLETE | NONCOMPLETE,"completion.status")
        if record["status"] not in COMPLETE:
            require(record.get("verifiedComplete") is not True,"completion.unverifiedFlag")
            continue
        verified.add(int(key))
        for field in ("verifiedComplete","merged","requiredMainTreeVerified"):
            same(record.get(field),True,"completion." + key + "." + field)
        repo = "https://github.com/OpenMakerProjects/" + rmap[int(key)]["slug"]
        same(record.get("repository"),repo,"completion.repository")
        require(type(record.get("pr")) is str and bool(re.fullmatch(re.escape(repo)+r"/pull/[1-9][0-9]*",record["pr"])),"completion.pr")
        sha(record.get("mainCommit"),"completion.mainCommit")
        sha(record.get("headCommit"),"completion.headCommit")
        require(type(record.get("tests")) in (dict,str) and bool(record["tests"]),"completion.tests")
        audit = record.get("currentMainAudit"); obj(audit,"completion.currentMainAudit")
        for field, expected in (("id",int(key)),("repository",repo),("mainCommit",record["mainCommit"]),
                                ("pr",record["pr"]),("public",True),("prMerged",True),
                                ("requiredMainTreeVerified",True),("sourceTestsCI",True),
                                ("transportChunksRemaining",0)):
            same(audit.get(field),expected,"completion.audit." + field)
        sha(audit.get("mergeCommit"),"completion.audit.mergeCommit")
        sha(audit.get("imageGitBlob"),"completion.audit.imageGitBlob")
        date(audit.get("timestampIST"),"completion.audit.timestamp")
    same(sorted(verified),DONE,"checkpoint.verifiedIDs")
    obj(lease,"lease")
    original = ids(lease.get("originalSelectedIDs"),"lease.original")
    completed = ids(lease.get("completedIDs"),"lease.completed")
    remaining = ids(lease.get("remainingIDs"),"lease.remaining")
    require(not completed & remaining and original == completed | remaining,"lease.partition")
    same(sorted(original),DONE,"lease.originalBatch")
    require(completed <= verified and not remaining & verified,"lease.completionConsistency")
    require(lease.get("status") in ("active","completed","expired","released","blocked"),"lease.lifecycle")
    active = lease.get("activeProject")
    if lease["status"] == "active":
        require(active is None or (type(active) is int and active in remaining),"lease.activeProject")
        require(bool(remaining),"lease.activeRemaining")
        require(date(lease.get("expiresAt"),"lease.expiresAt") > date(lease.get("acquiredAtIST"),"lease.acquired"),"lease.expiry")
    else:
        same(active,None,"lease.inactiveProject")
    if lease["status"] == "completed":
        same(sorted(remaining),[],"lease.completedRemaining")
        same(completed,original,"lease.completedOriginal")
        date(lease.get("releasedAtIST"),"lease.released")
    same(lease.get("status"),"completed","checkpoint.leaseCompleted")
    next_id = next((i for i in range(1,2201) if i not in verified),None)
    for key, value in (("verifiedTotal",len(verified)),("remainingTotal",2200-len(verified)),("nextStartingID",next_id)):
        same(lease.get(key),value,"lease." + key)
    obj(batch,"batch")
    same(batch.get("status"),"completed","batch.status")
    same(batch.get("cloudOnly"),True,"batch.cloudOnly")
    same(batch.get("selectedIDs"),DONE,"batch.selected")
    same(batch.get("attemptedIDs"),DONE,"batch.attempted")
    same(batch.get("leaseStatus"),"completed","batch.leaseStatus")
    same(batch.get("leaseOwner"),lease.get("owner"),"batch.leaseOwner")
    totals=batch.get("totals"); obj(totals,"batch.totals")
    for key,value in (("roadmap",2200),("verifiedComplete",20),("remainingToVerifyAndComplete",2180),("nextStartingID",21)):
        same(totals.get(key),value,"batch.totals." + key)
    projects=unique_index(batch.get("projects"),"batch.projects")
    audits=unique_index(batch.get("finalMainAudit"),"batch.audit")
    same(sorted(projects),DONE,"batch.projects.IDs")
    same(sorted(audits),DONE,"batch.audit.IDs")
    for ident in DONE:
        record=completion[str(ident)]
        for field in ("repository","pr","mainCommit","headCommit"):
            same(projects[ident].get(field),record.get(field),"batch.project." + field)
        require(projects[ident].get("status") in COMPLETE,"batch.project.status")
        same(audits[ident],record["currentMainAudit"],"batch.auditConsistency")
    message=mail(batch.get("gmail"),"batch.gmail",True)
    same(batch["gmail"]["reportReference"],batch.get("runId"),"batch.gmail.reference")
    same(mail(lease.get("gmail"),"lease.gmail",True),message,"lease.gmail.message")
    same(lease["gmail"]["reportReference"],batch.get("runId"),"batch.reportReference")
    for record in completion.values():
        if record["status"] in COMPLETE:
            same(mail(record.get("gmail"),"completion.gmail"),message,"completion.gmail.message")
            same(record["gmail"]["reportReference"],batch["runId"],"completion.gmail.reference")
            same(record.get("emailStatus"),"sent:"+message,"completion.emailStatus")
    # Count distinct message IDs in this report's date, not append-only reconciliation rows.
    sent_ids=set(); latest={}
    require(type(rows) is list and bool(rows),"daily.rows")
    for row in rows:
        require(None not in row and None not in row.values(),"daily.csvShape")
        try: ident=int(row["Id"])
        except (ValueError,KeyError) as exc: raise ValidationError("daily.Id") from exc
        require(ident in rmap,"daily.roadmapId")
        latest[ident]=row
        if row.get("RunDate") == "2026-10-10" and ident in DONE:
            status=row.get("EmailStatus","")
            if status.startswith("sent:"):
                sent_ids.add(status[5:])
    same(sent_ids,{message},"daily.singleBatchMessage")
    for ident in DONE:
        row=latest.get(ident); obj(row,"daily.latest")
        same(row.get("Status"),"verified_complete","daily.latestStatus")
        same(row.get("MainCommit"),completion[str(ident)]["mainCommit"],"daily.main")
        same(row.get("EmailStatus"),"sent:"+message,"daily.gmail")
    obj(scheduler,"scheduler"); obj(setup,"setup")
    same(scheduler.get("enabled"),True,"scheduler.enabled")
    same(scheduler.get("paused"),False,"scheduler.paused")
    same(scheduler.get("timezone"),"Asia/Kolkata","scheduler.timezone")
    same(scheduler.get("source"),"authoritative cloud automations.peek","scheduler.source")
    recurrence=scheduler.get("recurrence"); text(recurrence,"scheduler.recurrence")
    lines=recurrence.splitlines()
    require(len(lines)==4 and lines[0]=="BEGIN:VEVENT" and lines[-1]=="END:VEVENT","scheduler.vevent")
    require(bool(re.fullmatch(r"DTSTART;TZID=Asia/Kolkata:[0-9]{8}T040000",lines[1])),"scheduler.start")
    same(lines[2],"RRULE:FREQ=DAILY;BYHOUR=4;BYMINUTE=0;BYSECOND=0","scheduler.rule")
    same(setup.get("scheduleId"),scheduler.get("scheduleId"),"scheduler.id")
    same(setup.get("enabled"),True,"setup.enabled")
    same(setup.get("timezone"),"Asia/Kolkata","setup.timezone")
    same(setup.get("schedule"),recurrence,"setup.schedule")
    same(setup.get("execution"),"ChatGPT cloud scheduled task; user computer/local executor prohibited","scheduler.cloudOnly")
    for key in ("projectExecutionStarted","emailSent"):
        same(scheduler.get(key),False,"scheduler." + key)
    chosen=selector(roadmap,completion,20)
    same([p["id"] for p in chosen],NEXT,"selector.first20Unfinished")
    same([p["id"] for p in roadmap if p["id"] not in verified][:20],NEXT,"noSkippedUnfinished")
    return {"valid":True,"roadmapCount":2200,"verifiedComplete":20,"remaining":2180,
            "nextID":21,"selectedIDs":NEXT,"uniqueBatchGmailMessages":len(sent_ids),
            "historicalLedgerRows":len(rows)}

def validate_files(root):
    root=Path(root)
    def read(path): return load_json(root/path)
    with (root/"state/daily-results.csv").open(newline="",encoding="utf-8-sig") as handle:
        rows=list(csv.DictReader(handle,strict=True))
    result=validate_state(read("roadmap-projects.json"),read("state/completion-verifications.json"),
        read("state/active-lease.json"),read(BATCH),read("state/scheduler-readback-20261010.json"),
        read("state/cloud-schedule-setup-20261006.json"),rows)
    validate_manifest(root)
    result["planningManifestValid"]=True
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    try:
        print(json.dumps(validate_files(args.root),sort_keys=True))
    except (ValidationError, OSError, csv.Error, KeyError, TypeError, ValueError) as exc:
        parser.exit(1,"INVALID CONTROL STATE: "+str(exc)+"\n")

if __name__=="__main__": main()
