#!/usr/bin/env python3
"""Deterministic offline HTML reporting; prepares data only, never sends email."""
import argparse
import csv
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.validate_execution_manifest import ValidationError,load_json,require,obj,text,same,unique_index

IST=timezone(timedelta(hours=5,minutes=30))
COMPLETE={"verified_complete","merged_verified"}
TERMINAL={"completed","blocked","failed","partial"}
PROFILE="balwanshrutik@gmail.com"
SECRET=re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|ya29\.[A-Za-z0-9_-]{20,})")

def clean(value):
    def inspect(node):
        if type(node) is dict:
            for key,item in node.items():
                require(str(key).lower() not in {"password","wifi_password","api_key","access_token","refresh_token","authorization","private_key"},"credential field in report")
                inspect(item)
        elif type(node) is list:
            for item in node:inspect(item)
    inspect(value)
    rendered=value if type(value) is str else json.dumps(value,sort_keys=True,ensure_ascii=False)
    require(not SECRET.search(rendered),"credential pattern in report text")
    return html.escape(rendered,quote=True)

def sha(value,path):
    require(type(value) is str and bool(re.fullmatch("[0-9a-f]{40}",value)),path)

def link(url,repo,kind="repo"):
    require(type(repo) is str and bool(re.fullmatch(r"https://github\.com/OpenMakerProjects/[a-z0-9]+(?:-[a-z0-9]+)*",repo)),"invalid expected repository")
    expected=re.escape(repo)
    suffix={"repo":"","pr":r"/pull/[1-9][0-9]*","commit":r"/commit/[0-9a-f]{40}"}[kind]
    require(type(url) is str and bool(re.fullmatch(expected+suffix,url)),"unexpected GitHub URL: "+str(url))
    return url

def anchor(url,label,repo,kind="repo"):
    return '<a href="'+clean(link(url,repo,kind))+'">'+clean(label)+'</a>'

def sent_index(records):
    """Deduplicate references from run/lease/completion reconciliation records."""
    found={}
    pending=set()
    def walk(node):
        if type(node) is dict:
            if "reportReference" in node and "status" in node:
                reference=node["reportReference"];text(reference,"durable.reportReference")
                if node["status"]=="sent":
                    ident=node.get("messageId")
                    require(type(ident) is str and bool(re.fullmatch("[0-9a-f]+",ident)),"durable.messageId")
                    require(node.get("to")=="me","durable.recipient")
                    require(node.get("resolvedProfile",node.get("resolvedRecipient"))==PROFILE,"durable.profile")
                    for field in ("cc","bcc"):
                        same(node.get(field,[]),[],"durable."+field)
                    found.setdefault(reference,set()).add(ident)
                elif node["status"] in ("prepared","sending","delivery_unknown"):
                    pending.add(reference)
            for value in node.values():walk(value)
        elif type(node) is list:
            for value in node:walk(value)
    walk(records)
    for reference,messages in found.items():
        require(len(messages)==1,"contradictory multiple Gmail messages for "+reference)
    return found,pending

