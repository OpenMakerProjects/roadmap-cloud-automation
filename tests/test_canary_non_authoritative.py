"""Canary rejection tests use offline synthetic lifecycle/evidence inputs."""
import copy
import json
from pathlib import Path
import unittest
import test_batch_lifecycle as lifecycle
from tools.batch_lifecycle import transition
from tools.completion_evidence import validate
from tools.non_authoritative import reject_canary_inputs
from tools.validate_execution_manifest import ValidationError
ROOT=Path(__file__).resolve().parents[1]
class CanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):lifecycle.BatchLifecycleTests.setUpClass()
    def setUp(self):
        self.helper=lifecycle.BatchLifecycleTests();self.helper.setUp()
        self.canary=json.loads((ROOT/"state/control-cas-canary-20261010.json").read_text())
    def test_real_canary_never_authoritative(self):
        with self.assertRaisesRegex(ValidationError,"canary"):reject_canary_inputs(self.canary)
        self.assertTrue(self.canary["nonAuthoritative"])
    def test_nested_markers_kinds_and_file_references(self):
        for value in ({"canary":True},{"nonAuthoritative":True},{"kind":"control_cas_canary","canary":False},
                      {"kind":"control_cas_canary_result"},{"proof":self.canary},
                      {"sourcePath":"state/control-cas-canary-20261010.json"},
                      {"state/control-cas-canary-result-20261010.json":{}},
                      ["control-cas-canary-20261010.json"]):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):reject_canary_inputs(value)
    def test_transition_rejects_canary_in_state_context_request(self):
        state=self.helper.begin()
        request=self.helper.request(state,"activate",projectID=21)
        for position in range(3):
            inputs=copy.deepcopy([state,self.helper.context,request])
            inputs[position]["auditProof"]=self.canary
            with self.assertRaisesRegex(ValidationError,"canary"):transition(*inputs)
    def test_completion_rejects_valid_fixture_polluted_by_canary(self):
        record,entry,plan=self.helper.helper.fixture(21)
        for position in range(3):
            values=copy.deepcopy([record,entry,plan]);values[position]["auditProof"]=self.canary
            with self.assertRaisesRegex(ValidationError,"canary"):validate(*values)
    def test_planning_marker_is_not_misclassified(self):
        state=self.helper.begin()
        reject_canary_inputs(state)
        self.assertTrue(state["nonAuthoritativePlanningOutput"])
if __name__=="__main__":unittest.main()
