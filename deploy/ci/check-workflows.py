"""Least-privilege lint for GitHub Actions workflows (stdlib only, no YAML parser needed for these rules).

Every workflow must declare a top-level `permissions:` block, must not use `write-all`, must not use the
`pull_request_target` trigger, and every third-party `uses:` must be pinned to a full 40-character commit SHA.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows"
errors = []
for wf in sorted(root.glob("*.y*ml")):
    text = wf.read_text(encoding="utf-8")
    if not re.search(r"^permissions:", text, re.M):
        errors.append(f"{wf.name}: no top-level 'permissions:' block")
    if "write-all" in text:
        errors.append(f"{wf.name}: uses 'write-all' permissions")
    if re.search(r"^\s*pull_request_target\s*:", text, re.M):
        errors.append(f"{wf.name}: uses pull_request_target")
    for m in re.finditer(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", text, re.M):
        ref = m.group(1)
        if ref.startswith("./"):
            continue
        if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref):
            errors.append(f"{wf.name}: action not pinned to a commit SHA: {ref}")
for e in errors:
    print(f"::error::{e}")
print(f"checked {len(list(root.glob('*.y*ml')))} workflow(s): {'FAIL' if errors else 'OK'}")
sys.exit(1 if errors else 0)
