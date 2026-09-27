"""License-vetted strain artwork metadata.

Artwork is intentionally separate from game balance data. Entries are added only
when the underlying image has explicit reusable rights. The bot never scrapes
commercial strain sites or treats a dataset/repository license as permission to
redistribute third-party photography.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StrainArtwork:
    image_url: str
    source_url: str
    author: str
    license_name: str
    attribution_required: bool = False


_STRAIN_ARTWORK = {
    "og kush": StrainArtwork(
        image_url="https://upload.wikimedia.org/wikipedia/commons/3/37/OG_Kush.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:OG_Kush.jpg",
        author="Coaster420",
        license_name="Public Domain",
    ),
    "blue dream": StrainArtwork(
        image_url="https://upload.wikimedia.org/wikipedia/commons/f/f8/Sativa-Blue_Dream.jpg",
        source_url="https://commons.wikimedia.org/wiki/File:Sativa-Blue_Dream.jpg",
        author="Psychonaught",
        license_name="Public Domain",
    ),
    "sour diesel": StrainArtwork(
        image_url="https://upload.wikimedia.org/wikipedia/commons/0/0f/Sour-diesel.PNG",
        source_url="https://commons.wikimedia.org/wiki/File:Sour-diesel.PNG",
        author="Sam Sutch",
        license_name="Public Domain",
    ),
}

STRAIN_ARTWORK: Mapping[str, StrainArtwork] = MappingProxyType(_STRAIN_ARTWORK)


def normalize_strain_name(value: str) -> str:
    clean = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    if clean.endswith(" seed"):
        clean = clean[:-5].strip()
    return clean


def get_strain_artwork(strain_name: str) -> StrainArtwork | None:
    return STRAIN_ARTWORK.get(normalize_strain_name(strain_name))
