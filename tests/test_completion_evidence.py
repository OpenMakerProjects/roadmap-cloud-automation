"""Synthetic offline evidence; never represents a live build or hardware test."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.completion_evidence import pending,validate,aggregate,FIELDS,GATES
from tools.validate_execution_manifest import ValidationError,load_json
ROOT=Path(__file__).resolve().parents[1]

class CompletionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roadmap=load_json(ROOT/"roadmap-projects.json")
        cls.plans=load_json(ROOT/"state/execution-manifest-20261011-ids021-040.json")["projects"]

    def fixture(self,ident=21):
        entry=self.roadmap[ident-1];plan=next(p for p in self.plans if p["id"]==ident)
        r=pending(entry,plan,"OMP-021-040-20261011")
        final="b"*40;main="c"*40;repo=r["repository"]["url"]
        r["repository"].update(public=True,observedAtIST="2026-10-11T04:00:00+05:30")
        r.update(finalHead=final,pr={"number":1,"url":repo+"/pull/1","base":"main",
            "branch":r["branch"],"head":final,"state":"closed","merged":True,
            "runPRNumbers":[1],"mergedAtIST":"2026-10-11T05:00:00+05:30","mergeCommit":main})
        r["checks"]=[{"event":event,"name":name,"runId":ident*1000+index,"url":repo+"/actions/runs/"+str(ident*1000+index),
            "head":final,"status":"completed","conclusion":"success",
            "completedAtIST":"2026-10-11T04:59:00+05:30"}
            for index,(event,name) in enumerate(sorted(GATES))]
        testfile="tests/test_policy.py" if plan["actualTargetGate"]["catalogRef"]=="piPython" else "tests/policy_test.cpp"
        files=["README.md","LICENSE",".gitignore","project.json",plan["intendedEntrypoint"],
            "docs/circuit-diagram.svg","docs/images/project-overview.png",testfile,
            "tools/validate.py",".github/workflows/completion.yml","config/example.json"]
        r["main"]={"branch":"main","commit":main,"public":True,
            "reverifiedAtIST":"2026-10-11T05:01:00+05:30","files":files,
            "testFiles":[testfile],"validationFiles":["tools/validate.py"],
            "ciFiles":[".github/workflows/completion.yml"],"configurationFiles":["config/example.json"],
            "metadataEntrypoint":plan["intendedEntrypoint"],"realSource":True,"fullMITLicense":True}
        svg='<svg xmlns="http://www.w3.org/2000/svg"><text x="1" y="2">Synthetic topology fixture</text></svg>'
        r["assets"]={"image":{"path":"docs/images/project-overview.png","originalGenerated":True,
            "bytes":12345,"dimensions":[1536,1024],"sha256":"d"*64,"gitBlob":"e"*40,
            "pngSignatureValid":True,"crcValid":True,"losslessHashVerified":True,
            "decoder":{"runId":99,"conclusion":"success","head":"a"*40,"finalHeadVerified":final,
                "sourceAncestorOfFinal":True,"validationRunId":ident*1000,"decodedSHA256":"d"*64}},
            "svg":{"path":"docs/circuit-diagram.svg","xmlParsed":True,"selfContained":True,
                "noScriptsOrExternalResources":True,"pinsPowerMatchSourceREADME":True,"gitBlob":"f"*40,
                "content":svg,"sha256":hashlib.sha256(svg.encode()).hexdigest()},
            "readme":{"relativeLinksPassed":True,"imageEmbeddedWithAlt":True,"requiredSectionsPassed":True,
                "checkedRelativeLinks":["docs/circuit-diagram.svg","docs/images/project-overview.png"],
                "imageAlt":"Synthetic project fixture, not an actual image"}}
        catalog=plan["actualTargetGate"]["catalogRef"]
        command=plan["actualTargetGate"].get("replaceDefaultBuildCommandWith") or {
            "esphomeESP32":"esphome compile firmware/device.yaml","esp32Arduino":"pio run -e esp32dev",
            "esp8266Arduino":"pio run -e nodemcuv2","nanoArduino":"pio run -e nano_33_iot",
            "piPython":"python -m src.main --simulate --iterations 5 --interval 0"}[catalog]
        r["validation"]={"head":final,"host":{"projectSpecific":True,"projectID":ident,
            "passedTests":7,"command":plan["actualTargetGate"].get("hostPolicyCommand","python -m unittest discover -s tests -v"),
            "cases":plan["proposedHostTests"],"productionPolicyCovered":True},
            "target":{"catalogRef":catalog,"command":command,"conclusion":"success",
                "kind":"linux_runtime_config" if catalog=="piPython" else "board_compile",
                "configurationPassed":True,"platformVersions":"synthetic version evidence"},
            "secretScan":{"passed":True,"head":final,"command":"synthetic-fixture-scan"}}
        r["result"]={"status":"verified_complete","blocker":None,
                     "timestampIST":"2026-10-11T05:02:00+05:30"}
        return r,entry,plan

    def reject(self,mutate):
        r,e,p=self.fixture();mutate(r)
        with self.assertRaises(ValidationError):validate(r,e,p)

    def test_schema_and_pending_template_alignment(self):
        schema=load_json(ROOT/"templates/completion-evidence/schema-v1.json")
        template=load_json(ROOT/"templates/completion-evidence/pending-id021.json")
        self.assertEqual(set(schema["required"]),set(template))
        self.assertEqual(template,pending(self.roadmap[20],self.plans[0],"OMP-021-040-20261011"))
        with self.assertRaises(ValidationError):validate(template,self.roadmap[20],self.plans[0])

    def test_all_twenty_planned_platform_fixtures(self):
        with patch("socket.socket",side_effect=AssertionError("network forbidden")):
            for plan in self.plans:
                r,e,p=self.fixture(plan["id"])
                self.assertEqual(validate(r,e,p),plan["id"])

    def test_pending_never_counts_and_cli(self):
        e=self.roadmap[20];p=self.plans[0];record=pending(e,p,"OMP-021-040-20261011")
        with self.assertRaises(ValidationError):validate(record,e,p)
        summary=aggregate([record],self.roadmap,self.plans)
        self.assertEqual((summary["verifiedTotal"],summary["remainingTotal"],summary["nextStartingID"]),(0,2200,1))
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"pending.json";path.write_text(json.dumps(record))
            result=subprocess.run([sys.executable,str(ROOT/"tools/completion_evidence.py"),
                "--validate",str(path)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            generated=subprocess.run([sys.executable,str(ROOT/"tools/completion_evidence.py"),
                "--generate-pending","21"],capture_output=True,text=True)
            self.assertEqual(generated.returncode,0,generated.stderr)
            self.assertEqual(json.loads(generated.stdout),record)

    def test_identity_base_repository_branch_and_schema(self):
        for key in FIELDS:
            self.reject(lambda r:r["identity"].__setitem__(key,"drift"))
        for key in ("schemaVersion","kind","baseMain","finalHead","branch"):
            self.reject(lambda r:r.__setitem__(key,"wrong"))
        self.reject(lambda r:r.__setitem__("extraIntent",True))
        for key,value in (("public",False),("defaultBranch","master"),("owner","someone"),
                          ("url","https://github.com/other/x")):
            self.reject(lambda r:r["repository"].__setitem__(key,value))

    def test_exact_head_all_four_event_gates_before_merge(self):
        self.reject(lambda r:r["checks"].pop())
        self.reject(lambda r:r["checks"].append(r["checks"][0]))
        for key,value in (("head","a"*40),("conclusion","failure"),("event","workflow_dispatch"),
                          ("runId",None),("status","queued"),("name","Generic smoke"),
                          ("completedAtIST","2026-10-11T06:00:00+05:30")):
            self.reject(lambda r:r["checks"][0].__setitem__(key,value))
        self.reject(lambda r:r["checks"][1].__setitem__("runId",r["checks"][0]["runId"]))

    def test_pr_merge_and_legacy_optin(self):
        for key,value in (("state","open"),("merged",False),("runPRNumbers",[1,2]),("head","a"*40)):
            self.reject(lambda r:r["pr"].__setitem__(key,value))
        self.reject(lambda r:r["main"].__setitem__("commit","d"*40))
        r,e,p=self.fixture();r["legacyRemediation"]={"legacy":True,"reason":"Synthetic remediation",
            "priorPRs":[{"number":2,"url":r["repository"]["url"]+"/pull/2","diagnostic":"Failed legacy gate"}]}
        with self.assertRaises(ValidationError):validate(r,e,p)
        with self.assertRaises(ValidationError):validate(r,e,p,allow_legacy=True)
        e=self.roadmap[12];p=dict(p,id=13)
        r["identity"]={k:e[k] for k in FIELDS}
        r["runReference"]="OMP-001-020-20261011"
        r["branch"]=r["branch"].replace("id021","id013").replace("omp-021-040-20261011","omp-001-020-20261011");r["pr"]["branch"]=r["branch"]
        repo="https://github.com/OpenMakerProjects/"+e["slug"]
        r["repository"]["url"]=repo;r["pr"]["url"]=repo+"/pull/1"
        r["main"]["repository"]=repo
        for check in r["checks"]:check["url"]=repo+"/actions/runs/"+str(check["runId"])
        r["legacyRemediation"]["priorPRs"][0]["url"]=repo+"/pull/2"
        r["validation"]["host"]["projectID"]=13
        self.assertEqual(validate(r,e,p,allow_legacy=True),13)
        r["legacyRemediation"]["priorPRs"].append(r["legacyRemediation"]["priorPRs"][0])
        with self.assertRaises(ValidationError):validate(r,e,p,allow_legacy=True)

    def test_missing_main_material_and_assets(self):
        for path in ("README.md","LICENSE","project.json","docs/circuit-diagram.svg",
                     "docs/images/project-overview.png","firmware/device.yaml"):
            self.reject(lambda r:r["main"]["files"].remove(path))
        self.reject(lambda r:r["main"]["files"].append("docs/image-staging/x.b64.001"))
        for key in ("testFiles","validationFiles","ciFiles","configurationFiles"):
            self.reject(lambda r:r["main"].__setitem__(key,[]))
        for key in ("realSource","fullMITLicense"):
            self.reject(lambda r:r["main"].__setitem__(key,False))
        for key in ("pngSignatureValid","crcValid","losslessHashVerified","originalGenerated"):
            self.reject(lambda r:r["assets"]["image"].__setitem__(key,False))
        self.reject(lambda r:r["assets"]["image"]["decoder"].__setitem__("decodedSHA256","0"*64))
        self.reject(lambda r:r["assets"]["readme"].__setitem__("checkedRelativeLinks",["../missing"]))
        self.reject(lambda r:r["assets"]["readme"].__setitem__("imageAlt",""))

    def test_svg_security_parse_and_hash(self):
        for svg in ("<svg>",'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>',
                    '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
                    '<svg xmlns="http://www.w3.org/2000/svg" onload="x"/>',
                    '<svg xmlns="http://www.w3.org/2000/svg"><use href="https://evil.test/"/></svg>'):
            def mutate(r):
                r["assets"]["svg"].update(content=svg,sha256=hashlib.sha256(svg.encode()).hexdigest())
            self.reject(mutate)
        self.reject(lambda r:r["assets"]["svg"].__setitem__("sha256","0"*64))

    def test_tests_platform_hardware_result_and_deferred_mail(self):
        self.reject(lambda r:r["validation"]["host"].__setitem__("projectSpecific",False))
        self.reject(lambda r:r["validation"]["host"].__setitem__("cases",["smoke","placeholder","generic"]))
        self.reject(lambda r:r["validation"]["host"].__setitem__("passedTests",0))
        self.reject(lambda r:r["validation"]["target"].__setitem__("catalogRef","nanoArduino"))
        self.reject(lambda r:r["validation"]["target"].__setitem__("command","python -m compileall ."))
        self.reject(lambda r:r["validation"]["secretScan"].__setitem__("passed",False))
        self.reject(lambda r:r["hardware"].__setitem__("status","performed"))
        for key,value in (("status","pending"),("blocker","blocked"),("timestampIST","2026-10-11T04:00:00+05:30")):
            self.reject(lambda r:r["result"].__setitem__(key,value))
        self.reject(lambda r:r["gmail"].__setitem__("status","sent"))
        self.reject(lambda r:r["gmail"].__setitem__("messageId","abc123"))

    def test_complete_batch_aggregation_and_cross_project_run_guard(self):
        records=[self.fixture(i)[0] for i in range(21,41)]
        summary=aggregate(records,self.roadmap,self.plans)
        self.assertEqual(summary["verifiedIDs"],list(range(21,41)))
        self.assertEqual((summary["verifiedTotal"],summary["remainingTotal"],summary["nextStartingID"]),(20,2180,1))
        copied=copy.deepcopy(records[:2])
        copied[1]["checks"][0]["runId"]=copied[0]["checks"][0]["runId"]
        copied[1]["checks"][0]["url"]=copied[1]["repository"]["url"]+"/actions/runs/"+str(copied[1]["checks"][0]["runId"])
        copied[1]["assets"]["image"]["decoder"]["validationRunId"]=copied[1]["checks"][0]["runId"]
        summary=aggregate(copied,self.roadmap,self.plans)
        self.assertEqual(summary["verifiedTotal"],1)
        self.assertIn("22",summary["invalidOrPending"])

    def test_aggregation_only_valid_records_and_duplicate_guard(self):
        good,e,p=self.fixture();bad=copy.deepcopy(good);bad["checks"][0]["head"]="a"*40
        summary=aggregate([bad],self.roadmap,self.plans)
        self.assertEqual(summary["verifiedTotal"],0)
        self.assertIn("21",summary["invalidOrPending"])
        summary=aggregate([good],self.roadmap,self.plans)
        self.assertEqual((summary["verifiedTotal"],summary["remainingTotal"],summary["nextStartingID"]),(1,2199,1))
        with self.assertRaises(ValidationError):aggregate([good,good],self.roadmap,self.plans)

if __name__=="__main__":unittest.main()
