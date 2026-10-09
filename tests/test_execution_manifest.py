"""Offline regression tests: real planning bundle plus isolated temporary fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools.validate_execution_manifest import (MANIFEST, QA, PREFLIGHT, REQUIREMENTS,
    RESTRICTIONS, QA_RESTRICTIONS, ValidationError, load_json, validate, validate_files)

ROOT = Path(__file__).resolve().parents[1]

class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.bundle = [load_json(ROOT / p) for p in
                       (MANIFEST, QA, "roadmap-projects.json", PREFLIGHT)]

    def test_actual_bundle_without_network(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = validate(*self.bundle)
        self.assertTrue(result["valid"])
        self.assertEqual(result["projectCount"], 20)

    def reject(self, mutate):
        bundle = copy.deepcopy(self.bundle)
        mutate(bundle)
        with self.assertRaises(ValidationError):
            validate(*bundle)

    def test_schema_status_and_selection(self):
        for i, key, value in [(0,"schemaVersion",2),(0,"schemaVersion",True),
            (0,"type","execution"),(0,"status","complete"),(1,"schemaVersion",2),
            (1,"kind","other"),(3,"schemaVersion",2)]:
            with self.subTest(i=i,key=key,value=value):
                self.reject(lambda b: b[i].__setitem__(key,value))
        for i, key in [(0,"selectedIDs"),(0,"recommendedProcessingOrder"),
                       (1,"selectedIDs"),(3,"selectedIDs")]:
            for value in [list(range(22,42)),[21]*20,list(range(40,20,-1)),list(range(21,40))]:
                with self.subTest(i=i,key=key,value=value):
                    self.reject(lambda b: b[i].__setitem__(key,value))

    def test_counts_project_order_and_duplicates(self):
        for i in (0,1):
            self.reject(lambda b: b[i]["projects"].pop())
            self.reject(lambda b: b[i]["projects"].reverse())
            self.reject(lambda b: b[i]["projects"].__setitem__(1,b[i]["projects"][0]))
        self.reject(lambda b: b[2].append(b[2][0]))
        self.reject(lambda b: b[3]["projects"].append(b[3]["projects"][0]))

    def test_roadmap_and_preflight_drift(self):
        for key in ("id","title","slug","category","platform","connectivity","components","scope","keyDeliverable"):
            with self.subTest(key=key):
                self.reject(lambda b: b[0]["projects"][0].__setitem__(key,[] if key=="components" else "drift"))
        for key in ("currentMainSHA","existingEntrypoint","repository","roadmapEntry"):
            with self.subTest(key=key):
                self.reject(lambda b: b[0]["projects"][0].__setitem__(key,"drift"))

    def test_required_project_content(self):
        for key in ("intendedEntrypoint","generatedImageBrief","projectSpecificTemplateWarning",
                    "plannedBehavior","safetyConstraints","proposedHostTests",
                    "implementationFactsToVerify","dependencies","actualTargetGate","circuitArchitecture","readmeChecklist"):
            with self.subTest(key=key):
                self.reject(lambda b: b[0]["projects"][0].pop(key))
        for parent, key in [("circuitArchitecture","pinPowerFactsToVerify"),
            ("circuitArchitecture","topology"),("circuitArchitecture","svgPath"),
            ("readmeChecklist","projectSpecific"),("readmeChecklist","additionalEvidence"),
            ("readmeChecklist","commonSectionsRef"),("actualTargetGate","extraGates")]:
            with self.subTest(parent=parent,key=key):
                self.reject(lambda b: b[0]["projects"][0][parent].pop(key))
        self.reject(lambda b: b[0].__setitem__("readmeRequiredSections",["overview"]))
        self.reject(lambda b: b[0]["generatedImageRequirements"].__setitem__("executed",True))

    def test_unknown_or_empty_catalogs(self):
        for key in ("dependencyCatalogRef","generatedImageRequirementsRef"):
            self.reject(lambda b: b[0]["projects"][0].__setitem__(key,"unknown"))
        self.reject(lambda b: b[0]["projects"][0]["dependencies"].append("unknown"))
        self.reject(lambda b: b[0]["projects"][0]["actualTargetGate"].__setitem__("catalogRef","unknown"))
        self.reject(lambda b: b[0]["targetGateCatalog"]["esphomeESP32"].__setitem__("commands",[]))
        self.reject(lambda b: b[0]["dependencyCatalog"].__setitem__("esphome",{}))
        self.reject(lambda b: b[0]["dependencyCatalog"]["esphome"].__setitem__("scope",""))

    def test_execution_requirements_fail_closed(self):
        for key in REQUIREMENTS:
            with self.subTest(key=key):
                self.reject(lambda b: b[0]["executionRequirements"].pop(key))
        self.reject(lambda b: b[0].__setitem__("perProjectFinalGate",[]))
        for index in range(6):
            with self.subTest(final_gate=index):
                self.reject(lambda b: b[0]["perProjectFinalGate"].pop(index))
        self.reject(lambda b: b[0]["batchReporting"].__setitem__("when","Send reports"))
        self.reject(lambda b: b[0]["batchReporting"].__setitem__("delivery","Send again"))

    def test_restrictions_and_qa_coverage(self):
        for index,parent,expected in [(0,"planningRestrictions",RESTRICTIONS),
                                       (1,"restrictionsObserved",QA_RESTRICTIONS)]:
            for key,value in expected.items():
                with self.subTest(parent=parent,key=key):
                    self.reject(lambda b: b[index][parent].pop(key))
                    self.reject(lambda b: b[index][parent].__setitem__(key,not value))
        self.reject(lambda b: b[1]["comparison"].__setitem__("roadmapEntries",19))
        self.reject(lambda b: b[1].pop("readiness"))
        self.reject(lambda b: b[1]["readiness"].__setitem__("readyForMerge",True))
        self.reject(lambda b: b[1]["readiness"].__setitem__("condition",""))
        for key in ("disposition","corrections","residualFacts","slug"):
            self.reject(lambda b: b[1]["projects"][0].pop(key))

    def test_temporary_fixtures_and_invalid_json_cli(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path,data in zip((MANIFEST,QA,"roadmap-projects.json",PREFLIGHT),self.bundle):
                destination=root/path
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_text(json.dumps(data),encoding="utf-8")
            self.assertTrue(validate_files(root)["valid"])
            for invalid in ('{', '{"schemaVersion":1,"schemaVersion":1}', '{"x":NaN}'):
                (root/MANIFEST).write_text(invalid,encoding="utf-8")
                with self.assertRaises(ValidationError):
                    validate_files(root)
                result=subprocess.run([sys.executable,str(ROOT/"tools/validate_execution_manifest.py"),
                    "--root",str(root)],capture_output=True,text=True,check=False)
                self.assertNotEqual(result.returncode,0)
                self.assertIn("INVALID:",result.stderr)

if __name__ == "__main__":
    unittest.main()
