"""Static audit inventory; does not import the app or read environment files."""
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    endpoints = []
    for path in sorted((ROOT / "api").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
                prefix = next((k.value.value for k in node.keywords if k.arg == "prefix" and isinstance(k.value, ast.Constant)), "")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name) and dec.func.value.id in ("router", "app")
                        and dec.func.attr in ("get", "post", "put", "patch", "delete", "options", "head", "websocket")
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    endpoints.append({"method": dec.func.attr.upper(), "path": prefix + dec.args[0].value,
                                      "file": str(path.relative_to(ROOT)), "line": node.lineno, "handler": node.name})
    controls = []
    for path in sorted((ROOT / "web" / "src").rglob("*.tsx")):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<(button|input|select|textarea|a)\b([^>]*?)>", source, re.S):
            attrs = match.group(2)
            controls.append({"file": str(path.relative_to(ROOT)), "line": source[:match.start()].count("\n") + 1,
                             "element": match.group(1), "attributes": re.sub(r"\s+", " ", attrs).strip()[:500],
                             "verification": "Template inventory only; consult browser results for exercised controls."})
    result = {"endpoints": endpoints, "control_templates": controls,
              "limits": "Dynamic/map controls are templates, not unique visible controls. Legacy root components are inventoried but VersionRouter mounts v1/v2. This inventory does not claim complete browser coverage."}
    return result


if __name__ == "__main__":
    out = ROOT / ".audit" / "inventory.json"
    out.parent.mkdir(exist_ok=True)
    result = inventory()
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Inventoried {len(result['endpoints'])} route declarations and {len(result['control_templates'])} control templates.")
