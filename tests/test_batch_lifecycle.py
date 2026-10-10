"""Pure proposal tests using synthetic future evidence; never acquire a lease."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import test_completion_evidence as evidence_fixtures
from tools.batch_lifecycle import transition,digest
from tools.propose_batch import propose
from tools.validate_execution_manifest import ValidationError,load_json

ROOT=Path(__file__).resolve().parents[1]

class BatchLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence_fixtures.CompletionEvidenceTests.setUpClass()

    def setUp(self):
        manifest=load_json(ROOT/"state/execution-manifest-20261011-ids021-040.json")
        self.context={"roadmap":load_json(ROOT/"roadmap-projects.json"),
            "historicalCompletions":load_json(ROOT/"state/completion-verifications.json"),
            "authoritativeEvidence":[],"plans":manifest["projects"],"manifest":manifest,
            "preflight":load_json(ROOT/"state/preflight-20261010-ids021-040.json"),
            "durableReports":[load_json(ROOT/"state/run-20261010-batch001-020.json")]}
        self.prior=load_json(ROOT/"state/active-lease.json")
        self.counter=0
        self.helper=evidence_fixtures.CompletionEvidenceTests()

    def request(self,state,action,**extra):
        self.counter+=1
        request={"action":action,"requestId":"request-"+str(self.counter),
            "nowIST":"2026-10-11T05:10:00+05:30",
            "owner":state["owner"] if state and state.get("kind")=="batch_lifecycle_proposal" else "test-owner-a",
            "expectedStateDigest":digest(state),"expectedContextDigest":digest(self.context),
            "expectedRevision":state.get("revision",0) if state else 0}
        request.update(extra);return request

    def begin(self,prior=None):
        prior=self.prior if prior is None else prior
        request=self.request(prior,"begin",nowIST="2026-10-11T04:00:00+05:30",
            expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011")
        return transition(prior,self.context,request)["state"]

    def apply(self,state,action,**extra):
        return transition(state,self.context,self.request(state,action,**extra))["state"]

    def terminal_batch(self,success=True):
        state=self.begin()
        for ident in range(21,41):
            state=self.apply(state,"activate",projectID=ident)
            if success:
                evidence=self.helper.fixture(ident)[0]
                state=self.apply(state,"checkpoint",projectID=ident,status="verified_complete",evidence=evidence)
            else:state=self.apply(state,"checkpoint",projectID=ident,status="blocked",blocker="Synthetic CI outage")
        return state

    def receipt(self,state):
        report=state["report"]
        return {key:copy.deepcopy(report[key]) for key in
            ("reportReference","htmlSha256","subject","to","resolvedProfile","cc","bcc")} | {
            "status":"sent","messageId":"abc123","labelIds":["SENT"],
            "sentAtIST":"2026-10-11T05:11:00+05:30"}

    def test_actual_begin_proposal_and_absent_lease_are_pure(self):
        before=copy.deepcopy(self.prior)
        with patch("socket.socket",side_effect=AssertionError("network forbidden")):
            output=propose(ROOT,"2026-10-11T04:00:00+05:30","dry-run-owner")
        self.assertTrue(output["planningOnly"])
        self.assertEqual(output["proposal"]["state"]["remainingIDs"],list(range(21,41)))
        self.assertEqual(self.prior,before)
        request=self.request(None,"begin",nowIST="2026-10-11T04:00:00+05:30",
            expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011")
        self.assertEqual(transition(None,self.context,request)["state"]["totals"]["verifiedTotal"],20)

    def test_competing_writers_stale_digest_revision_context(self):
        state=self.begin()
        a=self.request(state,"activate",projectID=21)
        b=self.request(state,"activate",projectID=21)
        newer=transition(state,self.context,a)["state"]
        with self.assertRaisesRegex(ValidationError,"stale"):transition(newer,self.context,b)
        for key,value in (("expectedStateDigest","0"*64),("expectedRevision",999),("expectedContextDigest","0"*64)):
            bad=dict(a);bad[key]=value
            with self.assertRaises(ValidationError):transition(state,self.context,bad)

    def test_unexpired_rejected_expired_takeover_preserves_progress(self):
        state=self.begin()
        state=self.apply(state,"activate",projectID=21)
        state=self.apply(state,"checkpoint",projectID=21,status="verified_complete",evidence=self.helper.fixture(21)[0])
        request=self.request(state,"begin",owner="new-owner",nowIST="2026-10-11T06:00:00+05:30",
            expiresAtIST="2026-10-11T10:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(22,42)),runReference="OMP-021-040-20261011")
        with self.assertRaisesRegex(ValidationError,"unexpired"):transition(state,self.context,request)
        request["nowIST"]="2026-10-11T08:01:00+05:30"
        request["expiresAtIST"]="2026-10-11T12:01:00+05:30"
        out=transition(state,self.context,request)["state"]
        self.assertEqual(out["completedIDs"],[21])
        self.assertEqual(out["remainingIDs"],list(range(22,41)))
        self.assertEqual(out["owner"],"new-owner")
        self.assertEqual(len(out["history"]),len(state["history"])+1)

    def test_selection_plan_and_unique_owner_guards(self):
        for extra in ({"selectedIDs":list(range(22,42))},
                      {"selectorOutput":list(range(22,42))},
                      {"owner":self.prior["owner"]},{"owner":self.prior["previousOwner"]}):
            request=self.request(self.prior,"begin",nowIST="2026-10-11T04:00:00+05:30",
                expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
                selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011")
            request.update(extra)
            with self.assertRaises(ValidationError):transition(self.prior,self.context,request)
        context=copy.deepcopy(self.context);context["preflight"]["projects"][0]["mainHead"]="0"*40
        request=self.request(self.prior,"begin",nowIST="2026-10-11T04:00:00+05:30",
            expiresAtIST="2026-10-11T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261011",
            expectedContextDigest=digest(context))
        with self.assertRaises(ValidationError):transition(self.prior,context,request)

    def test_partial_checkpoint_invalid_evidence_duplicate_completion(self):
        state=self.begin();active=self.apply(state,"activate",projectID=21)
        with self.assertRaises(ValidationError):self.apply(active,"activate",projectID=22)
        evidence=self.helper.fixture(21)[0];bad=copy.deepcopy(evidence);bad["checks"][0]["head"]="0"*40
        with self.assertRaises(ValidationError):
            self.apply(active,"checkpoint",projectID=21,status="verified_complete",evidence=bad)
        newer=self.apply(active,"checkpoint",projectID=21,status="verified_complete",evidence=evidence)
        self.assertEqual((newer["totals"]["verifiedTotal"],newer["totals"]["remainingTotal"],newer["totals"]["nextStartingID"]),(21,2179,22))
        self.assertEqual(newer["completedIDs"],[21])
        with self.assertRaises(ValidationError):
            self.apply(newer,"checkpoint",projectID=21,status="verified_complete",evidence=evidence)

    def test_crash_retry_exact_idempotency_and_changed_payload(self):
        state=self.begin();request=self.request(state,"activate",projectID=21)
        newer=transition(state,self.context,request)["state"]
        replay=transition(newer,self.context,request)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["state"],newer)
        changed=dict(request,projectID=22)
        with self.assertRaises(ValidationError):transition(newer,self.context,changed)

    def test_report_requires_all_terminal_and_no_duplicate_intent(self):
        state=self.begin()
        with self.assertRaises(ValidationError):self.apply(state,"report-intent")
        done=self.terminal_batch()
        intent=self.apply(done,"report-intent")
        self.assertEqual(intent["report"]["to"],"me")
        self.assertEqual((intent["report"]["cc"],intent["report"]["bcc"]),([],[]))
        with self.assertRaises(ValidationError):self.apply(intent,"report-intent")
        with self.assertRaises(ValidationError):self.apply(intent,"release")

    def test_sent_reconciliation_and_successful_release(self):
        state=self.apply(self.terminal_batch(),"report-intent")
        receipt=self.receipt(state)
        bad=dict(receipt,htmlSha256="0"*64)
        with self.assertRaises(ValidationError):
            self.apply(state,"reconcile-sent",receipt=bad,nowIST="2026-10-11T05:11:00+05:30")
        sent=self.apply(state,"reconcile-sent",receipt=receipt,nowIST="2026-10-11T05:11:00+05:30")
        again=self.apply(sent,"reconcile-sent",receipt=receipt,nowIST="2026-10-11T05:11:00+05:30")
        self.assertEqual(again["report"]["messageId"],"abc123")
        released=self.apply(again,"release",nowIST="2026-10-11T05:12:00+05:30")
        self.assertEqual(released["status"],"completed")
        self.assertEqual(released["remainingIDs"],[])
        self.assertEqual(released["totals"],{"verifiedTotal":40,"remainingTotal":2160,"nextStartingID":41})

    def test_zero_success_valid_failure_release_keeps_delivery_pending(self):
        state=self.apply(self.terminal_batch(False),"report-intent")
        failed=self.apply(state,"release",path="zero_success_failure_report",
                          nowIST="2026-10-11T05:12:00+05:30")
        self.assertEqual(failed["status"],"expired")
        self.assertTrue(failed["deliveryPending"])
        self.assertEqual(failed["remainingIDs"],list(range(21,41)))
        self.assertEqual(failed["totals"]["verifiedTotal"],20)
        request=self.request(failed,"begin",owner="new-owner",nowIST="2026-10-12T04:00:00+05:30",
            expiresAtIST="2026-10-12T08:00:00+05:30",selectedIDs=list(range(21,41)),
            selectorOutput=list(range(21,41)),runReference="OMP-021-040-20261012")
        with self.assertRaisesRegex(ValidationError,"unresolved"):transition(failed,self.context,request)

    def test_partition_regression_and_cli_temp_fixture(self):
        state=self.begin()
        corrupted=copy.deepcopy(state);corrupted["completedIDs"]=[21]
        request=self.request(corrupted,"activate",projectID=21)
        with self.assertRaises(ValidationError):transition(corrupted,self.context,request)
        request=self.request(state,"activate",projectID=21)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"input.json"
            path.write_text(json.dumps({"state":state,"context":self.context,"request":request}))
            result=subprocess.run([sys.executable,str(ROOT/"tools/batch_lifecycle.py"),"--input",str(path)],
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)["state"]["activeProject"],21)

if __name__=="__main__":unittest.main()