def validate_ledger(run,roadmap):
    obj(run,"run"); clean(run)
    require(run.get("status") in TERMINAL,"run terminal status")
    same(run.get("cloudOnly"),True,"run.cloudOnly")
    ref=run.get("runId")
    require(type(ref) is str and bool(re.fullmatch(r"OMP-[A-Za-z0-9-]+",ref)),"stable runId/reportReference")
    try:stamp=datetime.fromisoformat(run["timestampIST"])
    except (KeyError,TypeError,ValueError) as exc:raise ValidationError("timestampIST") from exc
    require(stamp.tzinfo is not None and stamp.utcoffset()==IST.utcoffset(None),"timestampIST offset")
    report_date=stamp.astimezone(IST).date().isoformat()
    subject="OpenMakerProjects daily build report - "+report_date
    gmail=run.get("gmail");obj(gmail,"gmail")
    same(gmail.get("reportReference"),ref,"gmail.reportReference")
    same(gmail.get("subject"),subject,"gmail.subject")
    same(gmail.get("to"),"me","gmail.to")
    same(gmail.get("resolvedProfile"),PROFILE,"gmail.resolvedProfile")
    for field in ("cc","bcc"):same(gmail.get(field),[],"gmail."+field)
    require(gmail.get("status") in ("pending","not_sent","prepared","sending","delivery_unknown","sent"),"gmail.status")
    ids=run.get("selectedIDs")
    require(type(ids) is list and 1<=len(ids)<=20 and all(type(i) is int for i in ids),"selectedIDs")
    require(ids==sorted(set(ids)) and ids==list(range(ids[0],ids[0]+len(ids))),"selectedIDs contiguous unique")
    date_key=report_date.replace("-","")
    expected_reference=f"OMP-{ids[0]:03d}-{ids[-1]:03d}-{date_key}"
    same(ref,expected_reference,"canonical stable reportReference")
    rmap=unique_index(roadmap,"roadmap")
    require(all(i in rmap for i in ids),"selected roadmap IDs")
    attempted=run.get("attemptedIDs")
    require(type(attempted) is list and attempted==sorted(set(attempted)) and set(attempted)<=set(ids),"attemptedIDs")
    projects=run.get("projects");require(type(projects) is list,"projects")
    same([p.get("id") for p in projects if type(p) is dict],ids,"projects cover selected IDs in order")
    pmap=unique_index(projects,"projects")
    audits=unique_index(run.get("finalMainAudit",[]),"finalMainAudit")
    require(set(audits)<=set(ids),"audit outside selection")
    blockers=run.get("unresolvedBlockers");require(type(blockers) is list,"unresolvedBlockers")
    errors=run.get("errors");require(type(errors) is list,"errors")
    for error in errors:
        obj(error,"error");require(error.get("id") in ids and type(error.get("resolved")) is bool,"error id/resolution")
        text(error.get("detail"),"error.detail")
    successes=[]
    for ident in ids:
        p=pmap[ident];repo="https://github.com/OpenMakerProjects/"+rmap[ident]["slug"]
        link(p.get("repository"),repo)
        if p.get("pr"):link(p["pr"],repo,"pr")
        require(p.get("status") in COMPLETE|{"blocked","failed","not_attempted"},"project.status")
        if "mainCommit" in p and p["mainCommit"] is not None:sha(p["mainCommit"],"project.mainCommit")
        hardware=p.get("hardwareTesting")
        if hardware is not None:
            obj(hardware,"hardwareTesting")
            require(hardware.get("status") in ("not_performed","performed"),"hardwareTesting.status")
            if hardware["status"]=="performed":text(hardware.get("evidence"),"hardwareTesting.evidence")
        test_data=p.get("tests")
        if type(test_data) is dict:
            hardware_claim=test_data.get("hardware")
            if hardware_claim is not None and not re.search(r"not performed|not tested|untested",str(hardware_claim),re.I):
                require(hardware is not None and hardware["status"]=="performed","hardware claim lacks evidence")
        if type(test_data) is str and re.search(r"\b(?:physical|hardware) (?:tests?|testing) (?:passed|performed|completed)\b",test_data,re.I):
            require(hardware is not None and hardware["status"]=="performed","hardware claim lacks evidence")
        if p["status"] in COMPLETE:
            successes.append(ident);require(ident in attempted,"complete not attempted/reconciled")
            require(p.get("pr"),"complete PR missing")
            sha(p.get("mainCommit"),"complete.main");sha(p.get("headCommit"),"complete.head")
            require(type(p.get("tests")) in (dict,str) and bool(p["tests"]),"complete tests missing")
            if type(p["tests"]) is dict:
                for key,value in p["tests"].items():
                    if key in ("host","board","completion","finalHead","metadata","requiredMainTree"):
                        require(not re.search(r"\b(failed|pending|blocked)\b",str(value),re.I),"contradictory current tests")
            for check in p.get("checks",[]) if type(p.get("checks")) is list else []:
                obj(check,"check");same(check.get("conclusion"),"success","check.conclusion")
                if "head" in check:same(check["head"],p["headCommit"],"check.head")
            a=audits.get(ident);obj(a,"verified main audit missing")
            for key,value in (("repository",repo),("mainCommit",p["mainCommit"]),("pr",p["pr"]),
                              ("public",True),("prMerged",True),("requiredMainTreeVerified",True),
                              ("sourceTestsCI",True),("transportChunksRemaining",0)):
                same(a.get(key),value,"audit."+key)
            sha(a.get("imageGitBlob"),"audit.imageGitBlob")
            require(not p.get("blocker"),"completed project has blocker")
            require(not any(e["id"]==ident and not e["resolved"] for e in errors),"unresolved error on complete")
        else:
            require(ident not in audits,"failed project has complete audit")
            text(p.get("blocker"),"failed project blocker")
            require(p.get("merged") is not True,"blocked project claims merge")
            if p["status"]=="not_attempted":require(ident not in attempted,"not_attempted conflict")
    if run["status"]=="completed":same(successes,ids,"completed batch has failures")
    if successes==ids:same(run["status"],"completed","all-success ledger status")
    if not successes:require(run["status"] in ("failed","blocked"),"zero-success report status")
    totals=run.get("totals");obj(totals,"totals")
    same(totals.get("roadmap"),len(roadmap),"totals.roadmap")
    verified=totals.get("verifiedComplete");remaining=totals.get("remainingToVerifyAndComplete")
    require(type(verified) is int and type(remaining) is int and 0<=verified<=len(roadmap) and verified+remaining==len(roadmap),"totals arithmetic")
    require(verified>=len(successes),"totals fewer than successes")
    next_id=totals.get("nextStartingID")
    require((type(next_id) is int and next_id in rmap) if remaining else next_id is None,"nextStartingID")
    require(next_id not in successes,"next ID already completed")
    return ref,report_date,subject,pmap,rmap,successes

