"""Mocked persistence transports only; no network, real lease or credential."""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_batch_lifecycle as lifecycle_fixtures
from tools.control_persistence import prepare,execute,blob_sha,READ_PATHS,LEASE,OWNER,REPO,BRANCH
from tools.batch_lifecycle import transition,digest
from tools.validate_execution_manifest import ValidationError

ROOT=Path(__file__).resolve().parents[1]

def file(content,mode="100644"):
    return {"sha":blob_sha(content),"mode":mode,"content":content}

class MockAdapter:
    atomic_expected_head_supported=True
    def __init__(self,snapshot):
        self.current=copy.deepcopy(snapshot);self.writes=[];self.fail=False
        self.race=False;self.bad_readback=False;self.bad_parent=False;self.login="shrutikbalwan"
    def snapshot(self,owner,repo,branch):
        assert (owner,repo,branch)==(OWNER,REPO,BRANCH)
        return copy.deepcopy(self.current)
    def authenticated_login(self):return self.login
    def atomic_commit(self,operation):
        self.writes.append(copy.deepcopy(operation))
        data=operation["variables"]["input"]
        if self.race:self.current["refSHA"]="e"*40
        if self.fail or self.current["refSHA"]!=data["expectedHeadOid"]:
            raise RuntimeError("mock transport secret=DO_NOT_PRINT")
        expected=self.current["refSHA"];self.current["refSHA"]="d"*40
        for addition in data["fileChanges"]["additions"]:
            content=base64.b64decode(addition["contents"],validate=True).decode()
            self.current["files"][addition["path"]]=file(content)
        if self.bad_readback:
            self.current["files"][LEASE]=file("{}")
        return {"commitSHA":"d"*40,"refSHA":"d"*40,
                "parents":["e"*40] if self.bad_parent else [expected]}

