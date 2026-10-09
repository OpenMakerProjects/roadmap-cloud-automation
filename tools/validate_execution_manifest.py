#!/usr/bin/env python3
"""Offline, fail-closed validation of the IDs21–40 planning bundle."""
import argparse
import json
import re
from pathlib import Path

MANIFEST = "state/execution-manifest-20261011-ids021-040.json"
QA = "state/execution-manifest-20261011-ids021-040-qa.json"
PREFLIGHT = "state/preflight-20261010-ids021-040.json"
FIELDS = ("id", "title", "slug", "category", "platform", "connectivity", "components", "scope")
REQUIREMENTS = {
    "finalHeadPushChecks": ["Validate", "Completion"],
    "sameHeadPRChecks": ["Validate", "Completion"],
    "oneProjectPR": True, "mergeExpectedHeadSHA": True,
    "verifyMainTree": True, "noTransportChunks": True,
    "persistDurableResult": True, "singleEndOfBatchGmail": True,
    "gmailTo": "me", "gmailCC": [], "gmailBCC": [],
}
RESTRICTIONS = {
    "onlyControlRepositoryWritten": True, "projectRepositoriesChanged": False,
    "buildLeaseAcquired": False, "branchesOrPRsCreated": False,
    "mergesPerformed": False, "finalImagesGenerated": False, "buildsRun": False,
    "emailSent": False, "schedulerChanged": False,
}
QA_RESTRICTIONS = {
    "buildLeaseAcquired": False, "projectRepositoryMutations": False,
    "branchesOrPRsCreated": False, "imagesGenerated": False, "buildsRun": False,
    "emailSent": False, "onlyControlRepositoryChanged": True, "activeLeaseUnchanged": True,
}
README = ["overview","objectives","features","architecture","platform","BOM quantities",
"prerequisites","exact pin map","circuit/wiring","assembly","setup","flashing/deployment",
"configuration","usage","telemetry/data formats","expected output","actual run test results",
"troubleshooting","limitations","domain safety","future work","contributing","full MIT license"]

class ValidationError(ValueError):
    pass

def require(ok, path):
    if not ok:
        raise ValidationError(path)

def text(value, path):
    require(type(value) is str and bool(value.strip()), path)

def texts(value, path):
    require(type(value) is list and bool(value), path)
    for i, item in enumerate(value):
        text(item, f"{path}[{i}]")

def obj(value, path):
    require(type(value) is dict, path)

def same(actual, expected, path):
    require(type(actual) is type(expected) and actual == expected, path)

def flags(actual, expected, path):
    obj(actual, path)
    for key, value in expected.items():
        same(actual.get(key), value, f"{path}.{key}")

def unique_index(rows, path):
    require(type(rows) is list, path)
    out = {}
    for row in rows:
        obj(row, path)
        ident = row.get("id")
        require(type(ident) is int and ident not in out, path + ".id")
        out[ident] = row
    return out

def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, str(path) + ": duplicate JSON key " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValidationError(str(path) + ": non-finite JSON number " + value)
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=pairs, parse_constant=constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(str(path) + ": " + str(exc)) from exc

