from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if old not in source:
        raise SystemExit(f"Missing onboarding patch anchor: {label}")
    return source.replace(old, new, 1)


def patch(path_name: str, replacements: list[tuple[str, str, str]]) -> None:
    path = ROOT / path_name
    source = path.read_text(encoding="utf-8")
    for old, new, label in replacements:
        source = replace_once(source, old, new, f"{path_name}: {label}")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch(
        "onboarding.py",
        [
            (
                '        planted_at = float(plant.get("planted_at", now) or now)\n',
                '        raw_planted_at = plant.get("planted_at")\n'
                '        planted_at = now if raw_planted_at is None else float(raw_planted_at)\n',
                "preserve zero planted timestamp",
            )
        ],
    )

    patch(
        "tests/test_onboarding_runtime.py",
        [
            (
                '                "strain": "schwag",\n                "planted_at": 900,\n',
                '                "strain": "mexican brick",\n                "planted_at": 900,\n',
                "watering scenario uses longer grow",
            )
        ],
    )

    patch(
        "main.py",
        [
            (
                '    "notification_preferences",\n    "progression",',
                '    "notification_preferences",\n    "onboarding",\n    "progression",',
                "extension list",
            ),
            (
                'return await ctx.send(f"❌ Missing `{error.param.name}`. Try `!help` for usage.")',
                'return await ctx.send(f"❌ Missing `{error.param.name}`. Try `/help` for usage.")',
                "missing argument help",
            ),
            (
                'await bot.change_presence(activity=discord.Game(name="!help | Growing 🌿"))',
                'await bot.change_presence(activity=discord.Game(name="/help • /start • Growing 🌿"))',
                "ready presence",
            ),
        ],
    )

    patch(
        "tests/test_startup_contract.py",
        [
            (
                '    "notification_preferences",\n    "progression",',
                '    "notification_preferences",\n    "onboarding",\n    "progression",',
                "expected extensions",
            )
        ],
    )

    patch(
        "farming.py",
        [
            (
                'return await ctx.send("🌱 **Usage:** `!plant <strain name>` (e.g., `!plant og kush`)")',
                'return await ctx.send("🌱 **Usage:** `/plant strain_name:<strain>` (example: `/plant strain_name:schwag`)")',
                "plant usage",
            ),
            (
                'return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `!strains`.")',
                'return await ctx.send(f"❌ Unknown strain: **{clean_name}**. Check `/strains`.")',
                "strain lookup",
            ),
            (
                'f"❌ You don\'t have any **{clean_name.title()} Seeds**!\\nBuy some in the `!shop`."',
                'f"❌ You don\'t have any **{clean_name.title()} Seeds**!\\nUse `/shop`, then `/buy item_name:{seed_item_name}`."',
                "missing seed guidance",
            ),
            (
                '"⏳ **Nothing is ready to harvest yet.**\\nUse `!status` to check remaining time."',
                '"⏳ **Nothing is ready to harvest yet.**\\nUse `/status` to check remaining time."',
                "harvest timer guidance",
            ),
            (
                'description="Empty. Use `!plant` to start growing!",',
                'description="Empty. Use `/start` for your next step or `/plant` after buying a seed.",',
                "empty garden guidance",
            ),
            (
                'embed.set_footer(text=f"{ready_count} plants ready! Type !harvest")',
                'embed.set_footer(text=f"{ready_count} plants ready! Run /harvest")',
                "ready footer",
            ),
        ],
    )

    patch(
        "lab.py",
        [
            (
                'embed.set_footer(text="Use: !process [type] [amount] (e.g. !process wax 10)")',
                'embed.set_footer(text="Use /process concentrate_type:<type> amount:<amount> (example: wax, 10)")',
                "process usage",
            ),
            (
                'embed.set_footer(text="Use !collect when the batch is ready.")',
                'embed.set_footer(text="Use /collect when the batch is ready.")',
                "collect guidance",
            ),
            (
                'return await ctx.send("🧪 **No concentrates yet!** Use `!process` to make some.")',
                'return await ctx.send("🧪 **No concentrates yet!** Use `/process` to make some.")',
                "empty concentrate guidance",
            ),
        ],
    )

    patch(
        "quick.py",
        [
            (
                'embed.add_field(name="Status", value="`!q`  | `!cd`  | `!ready`", inline=False)',
                'embed.add_field(name="Status", value="`/quick` • `/cooldowns` • `/ready`", inline=False)',
                "quick status commands",
            ),
            (
                'embed.add_field(name="Progression", value="`!daily`  | `!quests`  | `!achievements`", inline=False)',
                'embed.add_field(name="Progression", value="`/growdaily` • `/growquests` • `/growachievements`", inline=False)',
                "quick progression commands",
            ),
            (
                'embed.add_field(name="Calculator", value="`!calc <strain>`", inline=False)',
                'embed.add_field(name="Calculator", value="`/calc strain:<strain>`", inline=False)',
                "quick calculator command",
            ),
            (
                'embed.add_field(name="Smart Plant", value="`!qplant` or `!qplant <count>`", inline=False)',
                'embed.add_field(name="Smart Plant", value="`/qplant` or `/qplant count:<number>`", inline=False)',
                "quick planting command",
            ),
            (
                'return await ctx.invoke(command) if command else await ctx.send("⚠️ `!ready` is unavailable.")',
                'return await ctx.invoke(command) if command else await ctx.send("⚠️ `/ready` is unavailable.")',
                "ready fallback",
            ),
            (
                'return await ctx.invoke(command) if command else await ctx.send("⚠️ `!profile` is unavailable.")',
                'return await ctx.invoke(command) if command else await ctx.send("⚠️ `/profile` is unavailable.")',
                "profile fallback",
            ),
        ],
    )

    patch(
        "tasks.py",
        [
            (
                '"!help | Build your empire",',
                '"/help • /start • Build your empire",',
                "rotating status",
            )
        ],
    )

    patch(
        "setup.py",
        [
            (
                '''        embed.add_field(
            name="Coming next",
            value="First-run onboarding",
            inline=False,
        )
''',
                '''        embed.add_field(
            name="Player Launch",
            value=(
                "Share `/start` for each player's tailored next move and `/help` for the "
                "compact command guide. Neither command changes server settings."
            ),
            inline=False,
        )
''',
                "player launch field",
            )
        ],
    )

    patch(
        ".github/workflows/ci.yml",
        [
            (
                "admin.py ai.py crime.py economy.py farming.py gambling.py lab.py notification_preferences.py progression.py quick.py sesh.py social.py tasks.py world_modes.py",
                "admin.py ai.py crime.py economy.py farming.py gambling.py lab.py notification_preferences.py onboarding.py progression.py quick.py sesh.py social.py tasks.py world_modes.py",
                "legacy cleanup module list",
            )
        ],
    )


if __name__ == "__main__":
    main()
