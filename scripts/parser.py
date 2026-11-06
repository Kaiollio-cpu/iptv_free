"""
parser.py - Channel Parser and Normalizer for IPTV Auto Updater.

Normalizes channel data, categorizes streams according to required standards,
deduplicates entries, resolves authorized public streams, and enforces compliance.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

CANONICAL_CATEGORIES = [
    "Canais Abertos",
    "Esportes",
    "Filmes e Séries",
    "Documentários",
    "Infantil",
    "Notícias",
    "Entretenimento",
    "Outros",
]

# Mapping category variations to canonical names
CATEGORY_MAPPING = {
    "canais abertos": "Canais Abertos",
    "abertos": "Canais Abertos",
    "aberto": "Canais Abertos",
    "general": "Canais Abertos",
    "culture": "Canais Abertos",
    "esportes": "Esportes",
    "esporte": "Esportes",
    "sports": "Esportes",
    "filmes e séries": "Filmes e Séries",
    "filmes e series": "Filmes e Séries",
    "filmes": "Filmes e Séries",
    "séries": "Filmes e Séries",
    "series": "Filmes e Séries",
    "movies": "Filmes e Séries",
    "classic": "Filmes e Séries",
    "documentários": "Documentários",
    "documentarios": "Documentários",
    "documentary": "Documentários",
    "infantil": "Infantil",
    "kids": "Infantil",
    "animation": "Infantil",
    "desenhos": "Infantil",
    "notícias": "Notícias",
    "noticias": "Notícias",
    "news": "Notícias",
    "entretenimento": "Entretenimento",
    "entertainment": "Entretenimento",
    "variedades": "Entretenimento",
    "music": "Entretenimento",
    "música": "Entretenimento",
    "comedy": "Entretenimento",
}

# Paywall / Subscription channels that cannot be broadcast publicly without authorization
PAYWALL_RESTRICTED_KEYWORDS = [
    "telecine", "premiere", "combate", "hbo", "paramount+", "megapix",
    "universal tv", "studio universal", "sony channel", "sony movies",
    "cinemax", "space", "warner tv", "usa", "sportv", "discovery science",
    "discovery theater", "discovery world", "discovery turbo", "gloob",
    "gloobinho", "multishow", "gnt", "bis", "canal off", "modo viagem"
]


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing, stripping accents, and removing non-alphanumeric chars."""
    if not text:
        return ""
    # remove resolution tags and brackets
    text = re.sub(r"\s*\(\d+p\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\[.*?\]", "", text)
    # decompose unicode accents
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # keep only alphanumeric
    return re.sub(r"[^a-zA-Z0-9]", "", without_accents).lower()


def detect_protocol(url: str) -> str:
    """Detect streaming protocol based on URL."""
    clean_url = url.split("?")[0].lower()
    if clean_url.endswith(".m3u8"):
        return "HLS"
    if clean_url.endswith(".ts"):
        return "MPEG-TS"
    if clean_url.endswith(".mpd"):
        return "DASH"
    return "HLS"


def standardize_tvg_id(channel_id: str, name: str) -> str:
    """Generate a clean, consistent tvg-id identifier."""
    base = channel_id or name
    slug = re.sub(r"[^a-zA-Z0-9]+", ".", base).strip(".").lower()
    if not slug.endswith(".br"):
        slug = f"{slug}.br"
    return slug


