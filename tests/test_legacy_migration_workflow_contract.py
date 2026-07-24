from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "migrate-legacy-data.yml"
HOME_GUILD_ID = "1514374173517152418"


def test_migration_workflow_defaults_to_safe_dry_run():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "default: dry-run" in source
    assert "- dry-run" in source
    assert "- apply" in source
    assert f'default: "{HOME_GUILD_ID}"' in source


def test_apply_requires_exact_home_guild_and_confirmation():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert f'HOME_GUILD_ID: "{HOME_GUILD_ID}"' in source
    assert 'inputs.guild_id }}" != "$HOME_GUILD_ID"' in source
    assert 'inputs.confirmation }}" != "MIGRATE $HOME_GUILD_ID"' in source
    assert "args+=(--apply)" in source


def test_workflow_uses_idle_grow_service_role_secrets_only():
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "secrets.IDLE_SUPABASE_URL" in source
    assert "secrets.IDLE_SUPABASE_SERVICE_ROLE_KEY" in source
    assert "secrets.SUPABASE_URL" not in source
    assert "secrets.SUPABASE_SERVICE_ROLE_KEY" not in source
    assert "IDLE_SUPABASE_KEY" not in source
    assert "permissions:\n  contents: read" in source
    assert "cancel-in-progress: false" in source
