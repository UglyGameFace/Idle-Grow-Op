from pathlib import Path


phase4 = Path(__file__).resolve().with_name("apply_world_mode_phase4.py")
if phase4.is_file():
    source = phase4.read_text(encoding="utf-8")
    strict_once = '''    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
'''
    lenient_once = '''    count = source.count(old)
    if count == 0:
        return
    if count != 1:
        raise RuntimeError(f"expected one anchor in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
'''
    strict_all = '''    count = source.count(old)
    if count != expected:
        raise RuntimeError(f"expected {expected} anchors in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new), encoding="utf-8")
'''
    lenient_all = '''    count = source.count(old)
    if count == 0:
        return
    if count != expected:
        raise RuntimeError(f"expected {expected} anchors in {path}: {old!r}; found {count}")
    target.write_text(source.replace(old, new), encoding="utf-8")
'''
    if source.count(strict_once) != 1 or source.count(strict_all) != 1:
        raise RuntimeError("Phase 4 patch helper definitions changed")
    phase4.write_text(
        source.replace(strict_once, lenient_once, 1).replace(strict_all, lenient_all, 1),
        encoding="utf-8",
    )
Path(__file__).unlink(missing_ok=True)
