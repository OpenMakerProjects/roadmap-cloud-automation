#!/usr/bin/env python3
"""Offline evidence consistency gate. Live GitHub observations remain mandatory."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import hashlib
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.validate_execution_manifest import ValidationError,load_json,require,same,obj,text,unique_index

FIELDS=("id","title","slug","category","platform","connectivity","components","scope","deliverable")
ROOT_KEYS={"schemaVersion","kind","identity","runReference","baseMain","repository","branch","pr",
"finalHead","checks","main","assets","validation","hardware","result","gmail","legacyRemediation"}
GATES={("push","Validate project"),("push","Completion gates"),
       ("pull_request","Validate project"),("pull_request","Completion gates")}
CATALOG_PLATFORMS={"esp32Arduino":"ESP32","esp8266Arduino":"ESP8266",
"nanoArduino":"Arduino Nano 33 IoT","esphomeESP32":"Home Assistant + ESPHome",
"piPython":"Raspberry Pi Zero 2 W"}

def sha(value,path,length=40):
    require(type(value) is str and bool(re.fullmatch("[0-9a-f]{"+str(length)+"}",value)),path)

def time(value,path):
    text(value,path)
    try:result=datetime.fromisoformat(value)
    except ValueError as exc:raise ValidationError(path) from exc
    require(result.tzinfo is not None,path+".timezone")
    return result

def integer(value,path,minimum=1):
    require(type(value) is int and value>=minimum,path)

def paths(value,path):
    require(type(value) is list and bool(value) and len(set(value))==len(value),path)
    for item in value:
        text(item,path)
        require(not item.startswith("/") and ".." not in item.split("/") and "\\" not in item,path+".relative")
    return value

def pending(entry,plan,run_reference):
    same(entry["id"],plan["id"],"pending identity")
    text(run_reference,"runReference")
    return {"schemaVersion":1,"kind":"project_completion_evidence","identity":{k:entry[k] for k in FIELDS},
        "runReference":run_reference,"baseMain":plan["currentMainSHA"],
        "repository":{"url":"https://github.com/OpenMakerProjects/"+entry["slug"],"owner":"OpenMakerProjects",
                      "public":None,"defaultBranch":"main","observedAtIST":None},
        "branch":"automation/"+run_reference.lower()+"-id"+str(entry["id"]).zfill(3),
        "pr":None,"finalHead":None,"checks":[],"main":None,"assets":None,"validation":None,
        "hardware":{"status":"not_performed","evidence":None},
        "result":{"status":"pending","blocker":None,"timestampIST":None},
        "gmail":{"status":"deferred_batch_report","messageId":None},"legacyRemediation":None}

def validate(record,entry,plan,allow_legacy=False):
    from tools.non_authoritative import reject_canary_inputs
    reject_canary_inputs([record,entry,plan])
    obj(record,"record")
    same(set(record),ROOT_KEYS,"record schema keys")
    same(record.get("schemaVersion"),1,"schemaVersion")
    same(record.get("kind"),"project_completion_evidence","kind")
    identity=record.get("identity");obj(identity,"identity")
    same(identity,{k:entry[k] for k in FIELDS},"exact roadmap identity")
    same(plan["id"],entry["id"],"plan ID")
    sha(record.get("baseMain"),"baseMain")
    same(record["baseMain"],plan["currentMainSHA"],"observed current base main")
    ref=record.get("runReference")
    require(type(ref) is str,"runReference")
    match=re.fullmatch(r"OMP-([0-9]{3,4})-([0-9]{3,4})-([0-9]{8})",ref)
    require(match is not None,"canonical runReference")
    first,last=int(match.group(1)),int(match.group(2))
    require(first<=entry["id"]<=last and 1<=last-first+1<=20,"project belongs to planned run")
    repo="https://github.com/OpenMakerProjects/"+entry["slug"]
    repository=record.get("repository");obj(repository,"repository")
    for key,value in (("url",repo),("owner","OpenMakerProjects"),("public",True),("defaultBranch","main")):
        same(repository.get(key),value,"repository."+key)
    time(repository.get("observedAtIST"),"repository observed time")
    branch=record.get("branch")
    require(type(branch) is str and bool(re.fullmatch(r"automation/[a-z0-9][a-z0-9/-]*",branch)),"unique automation branch")
    require(ref.lower() in branch and ("id"+str(entry["id"]).zfill(3)) in branch,"branch run/project identity")
    final=record.get("finalHead");sha(final,"finalHead")
    pr=record.get("pr");obj(pr,"pr")
    integer(pr.get("number"),"pr.number")
    same(pr.get("url"),repo+"/pull/"+str(pr["number"]),"pr.url")
    same(pr.get("base"),"main","pr.base");same(pr.get("branch"),branch,"pr.branch")
    same(pr.get("head"),final,"pr.head")
    same(pr.get("state"),"closed","pr.closed");same(pr.get("merged"),True,"pr.merged")
    numbers=pr.get("runPRNumbers")
    same(numbers,[pr["number"]],"exactly one PR in planned run")
    merged=time(pr.get("mergedAtIST"),"pr.mergedAt")
    sha(pr.get("mergeCommit"),"pr.mergeCommit")
    legacy=record.get("legacyRemediation")
    if legacy is not None:
        require(allow_legacy and entry["id"]<=20,"legacy remediation restricted to historical IDs1–20 with explicit opt-in")
        obj(legacy,"legacyRemediation");same(legacy.get("legacy"),True,"legacy marker")
        text(legacy.get("reason"),"legacy reason")
        historical=legacy.get("priorPRs")
        require(type(historical) is list and bool(historical),"legacy priorPRs")
        nums=set()
        for old in historical:
            obj(old,"legacy PR");integer(old.get("number"),"legacy number")
            require(old["number"]!=pr["number"] and old["number"] not in nums,"legacy duplicate PR")
            nums.add(old["number"])
            same(old.get("url"),repo+"/pull/"+str(old["number"]),"legacy URL")
            text(old.get("diagnostic"),"legacy diagnostic")
    checks=record.get("checks");require(type(checks) is list and len(checks)==4,"four exact-head gates")
    tuples=set();runs=set()
    for check in checks:
        obj(check,"check")
        pair=(check.get("event"),check.get("name"));require(pair in GATES and pair not in tuples,"check event/name")
        tuples.add(pair);integer(check.get("runId"),"check.runId")
        require(check["runId"] not in runs,"duplicate runId");runs.add(check["runId"])
        same(check.get("head"),final,"check exact head")
        same(check.get("status"),"completed","check status")
        same(check.get("conclusion"),"success","check success")
        finished=time(check.get("completedAtIST"),"check finished")
        require(finished<=merged,"check after merge")
        same(check.get("url"),repo+"/actions/runs/"+str(check["runId"]),"check URL")
    same(tuples,GATES,"push and PR event gates")
    main=record.get("main");obj(main,"main")
    same(main.get("branch"),"main","main.branch")
    same(main.get("commit"),pr["mergeCommit"],"merge/main consistency")
    same(main.get("public"),True,"main.public")
    verified=time(main.get("reverifiedAtIST"),"main reverification")
    require(verified>=merged,"main verified before merge")
    tree=paths(main.get("files"),"main.files")
    entrypoint=plan["intendedEntrypoint"]
    required={"README.md","LICENSE",".gitignore","project.json",entrypoint,
              "docs/circuit-diagram.svg","docs/images/project-overview.png"}
    require(required<=set(tree),"missing main artifacts")
    require(not any(".b64" in path for path in tree),"transport chunks remain")
    for group in ("testFiles","validationFiles","ciFiles","configurationFiles"):
        chosen=paths(main.get(group),"main."+group)
        require(set(chosen)<=set(tree),"declared material missing from main")
    require(all(p.startswith(".github/workflows/") and p.endswith((".yml",".yaml")) for p in main["ciFiles"]),"CI material")
    same(main.get("metadataEntrypoint"),entrypoint,"metadata entrypoint")
    same(main.get("realSource"),True,"real source evidence")
    same(main.get("fullMITLicense"),True,"full MIT evidence")
    assets=record.get("assets");obj(assets,"assets")
    image=assets.get("image");obj(image,"image")
    same(image.get("path"),"docs/images/project-overview.png","image path")
    same(image.get("originalGenerated"),True,"original image")
    integer(image.get("bytes"),"image bytes")
    dimensions=image.get("dimensions")
    require(type(dimensions) is list and len(dimensions)==2,"image dimensions")
    for dimension in dimensions:integer(dimension,"image dimension")
    sha(image.get("sha256"),"image SHA256",64);sha(image.get("gitBlob"),"image blob")
    for key in ("pngSignatureValid","crcValid","losslessHashVerified"):
        same(image.get(key),True,"image."+key)
    decoder=image.get("decoder")
    obj(decoder,"image decoder");integer(decoder.get("runId"),"decoder run")
    same(decoder.get("conclusion"),"success","decoder success")
    sha(decoder.get("head"),"decoder source head")
    same(decoder.get("finalHeadVerified"),final,"final PNG evidence head")
    if decoder["head"]!=final:same(decoder.get("sourceAncestorOfFinal"),True,"decoder ancestry")
    require(any(c["runId"]==decoder.get("validationRunId") and c["name"]=="Completion gates" for c in checks),"image final-check completion run evidence")
    same(decoder.get("decodedSHA256"),image["sha256"],"decoder hash")
    svg=assets.get("svg");obj(svg,"SVG")
    same(svg.get("path"),"docs/circuit-diagram.svg","SVG path")
    for key in ("xmlParsed","selfContained","noScriptsOrExternalResources","pinsPowerMatchSourceREADME"):
        same(svg.get(key),True,"SVG."+key)
    sha(svg.get("gitBlob"),"SVG blob")
    svg_text=svg.get("content");text(svg_text,"SVG content")
    require(len(svg_text)<=524288 and not re.search(r"<!DOCTYPE|<!ENTITY",svg_text,re.I),"unsafe SVG declarations")
    try:svg_root=ET.fromstring(svg_text)
    except ET.ParseError as exc:raise ValidationError("SVG parse") from exc
    same(svg_root.tag,"{http://www.w3.org/2000/svg}svg","SVG namespace")
    for node in svg_root.iter():
        require(node.tag.rsplit("}",1)[-1] not in {"script","foreignObject","image","style"},"unsafe SVG element")
        for key,value in node.attrib.items():
            local=key.rsplit("}",1)[-1].lower()
            require(not local.startswith("on"),"SVG event handler")
            if local=="href":require(value.startswith("#"),"external SVG href")
            require(not re.search(r"url\s*\(",value,re.I),"SVG CSS resource")
    same(svg.get("sha256"),hashlib.sha256(svg_text.encode()).hexdigest(),"SVG content hash")
    readme=assets.get("readme");obj(readme,"README")
    for key in ("relativeLinksPassed","imageEmbeddedWithAlt","requiredSectionsPassed"):
        same(readme.get(key),True,"README."+key)
    links=paths(readme.get("checkedRelativeLinks"),"README relative links")
    require(set(links)<=set(tree) and {"docs/circuit-diagram.svg","docs/images/project-overview.png"}<=set(links),"README linked assets")
    text(readme.get("imageAlt"),"README useful image alt")
    validation=record.get("validation");obj(validation,"validation")
    same(validation.get("head"),final,"validation head")
    host=validation.get("host");obj(host,"host")
    same(host.get("projectSpecific"),True,"project-specific tests")
    same(host.get("projectID"),entry["id"],"host project ID")
    integer(host.get("passedTests"),"host test count")
    text(host.get("command"),"host command")
    expected_host=plan["actualTargetGate"].get("hostPolicyCommand","python -m unittest discover -s tests -v")
    same(host["command"],expected_host,"project host command")
    if plan["actualTargetGate"]["catalogRef"]=="piPython":
        require(any(p.endswith(".py") and not p.endswith("__init__.py") for p in main["testFiles"]),"Pi Python test material")
    else:require(any(p.endswith(".cpp") for p in main["testFiles"]),"C++ host test material")
    cases=host.get("cases");require(type(cases) is list and len(cases)>=3,"meaningful behavior cases")
    for case in cases:text(case,"host case")
    require(len(set(cases))==len(cases),"generic duplicate test cases")
    same(cases,plan["proposedHostTests"],"project-specific planned behavior coverage")
    same(host.get("productionPolicyCovered"),True,"production policy coverage")
    target=validation.get("target");obj(target,"target")
    catalog=plan["actualTargetGate"]["catalogRef"]
    same(target.get("catalogRef"),catalog,"actual platform gate")
    same(entry["platform"],CATALOG_PLATFORMS.get(catalog),"platform mapping")
    expected_command=plan["actualTargetGate"].get("replaceDefaultBuildCommandWith")
    if not expected_command:
        expected_command={"esp32Arduino":"pio run -e esp32dev","esp8266Arduino":"pio run -e nodemcuv2",
                          "nanoArduino":"pio run -e nano_33_iot","esphomeESP32":"esphome compile firmware/device.yaml",
                          "piPython":"python -m src.main --simulate --iterations 5 --interval 0"}[catalog]
    same(target.get("command"),expected_command,"actual target command")
    same(target.get("conclusion"),"success","target success")
    required_kind="linux_runtime_config" if catalog=="piPython" else "board_compile"
    same(target.get("kind"),required_kind,"Pi host versus board distinction")
    if catalog in ("esphomeESP32","piPython"):same(target.get("configurationPassed"),True,"config validation")
    text(target.get("platformVersions"),"target pinned versions")
    scan=validation.get("secretScan");obj(scan,"secret scan")
    same(scan.get("passed"),True,"secret scan passed")
    same(scan.get("head"),final,"secret scan head")
    text(scan.get("command"),"secret scan command")
    hardware=record.get("hardware");obj(hardware,"hardware")
    require(hardware.get("status") in ("not_performed","performed"),"hardware status")
    if hardware["status"]=="performed":
        evidence=hardware.get("evidence");obj(evidence,"physical hardware evidence")
        for key in ("operator","equipment","procedure","results","artifactReference"):text(evidence.get(key),"hardware."+key)
        time(evidence.get("performedAtIST"),"hardware timestamp")
    else:same(hardware.get("evidence"),None,"unsupported hardware evidence")
    result=record.get("result");obj(result,"durable result")
    same(result.get("status"),"verified_complete","completion not inferred from intent")
    same(result.get("blocker"),None,"completed blocker")
    require(time(result.get("timestampIST"),"durable timestamp")>=verified,"durable before reverification")
    gmail=record.get("gmail");obj(gmail,"deferred Gmail")
    same(gmail.get("status"),"deferred_batch_report","Gmail batch-only")
    same(gmail.get("messageId"),None,"no per-project Gmail")
    return entry["id"]

def aggregate(records,roadmap,plans,allow_legacy=False):
    rmap=unique_index(roadmap,"roadmap")
    same(sorted(rmap),list(range(1,2201)),"roadmap exactly 2200")
    pmap=unique_index(plans,"plans")
    require(type(records) is list,"records")
    seen=set();verified=set();branches=set();check_runs=set();invalid={}
    for record in records:
        obj(record,"record")
        ident=record.get("identity",{}).get("id")
        require(type(ident) is int and ident in rmap and ident not in seen,"duplicate/unknown record ID")
        seen.add(ident)
        try:
            require(ident in pmap,"missing authoritative plan")
            validate(record,rmap[ident],pmap[ident],allow_legacy)
            require(record["branch"] not in branches,"duplicate automation branch")
            record_runs={check["runId"] for check in record["checks"]}
            require(not record_runs & check_runs,"workflow run IDs reused across projects")
            check_runs.update(record_runs)
            branches.add(record["branch"]);verified.add(ident)
        except (ValidationError,KeyError,TypeError,ValueError) as exc:
            invalid[str(ident)]=str(exc)
    unfinished=[i for i in sorted(rmap) if i not in verified]
    return {"verifiedTotal":len(verified),"remainingTotal":len(unfinished),
            "nextStartingID":unfinished[0] if unfinished else None,
            "verifiedIDs":sorted(verified),"invalidOrPending":invalid}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--generate-pending",type=int)
    parser.add_argument("--run-reference",default="OMP-021-040-20261011")
    parser.add_argument("--validate",type=Path)
    parser.add_argument("--aggregate",type=Path)
    args=parser.parse_args()
    try:
        roadmap=load_json(args.root/"roadmap-projects.json")
        manifest=load_json(args.root/"state/execution-manifest-20261011-ids021-040.json")
        rmap=unique_index(roadmap,"roadmap");pmap=unique_index(manifest["projects"],"plans")
        if args.generate_pending:
            ident=args.generate_pending
            require(ident in pmap,"ID outside authoritative plan")
            out=pending(rmap[ident],pmap[ident],args.run_reference)
        elif args.validate:
            record=load_json(args.validate);ident=record.get("identity",{}).get("id")
            require(ident in pmap,"ID outside plan")
            out={"valid":True,"id":validate(record,rmap[ident],pmap[ident])}
        elif args.aggregate:
            out=aggregate(load_json(args.aggregate),roadmap,manifest["projects"])
        else:raise ValidationError("choose generate-pending, validate or aggregate")
        print(json.dumps(out,sort_keys=True))
    except (ValidationError,OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(1,"INVALID COMPLETION EVIDENCE: "+str(exc)+"\n")

if __name__=="__main__":main()
