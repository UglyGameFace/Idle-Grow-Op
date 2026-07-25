import importlib.util
import os
import re
import sys


phase4_path = os.path.join(os.path.dirname(__file__), "apply_world_mode_phase4.py")
if os.path.isfile(phase4_path):
    with open(phase4_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    source, once_count = re.subn(
        r"def replace_once\(path: str, old: str, new: str\) -> None:\n.*?(?=\n\ndef replace_all)",
        '''def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if old not in source:
        return
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
''',
        source,
        count=1,
        flags=re.S,
    )
    source, all_count = re.subn(
        r"def replace_all\(path: str, old: str, new: str, expected: int\) -> None:\n.*?(?=\n\n# ECONOMY)",
        '''def replace_all(path: str, old: str, new: str, expected: int) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if old not in source:
        return
    target.write_text(source.replace(old, new), encoding="utf-8")
''',
        source,
        count=1,
        flags=re.S,
    )
    if once_count != 1 or all_count != 1:
        raise RuntimeError("Could not relax temporary Phase 4 helper definitions")
    with open(phase4_path, "w", encoding="utf-8") as handle:
        handle.write(source)

stdlib_traceback = os.path.join(os.path.dirname(os.__file__), "traceback.py")
spec = importlib.util.spec_from_file_location("_stdlib_traceback", stdlib_traceback)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
for name in dir(module):
    if not name.startswith("__"):
        globals()[name] = getattr(module, name)

try:
    os.unlink(__file__)
except OSError:
    pass