class SafeHTML(HTMLParser):
    def __init__(self,allowed):
        super().__init__(convert_charrefs=True);self.allowed=allowed;self.stack=[]
    def handle_starttag(self,tag,attrs):
        require(tag in {"html","body","h1","p","table","thead","tbody","tr","th","td","a","strong"},"HTML tag")
        require(len(dict(attrs))==len(attrs),"duplicate HTML attribute")
        if tag=="a":require(len(attrs)==1 and attrs[0][0]=="href" and attrs[0][1] in self.allowed,"HTML href")
        else:require(not attrs,"unexpected HTML attributes")
        self.stack.append(tag)
    def handle_endtag(self,tag):
        require(bool(self.stack) and self.stack.pop()==tag,"unbalanced HTML")
    def handle_comment(self,data):raise ValidationError("HTML comment")
    def handle_decl(self,decl):raise ValidationError("HTML declaration")

def render(run,roadmap):
    ref,date,subject,pmap,rmap,successes=validate_ledger(run,roadmap)
    allowed=set();rows=[]
    for ident in run["selectedIDs"]:
        p=pmap[ident];repo=p["repository"];allowed.add(repo)
        repo_cell=anchor(repo,rmap[ident]["title"],repo)
        pr_cell="None"
        if p.get("pr"):allowed.add(p["pr"]);pr_cell=anchor(p["pr"],"PR "+p["pr"].rsplit("/",1)[1],repo,"pr")
        validation=clean(p.get("tests","No successful validation recorded"))
        hardware=p.get("hardwareTesting")
        if hardware and hardware["status"]=="performed":
            hardware_text="Physical hardware testing: "+hardware["evidence"]
        else:hardware_text="Physical hardware tests: not recorded/performed; cloud/host/target results do not prove hardware operation."
        if ident in successes:
            url=repo+"/commit/"+p["mainCommit"];allowed.add(url)
            merged='Merged; public main verified '+anchor(url,p["mainCommit"],repo,"commit")+'; required tree present; no base64 chunks.'
        else:merged="Not verified complete; "+clean(p["status"])
        rows.append("<tr><td>"+str(ident)+"</td><td>"+repo_cell+"</td><td>"+pr_cell+
                    "</td><td>"+validation+"<p>"+clean(hardware_text)+"</p></td><td>"+merged+
                    "</td><td>"+clean(p.get("blocker") or "None")+"</td></tr>")
    t=run["totals"]
    body="<html><body><h1>OpenMakerProjects daily build report</h1><p>"+clean(date+" IST; report reference: "+ref)+        "</p><p>"+clean("Verified complete: "+str(t["verifiedComplete"])+" / "+str(t["roadmap"])+
        "; remaining: "+str(t["remainingToVerifyAndComplete"])+"; next starting ID: "+str(t["nextStartingID"]))+        "</p><table><thead><tr><th>ID</th><th>Repository</th><th>PR</th><th>Validation and hardware evidence</th><th>Merge/main verification</th><th>Blocker</th></tr></thead><tbody>"+        "".join(rows)+"</tbody></table><p>"+clean("Unresolved blockers: "+json.dumps(run["unresolvedBlockers"],sort_keys=True))+        "</p><p>"+clean("Error history: "+json.dumps(run["errors"],sort_keys=True))+"</p></body></html>"
    require(not SECRET.search(body),"HTML credentials")
    parser=SafeHTML(allowed);parser.feed(body);parser.close();require(not parser.stack,"unclosed HTML")
    return {"reportReference":ref,"idempotencyKey":ref,"subject":subject,"to":"me",
            "resolvedProfile":PROFILE,"cc":[],"bcc":[],"html":body,
            "htmlSha256":hashlib.sha256(body.encode("utf-8")).hexdigest(),"selectedCount":len(rows),
            "succeededCount":len(successes)}