class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lifecycle_fixtures.BatchLifecycleTests.setUpClass()
        cls.source={p:(ROOT/p).read_text(encoding="utf-8") for p in (*READ_PATHS,LEASE)}

    def setUp(self):
        self.helper=lifecycle_fixtures.BatchLifecycleTests();self.helper.setUp()
        self.snapshot={"owner":OWNER,"repo":REPO,"branch":BRANCH,"refSHA":"a"*40,
            "treeSHA":"b"*40,"files":{p:file(c) for p,c in self.source.items()}}
        self.operation=self.make(self.helper.prior,"begin",nowIST="2026-10-11T04:00:00+05:30",
            expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011")

    def change(self,path,new):
        old=self.snapshot["files"].get(path)
        prior=json.loads(old["content"]) if old else None
        return {"path":path,"expectedBlobSHA":old["sha"] if old else None,
            "expectedDigest":digest(prior),"expectedRevision":prior.get("revision",0) if prior else 0,
            "content":json.dumps(new,sort_keys=True)}

    def make(self,state,action,**extra):
        self.snapshot["files"][LEASE]=file(json.dumps(state))
        request=self.helper.request(state,action,**extra)
        bundle={"state":state,"context":self.helper.context,"request":request}
        proposed=transition(state,self.helper.context,request)["state"]
        return {"schemaVersion":1,"owner":OWNER,"repo":REPO,"branch":BRANCH,
            "expectedMainSHA":self.snapshot["refSHA"],"message":"Persist validated control transition",
            "transition":bundle,"changes":[self.change(LEASE,proposed)]}

    def reject(self,operation=None,snapshot=None):
        with self.assertRaises((ValidationError,ValueError,KeyError,TypeError)):
            prepare(operation or self.operation,snapshot or self.snapshot)

    def test_default_dry_run_and_real_manifests_offline(self):
        adapter=MockAdapter(self.snapshot)
        with patch("socket.socket",side_effect=AssertionError("network forbidden")):
            plan=execute(self.operation,adapter)
        self.assertTrue(plan["dryRun"]);self.assertEqual(adapter.writes,[])
        self.assertEqual(plan["atomicConnectorOperation"]["variables"]["input"]["expectedHeadOid"],"a"*40)
        self.assertFalse(plan["force"]);self.assertFalse(plan["authorOverride"])
        self.assertEqual(plan["deletions"],[])
        self.assertEqual((ROOT/LEASE).read_text(encoding="utf-8"),self.source[LEASE])

    def test_stale_ref_blob_digest_revision_and_absence(self):
        for key,value in (("expectedBlobSHA","0"*40),("expectedDigest","0"*64),("expectedRevision",8),
                          ("expectedBlobSHA",None)):
            bad=copy.deepcopy(self.operation);bad["changes"][0][key]=value;self.reject(bad)
        snapshot=copy.deepcopy(self.snapshot);snapshot["refSHA"]="e"*40;self.reject(snapshot=snapshot)
        snapshot=copy.deepcopy(self.snapshot);snapshot["files"][LEASE]["sha"]="0"*40;self.reject(snapshot=snapshot)

    def test_scope_paths_and_unapproved_options(self):
        for key,value in (("owner","other"),("repo","other"),("branch","feature"),("force",True),
                          ("author",{"name":"spoof"})):
            bad=copy.deepcopy(self.operation);bad[key]=value;self.reject(bad)
        for path in ("state/../active-lease.json","/state/active-lease.json","state/%2e%2e/x.json",
                     "state\\active-lease.json","AGENTS.md","state/daily-results.csv","state/not-allowed.json"):
            bad=copy.deepcopy(self.operation);bad["changes"][0]["path"]=path;self.reject(bad)

    def test_binary_oversize_json_secrets_and_schema(self):
        for content in ("not-json","{}",'{"a":1,"a":2}','{"a":NaN}',json.dumps({"authorization":"redacted"}),
                        json.dumps({"x":"ghp_"+"a"*30}),"{}\0",json.dumps({"x":"a"*2_000_000})):
            bad=copy.deepcopy(self.operation);bad["changes"][0]["content"]=content;self.reject(bad)
        bad=copy.deepcopy(self.operation);bad["changes"][0]["content"]=b"{}";self.reject(bad)
        bad=copy.deepcopy(self.operation);bad["schemaVersion"]=2;self.reject(bad)
        snapshot=copy.deepcopy(self.snapshot);snapshot["files"][LEASE]["mode"]="120000";self.reject(snapshot=snapshot)
        snapshot=copy.deepcopy(self.snapshot);snapshot["files"]["state"]={"mode":"120000"};self.reject(snapshot=snapshot)

    def test_snapshot_context_drift_and_unvalidated_new_state(self):
        bad=copy.deepcopy(self.operation);bad["transition"]["context"]["plans"][0]["title"]="wrong";self.reject(bad)
        bad=copy.deepcopy(self.operation);new=json.loads(bad["changes"][0]["content"]);new["totals"]["verifiedTotal"]=99
        bad["changes"][0]["content"]=json.dumps(new);self.reject(bad)
        bad=copy.deepcopy(self.operation);bad["transition"]["request"]["expectedStateDigest"]="0"*64;self.reject(bad)

    def test_absent_lease_uses_durable_validated_baseline(self):
        request=self.helper.request(None,"begin",nowIST="2026-10-11T04:00:00+05:30",
            expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011")
        del self.snapshot["files"][LEASE]
        self.operation["transition"]["state"]=None
        self.operation["transition"]["request"]=request
        new=transition(None,self.helper.context,request)["state"]
        self.operation["changes"]=[self.change(LEASE,new)]
        self.assertTrue(prepare(self.operation,self.snapshot)["dryRun"])

    def test_report_intent_and_ledger_atomic_and_invalid_ledger(self):
        terminal=self.helper.terminal_batch(False)
        operation=self.make(terminal,"report-intent")
        new=json.loads(operation["changes"][0]["content"])
        report=new["report"]
        intent="state/report-intent-"+report["reportReference"]+".json"
        ledger="state/run-20261011-batch021-040.json"
        operation["changes"] += [self.change(intent,report),self.change(ledger,report["ledger"])]
        plan=prepare(operation,self.snapshot)
        self.assertEqual(len(plan["changes"]),3)
        adapter=MockAdapter(self.snapshot)
        self.assertTrue(execute(operation,adapter,apply=True,protected_runtime=True)["readbackVerified"])
        bad=copy.deepcopy(operation);value=json.loads(bad["changes"][2]["content"]);value["totals"]["verifiedComplete"]=100
        bad["changes"][2]["content"]=json.dumps(value);self.reject(bad)
        bad=copy.deepcopy(operation);bad["changes"][1]["path"]="state/report-intent-WRONG.json";self.reject(bad)

    def test_multifile_atomic_evidence_plan(self):
        active=self.helper.apply(self.helper.begin(),"activate",projectID=21)
        evidence=self.helper.helper.fixture(21)[0]
        operation=self.make(active,"checkpoint",projectID=21,status="verified_complete",evidence=evidence)
        path="state/completion-evidence/id021.json"
        operation["changes"].append(self.change(path,evidence))
        plan=prepare(operation,self.snapshot)
        additions=plan["atomicConnectorOperation"]["variables"]["input"]["fileChanges"]["additions"]
        self.assertEqual([a["path"] for a in additions],[LEASE,path])
        adapter=MockAdapter(self.snapshot)
        result=execute(operation,adapter,apply=True,protected_runtime=True)
        self.assertTrue(result["readbackVerified"]);self.assertEqual(len(adapter.writes),1)
        self.assertEqual(json.loads(adapter.current["files"][path]["content"]),evidence)
        bad=copy.deepcopy(operation);bad["changes"].append(copy.deepcopy(bad["changes"][0]));self.reject(bad)
        bad=copy.deepcopy(operation);bad["changes"][1]["expectedBlobSHA"]="0"*40;self.reject(bad)

    def test_apply_requires_explicit_flag_protected_auth_and_atomic_adapter(self):
        for alteration in ("runtime","login","capability"):
            adapter=MockAdapter(self.snapshot)
            if alteration=="login":adapter.login="other"
            if alteration=="capability":adapter.atomic_expected_head_supported=False
            with self.assertRaises(ValidationError):
                execute(self.operation,adapter,apply=True,protected_runtime=alteration!="runtime")
            self.assertEqual(adapter.writes,[])

    def test_update_failure_competing_writer_no_retry_no_secret_echo(self):
        for failure in ("fail","race"):
            adapter=MockAdapter(self.snapshot);setattr(adapter,failure,True)
            with self.assertRaises(ValidationError) as error:
                execute(self.operation,adapter,apply=True,protected_runtime=True)
            self.assertNotIn("DO_NOT_PRINT",str(error.exception));self.assertIsNone(error.exception.__cause__)
            self.assertEqual(len(adapter.writes),1)
            self.assertEqual(adapter.current["files"],self.snapshot["files"])

    def test_success_readback_and_uncertain_readback_no_retry(self):
        adapter=MockAdapter(self.snapshot)
        result=execute(self.operation,adapter,apply=True,protected_runtime=True)
        self.assertEqual(result["commitSHA"],"d"*40);self.assertTrue(result["readbackVerified"])
        with self.assertRaises(ValidationError):execute(self.operation,adapter,apply=True,protected_runtime=True)
        self.assertEqual(len(adapter.writes),1)
        for failure in ("bad_readback","bad_parent"):
            adapter=MockAdapter(self.snapshot);setattr(adapter,failure,True)
            with self.assertRaises(ValidationError):execute(self.operation,adapter,apply=True,protected_runtime=True)
            self.assertEqual(len(adapter.writes),1)

    def test_cli_defaults_plan_symlink_and_no_builtin_apply_adapter(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"request.json"
            path.write_text(json.dumps({"operation":self.operation,"snapshot":self.snapshot}))
            command=[sys.executable,str(ROOT/"tools/control_persistence.py"),"--input",str(path)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)["dryRun"])
            # Inspect refusal guard; never invoke the CLI --apply flag in this task.
            self.assertIn('require(not args.apply', (ROOT/"tools/control_persistence.py").read_text())
            link=Path(temp)/"symlink.json"
            try:link.symlink_to(path)
            except OSError:self.skipTest("symlink creation unavailable on this host")
            result=subprocess.run(command[:-1]+[str(link)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)

if __name__=="__main__":unittest.main()
