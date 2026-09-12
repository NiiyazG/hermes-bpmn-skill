#!/usr/bin/env python3
import importlib, shutil, sys
mods={"lxml":"lxml","Pillow":"PIL","PyMuPDF":"fitz"}
ok=True
print("Hermes BPMN Diagramming — environment check")
for label,mod in mods.items():
    try:
        importlib.import_module(mod)
        found=True
    except Exception as exc:
        found=False
        print(f"- {label}: MISSING ({exc})")
    else:
        print(f"- {label}: OK")
    ok &= found
ink=shutil.which("inkscape")
print(f"- Inkscape (EPS): {ink or 'MISSING — EPS will be skipped'}")
print("STATUS:","PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
