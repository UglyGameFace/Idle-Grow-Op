from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ai_keeps_chat_without_image_generation_surface():
    source = (ROOT / "ai.py").read_text(encoding="utf-8")

    assert '@commands.hybrid_command(name="chat"' in source
    assert 'name="imagine"' not in source
    assert 'aliases=["draw", "img"]' not in source
    assert "images/generations" not in source
    assert "AI_IMAGE_COST" not in source
    assert "_generate_image" not in source
    assert "_refund_image_cost" not in source
    assert "dall-e" not in source.lower()
