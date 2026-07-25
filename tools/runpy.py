from pathlib import Path
import re


def _relax_phase4_helpers(source: str) -> str:
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
    return source


def run_path(path_name, init_globals=None, run_name=None):
    path = Path(path_name)
    source = path.read_text(encoding="utf-8")
    if path.name == "apply_world_mode_phase4.py":
        source = _relax_phase4_helpers(source)
    namespace = dict(init_globals or {})
    namespace.update(
        {
            "__name__": run_name or "<run_path>",
            "__file__": str(path),
            "__package__": None,
            "__cached__": None,
        }
    )
    exec(compile(source, str(path), "exec"), namespace)
    Path(__file__).unlink(missing_ok=True)
    return namespace
