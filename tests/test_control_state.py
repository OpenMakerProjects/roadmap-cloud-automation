"""Offline state invariants and append-only history regression tests."""
import copy
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.validate_control_state import validate_state, validate_files, BATCH
from tools.validate_execution_manifest import ValidationError, load_json

ROOT=Path(__file__).resolve().parents[1]
PATHS=["roadmap-projects.json","state/completion-verifications.json","state/active-lease.json",
       BATCH,"state/scheduler-readback-20261010.json","state/cloud-schedule-setup-20261006.json"]

class ControlStateTests(unittest.TestCase):
    def setUp(self):
        self.bundle=[load_json(ROOT/p) for p in PATHS]
        self.bundle.append(list(csv.DictReader(io.StringIO(
            (ROOT/"state/daily-results.csv").read_text()),strict=True)))

    def reject(self,mutate):
        bundle=copy.deepcopy(self.bundle); mutate(bundle)
        with self.assertRaises(ValidationError): validate_state(*bundle)

    def test_actual_state_offline(self):
        with patch("socket.socket",side_effect=AssertionError("network forbidden")):
            result=validate_files(ROOT)
        self.assertEqual(result["verifiedComplete"],20)
        self.assertEqual(result["selectedIDs"],list(range(21,41)))
        self.assertEqual(result["uniqueBatchGmailMessages"],1)

    def test_roadmap_integrity(self):
        self.reject(lambda b:b[0].pop())
        self.reject(lambda b:b[0].reverse())
        self.reject(lambda b:b[0][1].__setitem__("id",1))
        self.reject(lambda b:b[0][1].__setitem__("slug",b[0][0]["slug"]))

    def test_completion_keys_status_and_evidence(self):
        self.reject(lambda b:b[1].__setitem__("01",b[1]["1"]))
        self.reject(lambda b:b[1].__setitem__("2201",dict(b[1]["1"],id=2201)))
        self.reject(lambda b:b[1]["1"].__setitem__("status","published"))
        for field in ("id","verifiedComplete","merged","requiredMainTreeVerified","repository",
                      "mainCommit","headCommit","pr","tests","currentMainAudit"):
            with self.subTest(field=field): self.reject(lambda b:b[1]["1"].pop(field))
        for field in ("public","mainCommit","sourceTestsCI","transportChunksRemaining","imageGitBlob"):
            self.reject(lambda b:b[1]["1"]["currentMainAudit"].pop(field))
        self.reject(lambda b:b[1]["1"]["currentMainAudit"].__setitem__("transportChunksRemaining",1))
        self.reject(lambda b:b[1]["21"].__setitem__("status","verified_complete") if "21" in b[1]
                    else b[1].__setitem__("21",dict(b[1]["20"],id=21)))

    def test_lease_partition_lifecycle_and_totals(self):
        self.reject(lambda b:b[2]["completedIDs"].pop())
        self.reject(lambda b:b[2].__setitem__("remainingIDs",[20]))
        self.reject(lambda b:b[2].__setitem__("activeProject",21))
        self.reject(lambda b:b[2].__setitem__("status","unknown"))
        self.reject(lambda b:b[2].__setitem__("status","active"))
        self.reject(lambda b:b[2].__setitem__("releasedAtIST","bad"))
        for key,value in (("verifiedTotal",19),("remainingTotal",2200),("nextStartingID",22)):
            self.reject(lambda b:b[2].__setitem__(key,value))
        self.reject(lambda b:b[2]["completedIDs"].append(20))

    def test_batch_reconciliation_and_gmail(self):
        self.reject(lambda b:b[3]["projects"].pop())
        self.reject(lambda b:b[3]["finalMainAudit"][0].__setitem__("public",False))
        self.reject(lambda b:b[3]["totals"].__setitem__("nextStartingID",22))
        for index in (2,3):
            for field,value in (("status","pending"),("to","someone"),("cc",["x"]),
                                 ("bcc",["x"]),("messageId","different"),("reportReference","other")):
                self.reject(lambda b:b[index]["gmail"].__setitem__(field,value))
        self.reject(lambda b:b[1]["20"]["gmail"].__setitem__("messageId","deadbeef"))
        self.reject(lambda b:b[6][-1].__setitem__("EmailStatus","sent:deadbeef"))

    def test_reconciliation_rows_not_duplicate_sends(self):
        self.bundle[-1].append(copy.deepcopy(self.bundle[-1][-1]))
        result=validate_state(*self.bundle)
        self.assertEqual(result["uniqueBatchGmailMessages"],1)
        self.bundle[-1].append(dict(self.bundle[-1][-1],EmailStatus="sent:deadbeef"))
        with self.assertRaises(ValidationError): validate_state(*self.bundle)

    def test_scheduler_and_cloud_contract(self):
        for key,value in (("enabled",False),("paused",True),("timezone","UTC"),
                          ("recurrence","BEGIN:VEVENT\nRRULE:FREQ=DAILY;BYHOUR=5\nEND:VEVENT"),
                          ("source","memory"),("scheduleId","other")):
            self.reject(lambda b:b[4].__setitem__(key,value))
        self.reject(lambda b:b[5].__setitem__("execution","local executor"))
        self.reject(lambda b:b[5].__setitem__("enabled",False))

    def test_selector_alias_and_no_skipped_ids(self):
        from scripts.select_batch import select
        self.assertEqual([p["id"] for p in select(self.bundle[0],self.bundle[1])],
                         list(range(21,41)))
        with self.assertRaises(ValidationError):
            validate_state(*self.bundle,selector=lambda *args:self.bundle[0][21:41])
        self.reject(lambda b:b[1].pop("18"))

    def test_temp_fixture_manifest_drift_and_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for path,data in zip(PATHS,self.bundle):
                target=root/path; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(data))
            for path in ("state/execution-manifest-20261011-ids021-040.json",
                         "state/execution-manifest-20261011-ids021-040-qa.json",
                         "state/preflight-20261010-ids021-040.json"):
                (root/path).write_text((ROOT/path).read_text())
            (root/"state/daily-results.csv").write_text((ROOT/"state/daily-results.csv").read_text())
            self.assertTrue(validate_files(root)["valid"])
            path=root/"state/preflight-20261010-ids021-040.json"
            preflight=load_json(path)
            preflight["projects"][0]["mainHead"]="0"*40
            path.write_text(json.dumps(preflight))
            with self.assertRaises(ValidationError):validate_files(root)
            result=subprocess.run([sys.executable,str(ROOT/"tools/validate_control_state.py"),
                "--root",str(root)],capture_output=True,text=True,check=False)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("INVALID CONTROL STATE:",result.stderr)

if __name__=="__main__":unittest.main()
