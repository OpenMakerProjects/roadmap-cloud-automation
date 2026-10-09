"""Offline daily report fixtures: no Gmail/network calls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.daily_report import render,prepare,sent_index,records_from_state
from tools.validate_execution_manifest import ValidationError,load_json
ROOT=Path(__file__).resolve().parents[1]

class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.roadmap=load_json(ROOT/"roadmap-projects.json")
        self.history=load_json(ROOT/"state/run-20261010-batch001-020.json")
        self.run=copy.deepcopy(self.history)
        self.run["gmail"]["status"]="pending"
        for field in ("messageId","threadId","sentAtIST","labelIds","htmlSha256"):
            self.run["gmail"].pop(field,None)

    def tomorrow(self):
        run=copy.deepcopy(self.run)
        run.update(runId="OMP-021-040-20261011",timestampIST="2026-10-11T04:30:00+05:30",
                   status="failed",selectedIDs=list(range(21,41)),attemptedIDs=list(range(21,41)),
                   projects=[],finalMainAudit=[],errors=[],unresolvedBlockers=["CI service unavailable"])
        run["gmail"].update(reportReference=run["runId"],
                           subject="OpenMakerProjects daily build report - 2026-10-11")
        run["totals"].update(verifiedComplete=20,remainingToVerifyAndComplete=2180,nextStartingID=21)
        for ident in run["selectedIDs"]:
            run["projects"].append({"id":ident,"repository":"https://github.com/OpenMakerProjects/"+
                self.roadmap[ident-1]["slug"],"status":"blocked","blocker":"CI unavailable",
                "hardwareTesting":{"status":"not_performed"}})
        return run

    def reject(self,mutate):
        run=copy.deepcopy(self.run);mutate(run)
        with self.assertRaises(ValidationError):render(run,self.roadmap)

    def test_success_determinism_hash_and_recipients(self):
        with patch("socket.socket",side_effect=AssertionError("network forbidden")):
            a=prepare(self.run,self.roadmap,[])
            b=prepare(self.run,self.roadmap,[])
        self.assertEqual(a,b)
        self.assertEqual(a["htmlSha256"],hashlib.sha256(a["html"].encode()).hexdigest())
        self.assertEqual(a["succeededCount"],20)
        self.assertEqual(a["idempotencyKey"],self.run["runId"])
        self.assertEqual((a["to"],a["resolvedProfile"],a["cc"],a["bcc"]),
                         ("me","balwanshrutik@gmail.com",[],[]))
        self.assertIn("Physical hardware tests: not recorded/performed",a["html"])
        self.assertNotIn("<img",a["html"])

    def test_actual_sent_history_cannot_prepare(self):
        result=render(self.history,self.roadmap)
        self.assertEqual(result["succeededCount"],20)
        with self.assertRaisesRegex(ValidationError,"already sent"):
            prepare(self.history,self.roadmap,[])
        with self.assertRaisesRegex(ValidationError,"already sent"):
            prepare(self.run,self.roadmap,records_from_state(ROOT))

    def test_reconciliation_deduplication_and_conflict(self):
        mail=self.history["gmail"]
        records=[{"gmail":mail},{"reconciliation":[mail,mail]}]
        found,_=sent_index(records)
        self.assertEqual(found[self.run["runId"]],{mail["messageId"]})
        with self.assertRaises(ValidationError):prepare(self.run,self.roadmap,records)
        different=dict(mail,messageId="deadbeef")
        with self.assertRaises(ValidationError):sent_index(records+[different])
        for status in ("prepared","sending","delivery_unknown"):
            with self.assertRaisesRegex(ValidationError,"reconciliation"):
                prepare(self.run,self.roadmap,[dict(mail,status=status)])

    def test_escaping_all_dynamic_text(self):
        malicious='<script>alert("x")</script><img src="https://evil.test/"> & \''
        run=self.tomorrow()
        run["projects"][0]["blocker"]=malicious
        run["projects"][0]["tests"]={"diagnostic":malicious}
        run["errors"]=[{"id":21,"resolved":False,"detail":malicious}]
        run["unresolvedBlockers"]=[malicious]
        roadmap=copy.deepcopy(self.roadmap);roadmap[20]["title"]=malicious
        result=render(run,roadmap)
        self.assertNotIn("<script",result["html"])
        self.assertNotIn("<img",result["html"])
        self.assertIn("&lt;script&gt;",result["html"])
        self.assertIn("&amp;",result["html"])

    def test_expected_github_links_only(self):
        repo=self.run["projects"][0]["repository"]
        for url in ("http://github.com/OpenMakerProjects/a","https://evil.test",
                    repo+"?token=x",repo+"#x",repo.replace("github.com","github.com.evil"),
                    repo.replace("github.com","user:pass@github.com"),repo+"/../x",
                    "javascript:alert(1)"):
            self.reject(lambda r:r["projects"][0].__setitem__("repository",url))
        self.reject(lambda r:r["projects"][0].__setitem__("pr",
            "https://github.com/OpenMakerProjects/other/pull/1"))

    def test_missing_and_contradictory_evidence(self):
        for key in ("runId","timestampIST","selectedIDs","attemptedIDs","projects","totals","gmail","errors","unresolvedBlockers"):
            self.reject(lambda r:r.pop(key))
        for key in ("reportReference","subject","to","resolvedProfile","cc","bcc"):
            self.reject(lambda r:r["gmail"].pop(key))
        for key in ("tests","mainCommit","headCommit","pr"):
            self.reject(lambda r:r["projects"][0].pop(key))
        self.reject(lambda r:r["finalMainAudit"][0].__setitem__("transportChunksRemaining",1))
        self.reject(lambda r:r["projects"][0].__setitem__("blocker","unresolved"))
        self.reject(lambda r:r["projects"][-1]["checks"][0].__setitem__("conclusion","failure"))
        self.reject(lambda r:r["totals"].__setitem__("verifiedComplete",19))
        self.reject(lambda r:r["gmail"].__setitem__("cc",["someone"]))
        self.reject(lambda r:r["gmail"].__setitem__("subject","wrong"))
        self.reject(lambda r:r.update(runId="OMP-other",gmail=dict(r["gmail"],reportReference="OMP-other")))
        self.reject(lambda r:r.__setitem__("status","failed"))
        self.reject(lambda r:r["timestampIST"].__class__ if False else r.__setitem__("timestampIST","2026-10-10T00:00:00Z"))
        self.reject(lambda r:r["projects"][0].__setitem__("hardwareTesting",{"status":"performed"}))
        self.reject(lambda r:r["projects"][0].__setitem__("tests",{"hardware":"passed"}))
        self.reject(lambda r:r["projects"][0].__setitem__("tests","Hardware tests passed"))

    def test_no_credentials(self):
        self.reject(lambda r:r["projects"][0].__setitem__("tests",{"wifi_password":"example-private-value"}))
        self.reject(lambda r:r["projects"][0].__setitem__("tests","ghp_"+"a"*30))

    def test_zero_success_failure_and_not_attempted_rows(self):
        run=self.tomorrow()
        result=prepare(run,self.roadmap,[self.history])
        self.assertEqual((result["selectedCount"],result["succeededCount"]),(20,0))
        self.assertIn("CI unavailable",result["html"])
        run["attemptedIDs"]=[]
        for p in run["projects"]:p["status"]="not_attempted"
        self.assertEqual(prepare(run,self.roadmap,[self.history])["succeededCount"],0)
        run["status"]="completed"
        with self.assertRaises(ValidationError):render(run,self.roadmap)

    def test_tomorrow_success_and_temp_cli_prevention(self):
        run=self.tomorrow();run["status"]="completed";run["unresolvedBlockers"]=[]
        run["totals"].update(verifiedComplete=40,remainingToVerifyAndComplete=2160,nextStartingID=41)
        run["finalMainAudit"]=[]
        for p in run["projects"]:
            p.update(status="verified_complete",pr=p["repository"]+"/pull/1",
                     mainCommit="a"*40,headCommit="b"*40,tests="Host and actual target compile passed")
            p.pop("blocker")
            run["finalMainAudit"].append(dict(id=p["id"],repository=p["repository"],pr=p["pr"],
                mainCommit=p["mainCommit"],public=True,prMerged=True,requiredMainTreeVerified=True,
                sourceTestsCI=True,transportChunksRemaining=0,imageGitBlob="c"*40))
        self.assertEqual(prepare(run,self.roadmap,[self.history])["succeededCount"],20)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/"state").mkdir()
            (root/"roadmap-projects.json").write_text(json.dumps(self.roadmap))
            (root/"state/run.json").write_text(json.dumps(run))
            (root/"state/old.json").write_text(json.dumps(self.history))
            result=subprocess.run([sys.executable,str(ROOT/"tools/daily_report.py"),"--root",str(root),
                "--ledger","state/run.json"],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            prepared=json.loads(result.stdout)
            (root/"state/sent.json").write_text(json.dumps(dict(run["gmail"],status="sent",messageId="abc123")))
            second=subprocess.run([sys.executable,str(ROOT/"tools/daily_report.py"),"--root",str(root),
                "--ledger","state/run.json"],capture_output=True,text=True)
            self.assertNotEqual(second.returncode,0)
            self.assertIn("already sent",second.stderr)
            (root/"state/sent.json").unlink()
            (root/"state/daily-results.csv").write_text("RunDate,Id,EmailStatus\n2026-10-11,21,sent:abc123\n")
            with self.assertRaisesRegex(ValidationError,"already sent"):
                prepare(run,self.roadmap,records_from_state(root))

if __name__=="__main__":unittest.main()
