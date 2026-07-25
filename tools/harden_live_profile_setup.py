from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "setup.py"
source = path.read_text(encoding="utf-8")

old = '''        await self.signature_view.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_ALLOWED_FIELDS_KEY: list(self.values)},
        )
        await self.signature_view.refresh(interaction)
'''
new = '''        await interaction.response.defer()
        await self.signature_view.cog.update_signature_config(
            guild.id,
            **{SIGNATURE_ALLOWED_FIELDS_KEY: list(self.values)},
        )
        signature_cog = self.signature_view.cog.bot.get_cog("ProfileSignatures")
        if signature_cog is not None and hasattr(
            signature_cog, "invalidate_guild_cards"
        ):
            await signature_cog.invalidate_guild_cards(guild)
        config = await self.signature_view.cog.get_signature_config(guild.id)
        view = SignatureSetupView(
            self.signature_view.cog,
            interaction.user.id,
            guild.id,
            config,
        )
        await interaction.edit_original_response(
            embed=await self.signature_view.cog.build_signature_panel(guild),
            view=view,
        )
'''
if source.count(old) != 1:
    raise RuntimeError(f"Expected one signature field callback, found {source.count(old)}")
source = source.replace(old, new, 1)

old = "        await interaction.response.defer(ephemeral=True)\n        await self.cog.update_signature_config(\n            guild.id,\n            **{SIGNATURE_ENABLED_KEY: False},\n        )"
new = "        await interaction.response.defer()\n        await self.cog.update_signature_config(\n            guild.id,\n            **{SIGNATURE_ENABLED_KEY: False},\n        )"
if source.count(old) != 1:
    raise RuntimeError(f"Expected one signature disable defer, found {source.count(old)}")
source = source.replace(old, new, 1)

path.write_text(source, encoding="utf-8")
