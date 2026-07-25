from pathlib import Path
import re


phase4 = Path(__file__).resolve().with_name("apply_world_mode_phase4.py")
if phase4.is_file():
    source = phase4.read_text(encoding="utf-8")
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
        raise RuntimeError("Could not replace temporary Phase 4 helper definitions")
    phase4.write_text(source, encoding="utf-8")
Path(__file__).unlink(missing_ok=True)