def prepare(run,roadmap,durable_records):
    result=render(run,roadmap)
    sent,pending=sent_index([durable_records,run])
    reference=result["reportReference"]
    require(reference not in sent,"already sent: "+reference)
    require(reference not in pending,"delivery intent requires reconciliation: "+reference)
    result["action"]="prepare_only_no_send"
    return result

def records_from_state(root):
    root=Path(root)
    records=[load_json(path) for path in sorted((root/"state").rglob("*.json"))]
    # CSV has no report-reference column. Resolve only via durable JSON message IDs.
    sent_index(records)
    reports=[]
    for record in records:
        if type(record) is dict and type(record.get("selectedIDs")) is list and type(record.get("gmail")) is dict:
            if record["gmail"].get("reportReference") and record.get("timestampIST"):
                try: day=datetime.fromisoformat(record["timestampIST"]).astimezone(IST).date().isoformat()
                except (TypeError,ValueError) as exc:raise ValidationError("durable report timestamp") from exc
                reports.append((day,set(record["selectedIDs"]),record["gmail"]))
    for path in sorted((root/"state").glob("*.csv")):
        with path.open(newline="",encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle,strict=True):
                require(None not in row,"CSV malformed")
                status=row.get("EmailStatus","") or ""
                if status.startswith("sent:"):
                    # Older rows belong to older reports; retain them without assigning current reference.
                    require(bool(re.fullmatch("[0-9a-f]+",status[5:])),"CSV messageId")
                    for day,selected,gmail in reports:
                        if row.get("RunDate")==day and str(row.get("Id","")).isdigit() and int(row["Id"]) in selected:
                            records.append(dict(gmail,status="sent",messageId=status[5:]))
    return records

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ledger",default="state/run-20261010-batch001-020.json")
    parser.add_argument("--validate-history",action="store_true",
                        help="Validate/render evidence without preparing a send or rewriting historical HTML")
    args=parser.parse_args()
    try:
        run=load_json(args.root/args.ledger);roadmap=load_json(args.root/"roadmap-projects.json")
        if args.validate_history:
            result=render(run,roadmap)
            sent,_=sent_index(records_from_state(args.root))
            historical=run.get("gmail",{})
            if historical.get("status")=="sent":
                require(run["runId"] in sent,"missing durable sent evidence")
                # Validate original evidence independently of this new renderer's output.
                day=result["subject"].rsplit(" ",1)[-1].replace("-","")
                ids=run["selectedIDs"]
                path=args.root/f"state/reports/daily-{day}-batch{ids[0]:03d}-{ids[-1]:03d}.html"
                require(path.exists(),"historical HTML missing")
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                same(digest,historical.get("htmlSha256"),"historical HTML hash")
            result.pop("html");result["action"]="validate_only_no_send"
        else:result=prepare(run,roadmap,records_from_state(args.root))
        print(json.dumps(result,sort_keys=True))
    except (ValidationError,OSError,ValueError,TypeError,KeyError,csv.Error) as exc:
        parser.exit(1,"INVALID REPORT: "+str(exc)+"\n")

if __name__=="__main__":main()
