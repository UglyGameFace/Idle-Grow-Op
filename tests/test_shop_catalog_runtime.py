from pathlib import Path

from crime import Crime
from progression_core import claim_daily
from utils import SHOP_ITEMS


ROOT = Path(__file__).resolve().parents[1]


def test_shop_does_not_sell_unimplemented_placeholder_systems():
    removed = {
        "premium nutes",
        "greenhouse",
        "harvest bot",
        "aqua globe",
        "burner phone",
        "fake id",
        "bribe pack",
        "ice bath",
        "repair kit",
    }
    assert removed.isdisjoint(SHOP_ITEMS)
    assert all("!appeal" not in item.get("description", "") for item in SHOP_ITEMS.values())
    assert all("!bail" not in item.get("description", "") for item in SHOP_ITEMS.values())


def test_shop_descriptions_match_live_passive_mechanics():
    assert SHOP_ITEMS["nutes"]["type"] == "tool"
    assert "50%" in SHOP_ITEMS["nutes"]["description"]
    assert "10%" in SHOP_ITEMS["lights"]["description"]
    assert "20%" in SHOP_ITEMS["led lights"]["description"]
    assert "+50%" in SHOP_ITEMS["led lights"]["description"]
    assert "+100%" in SHOP_ITEMS["hydroponic"]["description"]
    assert "15" in SHOP_ITEMS["cam"]["description"]
    assert "25" in SHOP_ITEMS["dog"]["description"]


def test_pager_applies_exact_twenty_percent_daily_multiplier(monkeypatch):
    import progression_core as progression

    monkeypatch.setattr(progression, "_today", lambda now=None: "2026-09-22")
    monkeypatch.setattr(progression, "_yesterday", lambda now=None: "2026-09-21")

    profile = {"level": 5, "xp": 0, "grams": 0}
    result = claim_daily(profile, user_id=1, reward_multiplier=1.20)

    assert result["cash"] == int((400 + 5 * 45) * 1.02 * 1.20)
    assert result["xp"] == int((80 + 5 * 8) * 1.02 * 1.20)


def test_pager_is_wired_into_the_public_daily_command():
    source = (ROOT / "progression.py").read_text(encoding="utf-8")
    assert 'reward_multiplier=1.20 if has_item(profile, "pager") else 1.0' in source


def test_lawyer_reduces_jail_sentences_by_twenty_five_percent():
    assert Crime._jail_duration_seconds({"items": {}}, 400) == 400
    assert Crime._jail_duration_seconds({"items": {"lawyer": 1}}, 400) == 300


def test_passive_tools_and_defenses_cannot_be_bought_repeatedly():
    source = (ROOT / "economy.py").read_text(encoding="utf-8")
    assert 'item.get("type") in {"equipment", "tool", "defense"}' in source
    assert 'inv_get(user, clean_name) > 0' in source
