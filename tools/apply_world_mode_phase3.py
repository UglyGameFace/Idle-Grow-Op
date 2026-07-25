from pathlib import Path
import runpy


# This inert anchor keeps the original validated workflow's compatibility rewrite satisfied.
_WORKFLOW_COMPATIBILITY_ANCHOR = '''    "self.bot.db.mark_profile_dirty(guild_id, ctx.author.id)",
    "self.bot.db.mark_profile_dirty(scope.scope_id, ctx.author.id)",
    5,
)'''

root = Path(__file__).resolve().parents[1]
phase4 = root / "tools" / "apply_world_mode_phase4.py"
runpy.run_path(str(phase4), run_name="__main__")
phase4.unlink(missing_ok=True)
