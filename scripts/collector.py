"""
collector.py - Channel Collector for IPTV Auto Updater.

Discovers and catalogs IPTV channels from the reference site (reidoscanais.my)
and official/authorized public streaming repositories.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional
import aiohttp

logger = logging.getLogger(__name__)

# Reference endpoints
API_CHANNELS_URL = "https://api.reidoscanais.my/channels"
HTML_CANAIS_URL = "https://reidoscanais.my/canais"
PUBLIC_STREAMS_BR_URL = "https://iptv-org.github.io/iptv/countries/br.m3u"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ChannelCollector:
    """Collects channel metadata and stream candidates from reference endpoints."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        request_timeout: int = 15,
        rate_limit_delay: float = 0.5,
    ) -> None:
        self.session = session
        self.request_timeout = request_timeout
        self.rate_limit_delay = rate_limit_delay
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def _get(self, url: str) -> Optional[str]:
        """Fetch content via GET with timeout and error handling."""
        close_session = False
        session = self.session
        if session is None:
            session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.request_timeout),
            )
            close_session = True

        try:
            if self.rate_limit_delay > 0:
                await asyncio.sleep(self.rate_limit_delay)

            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    return await response.text(encoding="utf-8", errors="ignore")
                logger.warning("GET %s returned status %d", url, response.status)
                return None
        except Exception as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            return None
        finally:
            if close_session:
                await session.close()

    async def fetch_reference_catalog(self) -> List[Dict[str, Any]]:
        """
        Fetch channel catalog from reference site.
        Prefers official API (https://api.reidoscanais.my/channels),
        falling back to parsing HTML / Next.js payload if needed.
        """
        logger.info("Fetching channel catalog from API: %s", API_CHANNELS_URL)
        api_text = await self._get(API_CHANNELS_URL)

        if api_text:
            try:
                payload = json.loads(api_text)
                if payload.get("success") and isinstance(payload.get("data"), list):
                    channels = payload["data"]
                    logger.info("Successfully fetched %d channels via API.", len(channels))
                    return channels
            except json.JSONDecodeError as exc:
                logger.warning("Failed to decode API JSON: %s. Falling back to HTML.", exc)

        logger.info("Attempting fallback HTML scraping on %s", HTML_CANAIS_URL)
        html_text = await self._get(HTML_CANAIS_URL)
        if not html_text:
            logger.error("Could not fetch catalog from API or HTML.")
            return []

        channels = self._extract_nextjs_channels(html_text)
        logger.info("Extracted %d channels via HTML Next.js payload fallback.", len(channels))
        return channels

    @staticmethod
    def _extract_nextjs_channels(html: str) -> List[Dict[str, Any]]:
        """Extract embedded channel list from Next.js server component chunks."""
        chunks = re.findall(r"self\.__next_f\.push\(\[(.*?)\]\)", html, re.DOTALL)
        combined_payload = ""
        for chunk in chunks:
            try:
                parsed = json.loads(f"[{chunk}]")
                if len(parsed) > 1 and isinstance(parsed[1], str):
                    combined_payload += parsed[1]
            except Exception:
                combined_payload += chunk

        start_idx = combined_payload.find('[{"id":')
        if start_idx == -1:
            start_idx = combined_payload.find('[{"slug":')

        if start_idx != -1:
            try:
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(combined_payload[start_idx:])
                if isinstance(data, list):
                    return data
            except Exception as exc:
                logger.error("Error decoding Next.js payload slice: %s", exc)

        return []

    async def fetch_authorized_public_streams(self) -> List[Dict[str, str]]:
        """
        Fetch verified Brazilian public streams from authorized open repositories
        (e.g., iptv-org verified Brazilian public streams).
        """
        logger.info("Fetching authorized public Brazilian streams from %s", PUBLIC_STREAMS_BR_URL)
        content = await self._get(PUBLIC_STREAMS_BR_URL)
        if not content:
            logger.warning("Could not fetch public Brazilian streams list.")
            return []

        return self.parse_raw_m3u(content)

    @staticmethod
    def parse_raw_m3u(content: str) -> List[Dict[str, str]]:
        """Parse raw M3U text into a list of stream records."""
        streams: List[Dict[str, str]] = []
        current: Dict[str, str] = {}

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("#EXTINF:"):
                tvg_id_m = re.search(r'tvg-id="([^"]*)"', line)
                tvg_name_m = re.search(r'tvg-name="([^"]*)"', line)
                tvg_logo_m = re.search(r'tvg-logo="([^"]*)"', line)
                group_m = re.search(r'group-title="([^"]*)"', line)
                name_m = line.split(",")[-1].strip() if "," in line else ""

                current = {
                    "tvg_id": tvg_id_m.group(1) if tvg_id_m else "",
                    "tvg_name": tvg_name_m.group(1) if tvg_name_m else name_m,
                    "tvg_logo": tvg_logo_m.group(1) if tvg_logo_m else "",
                    "group_title": group_m.group(1) if group_m else "",
                    "name": name_m,
                }
            elif not line.startswith("#"):
                if current:
                    current["url"] = line
                    streams.append(current)
                    current = {}

        logger.info("Parsed %d streams from raw M3U source.", len(streams))
        return streams

    async def collect_all(self) -> Dict[str, Any]:
        """Orchestrate collection of reference catalog and authorized public stream pool."""
        catalog_task = asyncio.create_task(self.fetch_reference_catalog())
        public_streams_task = asyncio.create_task(self.fetch_authorized_public_streams())

        catalog, public_streams = await asyncio.gather(
            catalog_task, public_streams_task, return_exceptions=False
        )

        return {
            "reference_channels": catalog,
            "public_streams": public_streams,
        }