class ChannelParser:
    """Parses and organizes channels from collected data."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def map_category(raw_category: str) -> str:
        """Map raw category string to one of the 8 canonical categories."""
        if not raw_category:
            return "Outros"
        cleaned = raw_category.strip().lower()
        if cleaned in CATEGORY_MAPPING:
            return CATEGORY_MAPPING[cleaned]
        # Partial match
        for key, canonical in CATEGORY_MAPPING.items():
            if key in cleaned:
                return canonical
        return "Outros"

    @staticmethod
    def is_paywall_restricted(name: str) -> bool:
        """Check if channel is a known pay-TV / DRM-restricted channel."""
        norm = normalize_text(name)
        for keyword in PAYWALL_RESTRICTED_KEYWORDS:
            if normalize_text(keyword) in norm:
                return True
        return False

    def build_channel_catalog(
        self,
        reference_channels: List[Dict[str, Any]],
        public_streams: List[Dict[str, str]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Build the unified catalog by matching reference channels with verified public streams.
        Returns:
            (eligible_channels, excluded_channels)
        """
        # Index public streams by normalized name
        public_index: Dict[str, List[Dict[str, str]]] = {}
        for stream in public_streams:
            s_name = stream.get("name", "")
            s_tvg_name = stream.get("tvg_name", "")
            s_tvg_id = stream.get("tvg_id", "")

            keys = {
                normalize_text(s_name),
                normalize_text(s_tvg_name),
                normalize_text(s_tvg_id),
            }
            for k in keys:
                if k:
                    public_index.setdefault(k, []).append(stream)

        eligible: List[Dict[str, Any]] = []
        excluded: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()

        for ref in reference_channels:
            raw_id = ref.get("id", "")
            name = ref.get("name", "").strip()
            raw_cat = ref.get("category", "")
            logo = ref.get("logo_url", "")
            category = self.map_category(raw_cat)
            tvg_id = standardize_tvg_id(raw_id, name)
            origin = f"https://reidoscanais.my/canal/{raw_id}"

            # Check if this channel requires paywall / DRM / circumvention
            if self.is_paywall_restricted(name):
                excluded.append({
                    "id": raw_id,
                    "name": name,
                    "category": category,
                    "reason": "Canal fechado/pago ou com DRM (bloqueado por conformidade legal)",
                    "origin": origin,
                })
                continue

            # Look for matched verified public stream
            norm_name = normalize_text(name)
            norm_id = normalize_text(raw_id)
            matched_streams = public_index.get(norm_name) or public_index.get(norm_id) or []

            stream_url = None
            for candidate in matched_streams:
                url = candidate.get("url", "").strip()
                if url and url not in seen_urls:
                    stream_url = url
                    if not logo and candidate.get("tvg_logo"):
                        logo = candidate.get("tvg_logo")
                    break

            if stream_url:
                seen_urls.add(stream_url)
                eligible.append({
                    "id": raw_id,
                    "name": name,
                    "category": category,
                    "tvg_id": tvg_id,
                    "tvg_name": name,
                    "tvg_logo": logo,
                    "url": stream_url,
                    "protocol": detect_protocol(stream_url),
                    "origin": origin,
                    "status": "pending_validation",
                    "consecutive_failures": 0,
                    "is_authorized": True,
                })
            else:
                excluded.append({
                    "id": raw_id,
                    "name": name,
                    "category": category,
                    "reason": "Nenhuma fonte pública/autorizada verificada disponível",
                    "origin": origin,
                })

        logger.info(
            "Parser matched %d eligible channels and excluded %d channels.",
            len(eligible),
            len(excluded),
        )
        return eligible, excluded

    def organize_and_sort(self, channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Organize channels strictly by canonical categories order,
        and alphabetically by name within each category.
        Removes duplicates.
        """
        # Deduplicate by url and name
        unique_channels: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()
        seen_names: Set[str] = set()

        for ch in channels:
            url = ch.get("url", "")
            name = ch.get("name", "")
            if not url or url in seen_urls:
                continue
            if name in seen_names:
                continue
            seen_urls.add(url)
            seen_names.add(name)
            unique_channels.append(ch)

        # Group by category
        grouped: Dict[str, List[Dict[str, Any]]] = {
            cat: [] for cat in CANONICAL_CATEGORIES
        }
        for ch in unique_channels:
            cat = ch.get("category", "Outros")
            if cat not in grouped:
                cat = "Outros"
            grouped[cat].append(ch)

        # Sort alphabetically within each category
        ordered_list: List[Dict[str, Any]] = []
        for cat in CANONICAL_CATEGORIES:
            channels_in_cat = grouped[cat]
            channels_in_cat.sort(key=lambda x: x.get("name", "").lower())
            ordered_list.extend(channels_in_cat)

        return ordered_list
