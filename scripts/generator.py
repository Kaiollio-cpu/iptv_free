"""
generator.py - M3U Playlist Generator for IPTV Auto Updater.

Generates standards-compliant, UTF-8 encoded M3U playlists with
atomic file writing, empty playlist safeguards, and strict categorization.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Set

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


class M3UGenerator:
    """Generates and writes IPTV M3U playlists."""

    def __init__(self, output_path: str = "main.m3u") -> None:
        self.output_path = output_path

    @staticmethod
    def generate_content(channels: List[Dict[str, Any]]) -> str:
        """
        Generate M3U formatted text string from list of channels.
        Enforces category order and alphabetical sorting within each category.
        """
        lines = ["#EXTM3U"]

        # Group channels by canonical category
        grouped: Dict[str, List[Dict[str, Any]]] = {
            cat: [] for cat in CANONICAL_CATEGORIES
        }
        for ch in channels:
            cat = ch.get("category", "Outros")
            if cat not in grouped:
                cat = "Outros"
            grouped[cat].append(ch)

        seen_urls: Set[str] = set()

        for category in CANONICAL_CATEGORIES:
            cat_channels = grouped[category]
            # Sort alphabetically by channel name
            cat_channels.sort(key=lambda c: c.get("name", "").lower())

            for ch in cat_channels:
                url = ch.get("url", "").strip()
                name = ch.get("name", "").strip()
                tvg_id = ch.get("tvg_id", "").strip()
                tvg_name = ch.get("tvg_name", name).strip()
                tvg_logo = ch.get("tvg_logo", "").strip()

                # Safety checks
                if not url or url in seen_urls:
                    continue
                if not (url.startswith("http://") or url.startswith("https://")):
                    continue

                seen_urls.add(url)

                # Format standard:
                # #EXTINF:-1 tvg-id="canal.exemplo" tvg-name="Canal Exemplo" tvg-logo="https://..." group-title="Canais Abertos",Canal Exemplo
                extinf = (
                    f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" '
                    f'tvg-logo="{tvg_logo}" group-title="{category}",{name}'
                )
                lines.append(extinf)
                lines.append(url)

        return "\n".join(lines) + "\n"

    def write_playlist(self, channels: List[Dict[str, Any]]) -> bool:
        """
        Write channels to output file with atomic guarantees and empty result protection.
        Returns True on success, False if skipped due to safety checks.
        """
        if not channels:
            logger.error(
                "Refusing to generate empty playlist. Existing '%s' will be preserved.",
                self.output_path,
            )
            return False

        content = self.generate_content(channels)

        # Check that we generated more than just #EXTM3U
        valid_entries = sum(1 for line in content.splitlines() if line.startswith("#EXTINF:"))
        if valid_entries == 0:
            logger.error(
                "No valid #EXTINF entries generated. Preserving existing '%s'.",
                self.output_path,
            )
            return False

        # Atomic write: write to temp file in same directory then rename
        target_dir = os.path.dirname(os.path.abspath(self.output_path))
        os.makedirs(target_dir, exist_ok=True)

        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix="main_m3u_",
            suffix=".tmp",
            dir=target_dir,
            text=True,
        )

        try:
            with open(tmp_fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replacement
            os.replace(tmp_path, self.output_path)
            logger.info(
                "Atomically updated '%s' with %d valid channels.",
                self.output_path,
                valid_entries,
            )
            return True
        except Exception as exc:
            logger.error("Failed to write atomic playlist: %s", exc)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False
