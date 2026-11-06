"""
main.py - Main Pipeline Orchestrator for IPTV Auto Updater.

Executes:
1. Reference channel catalog discovery (reidoscanais.my)
2. Authorized public streams matching and compliance filtering
3. Asynchronous stream validation with temporary failure tolerance
4. Atomic M3U playlist generation
5. Metrics calculation and audit reporting
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import sys
from typing import Any, Dict, List, Set, Tuple

from collector import ChannelCollector
from parser import ChannelParser
from validator import StreamValidator
from generator import M3UGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("iptv_updater")


def extract_channels_from_m3u(file_path: str) -> Dict[str, str]:
    """Extract mapping of {channel_name: stream_url} from an existing M3U file."""
    if not os.path.exists(file_path):
        return {}
    channels: Dict[str, str] = {}
    current_name = None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#EXTINF:"):
                    current_name = line.split(",")[-1].strip() if "," in line else ""
                elif line and not line.startswith("#"):
                    if current_name:
                        channels[current_name] = line
                        current_name = None
    except Exception as exc:
        logger.warning("Error reading previous M3U at %s: %s", file_path, exc)
    return channels


def compare_playlists(
    old_channels: Dict[str, str],
    new_channels: List[Dict[str, Any]],
) -> Tuple[List[str], List[str], List[str]]:
    """Compare previous and new channels to identify additions, removals, and URL updates."""
    old_names = set(old_channels.keys())
    new_map = {c.get("name", ""): c.get("url", "") for c in new_channels if c.get("name")}
    new_names = set(new_map.keys())

    added = sorted(list(new_names - old_names))
    removed = sorted(list(old_names - new_names))
    modified = []

    for name in old_names & new_names:
        if old_channels[name] != new_map[name]:
            modified.append(name)

    return added, removed, sorted(modified)


def write_github_step_summary(metrics: Dict[str, Any]) -> None:
    """Write formatted summary report to GitHub Actions GITHUB_STEP_SUMMARY if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    markdown = f"""
## 📺 Relatório de Atualização IPTV Auto Updater

| Métrica | Valor |
|---|---|
| **Início da Execução** | `{metrics['start_time']}` |
| **Término da Execução** | `{metrics['end_time']}` |
| **Duração** | `{metrics['duration']}` |
| **Canais Identificados no Site** | **{metrics['total_identified']}** |
| **Fontes Autorizadas Descobertas** | **{metrics['total_authorized_found']}** |
| **Canais Aptos / Validados** | **{metrics['total_valid']}** |
| **Canais Indisponíveis / Excluídos** | **{metrics['total_unavailable']}** |
| **Canais Adicionados** | **{len(metrics['added'])}** |
| **Canais Removidos** | **{len(metrics['removed'])}** |
| **Canais com URL Atualizada** | **{len(metrics['modified'])}** |
| **Status da Playlist** | `{metrics['playlist_status']}` |

### 📋 Detalhes das Alterações:
- **Novos canais ({len(metrics['added'])}):** {", ".join(metrics['added']) if metrics['added'] else "Nenhum"}
- **Canais removidos ({len(metrics['removed'])}):** {", ".join(metrics['removed']) if metrics['removed'] else "Nenhum"}
- **Canais modificados ({len(metrics['modified'])}):** {", ".join(metrics['modified']) if metrics['modified'] else "Nenhum"}

> [!NOTE]
> Sistema em conformidade com as diretrizes legais e éticas: canais pagos, paywalls e restrições DRM são respeitados e ignorados na geração da playlist pública.
"""
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(markdown)
    except Exception as exc:
        logger.warning("Could not write GITHUB_STEP_SUMMARY: %s", exc)


async def run_pipeline(
    m3u_path: str = "main.m3u",
    state_file: str = "data/channel_status.json",
) -> int:
    """Main execution pipeline."""
    start_dt = datetime.datetime.now(datetime.timezone.utc)
    logger.info("=====================================================")
    logger.info("IPTV Auto Updater Pipeline Starting at %s UTC", start_dt.isoformat())
    logger.info("=====================================================")

    # 1. Read existing M3U for diff comparison
    old_channels = extract_channels_from_m3u(m3u_path)
    logger.info("Loaded %d channels from existing '%s'", len(old_channels), m3u_path)

    # 2. Collect from reference endpoints
    collector = ChannelCollector()
    collected = await collector.collect_all()
    ref_channels = collected.get("reference_channels", [])
    public_streams = collected.get("public_streams", [])

    total_identified = len(ref_channels)
    total_public_pool = len(public_streams)
    logger.info(
        "Collector returned %d reference channels and %d public stream candidates.",
        total_identified,
        total_public_pool,
    )

    # 3. Parse, match, and organize
    parser = ChannelParser()
    eligible, excluded = parser.build_channel_catalog(ref_channels, public_streams)
    organized = parser.organize_and_sort(eligible)

    # 4. Asynchronously validate streams
    validator = StreamValidator(state_file=state_file)
    active_channels, inactive_channels = await validator.validate_all(organized)

    # 5. Final organization and sorting of active channels
    final_channels = parser.organize_and_sort(active_channels)

    # 6. Generate M3U playlist atomically
    generator = M3UGenerator(output_path=m3u_path)
    success = generator.write_playlist(final_channels)
    playlist_status = "Atualizada com sucesso" if success else "Preservada versão anterior"

    # 7. Compare results
    added, removed, modified = compare_playlists(old_channels, final_channels)

    end_dt = datetime.datetime.now(datetime.timezone.utc)
    duration_str = str(end_dt - start_dt)

    metrics = {
        "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "duration": duration_str,
        "total_identified": total_identified,
        "total_authorized_found": len(eligible),
        "total_valid": len(final_channels),
        "total_unavailable": len(excluded) + len(inactive_channels),
        "added": added,
        "removed": removed,
        "modified": modified,
        "playlist_status": playlist_status,
    }

    logger.info("=====================================================")
    logger.info("Pipeline Summary:")
    logger.info("  Start: %s | End: %s (Duration: %s)", metrics["start_time"], metrics["end_time"], duration_str)
    logger.info("  Channels Identified: %d", total_identified)
    logger.info("  Authorized Sources Found: %d", len(eligible))
    logger.info("  Valid Active Channels: %d", len(final_channels))
    logger.info("  Unavailable/Excluded: %d", metrics["total_unavailable"])
    logger.info("  Added: %d, Removed: %d, Modified: %d", len(added), len(removed), len(modified))
    logger.info("  Playlist Write Status: %s", playlist_status)
    logger.info("=====================================================")

    write_github_step_summary(metrics)
    return 0 if success else 1


def main() -> None:
    """Entry point."""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m3u_path = os.path.join(root_dir, "main.m3u")
    state_file = os.path.join(root_dir, "data", "channel_status.json")

    exit_code = asyncio.run(run_pipeline(m3u_path=m3u_path, state_file=state_file))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