def validate(manifest, qa, roadmap, preflight):
    obj(manifest, "manifest"); obj(qa, "qa"); obj(preflight, "preflight")
    same(manifest.get("schemaVersion"), 1, "manifest.schemaVersion")
    same(manifest.get("type"), "planning_only_execution_manifest", "manifest.type")
    same(manifest.get("status"), "proposed_not_executed", "manifest.status")
    same(qa.get("schemaVersion"), 1, "qa.schemaVersion")
    same(qa.get("kind"), "read_only_project_qa_control_only_corrections", "qa.kind")
    same(preflight.get("schemaVersion"), 1, "preflight.schemaVersion")
    ids = list(range(21, 41))
    same(manifest.get("selectedIDs"), ids, "manifest.selectedIDs")
    same(manifest.get("recommendedProcessingOrder"), ids, "manifest.order")
    same(qa.get("selectedIDs"), ids, "qa.selectedIDs")
    same(preflight.get("selectedIDs"), ids, "preflight.selectedIDs")
    rmap = unique_index(roadmap, "roadmap")
    pmap = unique_index(preflight.get("projects"), "preflight.projects")
    plans = manifest.get("projects"); qrows = qa.get("projects")
    require(type(plans) is list and len(plans) == 20, "manifest.projects.count")
    require(type(qrows) is list and len(qrows) == 20, "qa.projects.count")
    same([p.get("id") for p in plans if type(p) is dict], ids, "manifest.projects.order")
    same([p.get("id") for p in qrows if type(p) is dict], ids, "qa.projects.order")
    deps = manifest.get("dependencyCatalog"); gates = manifest.get("targetGateCatalog")
    obj(deps, "dependencyCatalog"); obj(gates, "targetGateCatalog")
    require(bool(deps) and bool(gates), "catalogs.empty")
    for catalog in (deps, gates):
        for key, value in catalog.items():
            text(key, "catalog.key"); obj(value, "catalog." + key)
            require(bool(value), "catalog." + key + ".empty")
    same(manifest.get("readmeRequiredSections"), README, "readmeRequiredSections")
    for p, q in zip(plans, qrows):
        ident = p["id"]; prefix = f"project[{ident}]"
        require(ident in rmap and ident in pmap, prefix + ".sources")
        r, pf = rmap[ident], pmap[ident]
        for key in FIELDS:
            same(p.get(key), r.get(key), prefix + "." + key)
        same(p.get("keyDeliverable"), r.get("deliverable"), prefix + ".keyDeliverable")
        same(p.get("roadmapEntry"), r, prefix + ".roadmapEntry")
        same(p.get("currentMainSHA"), pf.get("mainHead"), prefix + ".currentMainSHA")
        require(bool(re.fullmatch(r"[0-9a-f]{40}", p["currentMainSHA"])), prefix + ".SHAformat")
        same(p.get("existingEntrypoint"), pf.get("entrypoint"), prefix + ".existingEntrypoint")
        same(p.get("repository"), pf.get("repository"), prefix + ".repository")
        for key in ("intendedEntrypoint", "generatedImageBrief", "projectSpecificTemplateWarning"):
            text(p.get(key), prefix + "." + key)
        for key in ("plannedBehavior", "safetyConstraints", "proposedHostTests", "implementationFactsToVerify", "dependencies"):
            texts(p.get(key), prefix + "." + key)
        for dep in p["dependencies"]:
            require(dep in deps, prefix + ".unknownDependency:" + dep)
        same(p.get("dependencyCatalogRef"), "dependencyCatalog", prefix + ".dependencyCatalogRef")
        gate = p.get("actualTargetGate"); obj(gate, prefix + ".actualTargetGate")
        ref = gate.get("catalogRef"); require(type(ref) is str and ref in gates, prefix + ".unknownTargetGate")
        texts(gates[ref].get("commands"), "targetGateCatalog." + ref + ".commands")
        texts(gates[ref].get("requirements"), "targetGateCatalog." + ref + ".requirements")
        texts(gate.get("extraGates"), prefix + ".extraGates")
        circuit = p.get("circuitArchitecture"); obj(circuit, prefix + ".circuitArchitecture")
        same(circuit.get("svgPath"), "docs/circuit-diagram.svg", prefix + ".svgPath")
        text(circuit.get("topology"), prefix + ".topology")
        texts(circuit.get("pinPowerFactsToVerify"), prefix + ".pinPower")
        same(p.get("generatedImageRequirementsRef"), "generatedImageRequirements", prefix + ".imageRef")
        readme = p.get("readmeChecklist"); obj(readme, prefix + ".README")
        same(readme.get("commonSectionsRef"), "readmeRequiredSections", prefix + ".readmeRef")
        text(readme.get("projectSpecific"), prefix + ".readmeSpecific")
        text(readme.get("additionalEvidence"), prefix + ".readmeEvidence")
        same(q.get("slug"), p["slug"], prefix + ".qaSlug")
        require(q.get("disposition") in ("corrected", "pass"), prefix + ".qaDisposition")
        texts(q.get("corrections"), prefix + ".qaCorrections")
        texts(q.get("residualFacts"), prefix + ".qaResidualFacts")
    flags(manifest.get("executionRequirements"), REQUIREMENTS, "executionRequirements")
    flags(manifest.get("planningRestrictions"), RESTRICTIONS, "planningRestrictions")
    flags(qa.get("restrictionsObserved"), QA_RESTRICTIONS, "qa.restrictions")
    texts(manifest.get("perProjectFinalGate"), "perProjectFinalGate")
    require(len(manifest["perProjectFinalGate"]) == 6, "perProjectFinalGate.count")
    final = " ".join(manifest["perProjectFinalGate"])
    for token in ("exact head", "push", "PR", "exactly one", "expected_head_sha", "main", ".b64", "durable"):
        require(token in final, "perProjectFinalGate missing " + token)
    reporting = manifest.get("batchReporting"); obj(reporting, "batchReporting")
    for key in ("when", "account", "subject", "delivery", "schedule"):
        text(reporting.get(key), "batchReporting." + key)
    require("Exactly one HTML Gmail" in reporting["when"], "singleGmail")
    require("message ID" in reporting["delivery"] and "reconcile" in reporting["delivery"], "gmailReconciliation")
    readiness = qa.get("readiness"); obj(readiness, "qa.readiness")
    require(type(readiness.get("readyForUnattendedImplementation")) is bool, "qa.readiness.implementation")
    same(readiness.get("readyForMerge"), False, "qa.readiness.merge")
    text(readiness.get("condition"), "qa.readiness.condition")
    same(qa.get("manifestPath"), MANIFEST, "qa.manifestPath")
    same(manifest.get("qaReportPath"), QA, "qaReportPath")
    image = manifest.get("generatedImageRequirements"); obj(image, "image")
    same(image.get("output"), "docs/images/project-overview.png", "image.output")
    same(image.get("executed"), False, "image.executed")
    text(image.get("constraints"), "image.constraints")
    return {"selectedIDs": ids, "projectCount": len(plans), "valid": True}

def validate_files(root):
    root = Path(root)
    return validate(load_json(root / MANIFEST), load_json(root / QA),
                    load_json(root / "roadmap-projects.json"), load_json(root / PREFLIGHT))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        print(json.dumps(validate_files(args.root), sort_keys=True))
    except (ValidationError, KeyError, TypeError) as exc:
        parser.exit(1, "INVALID: " + str(exc) + "\n")

if __name__ == "__main__":
    main()
