"""Canary audit data is never authoritative operational input."""
import re
from tools.validate_execution_manifest import ValidationError
CANARY_PATH=re.compile(r"(?:state/)?control-cas-canary(?:-result)?-[0-9]{8}\.json$")
def reject_canary_inputs(value):
    def walk(node):
        if type(node) is dict:
            kind=node.get("kind","")
            if node.get("canary") is True or node.get("nonAuthoritative") is True or (
                type(kind) is str and kind.startswith("control_cas_canary")):
                raise ValidationError("canary audit is never authoritative lifecycle/evidence input")
            for key,item in node.items():
                if type(key) is str and CANARY_PATH.fullmatch(key):
                    raise ValidationError("canary path is not authoritative")
                walk(item)
        elif type(node) is list:
            for item in node:walk(item)
        elif type(node) is str and CANARY_PATH.fullmatch(node):
            raise ValidationError("canary path is not authoritative")
    walk(value)
