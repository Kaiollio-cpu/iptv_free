"""
validator.py - Asynchronous Stream Validator for IPTV Auto Updater.

Validates HLS / MPEG-TS streams using aiohttp with concurrency limits,
SSRF protection, exponential backoff, header inspection, and temporary failure tracking.
"""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import json
import logging
import os
import re
import socket
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import aiohttp

logger = logging.getLogger(__name__)

# Constants
DEFAULT_CONCURRENCY = 10
DEFAULT_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
MAX_CONSECUTIVE_FAILURES = 3

DEFAULT_STATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "channel_status.json",
)


def mask_sensitive_url(url: str) -> str:
    """Mask tokens, keys, and credentials in URLs for safe logging."""
    try:
        parsed = urllib.parse.urlparse(url)
        # mask user info
        netloc = parsed.netloc
        if "@" in netloc:
            credentials, host = netloc.split("@", 1)
            netloc = f"***:***@{host}"

        # mask query parameters
        if parsed.query:
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            masked_pairs = []
            for k, v in query_pairs:
                if any(s in k.lower() for s in ["token", "key", "auth", "sign", "secret", "pass", "pwd", "hash"]):
                    masked_pairs.append((k, "***"))
                else:
                    masked_pairs.append((k, v))
            query = urllib.parse.urlencode(masked_pairs, safe="*")
        else:
            query = ""

        return urllib.parse.urlunparse((
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            query,
            parsed.fragment,
        ))
    except Exception:
        return "<invalid_url>"


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    SSRF Protection: Check if URL scheme is http/https and resolved IP is not private/reserved.
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, f"Protocolo inseguro ou inválido: {parsed.scheme}"

        hostname = parsed.hostname
        if not hostname:
            return False, "Hostname ausente"

        # Check for numeric or named localhost
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False, "Acesso a localhost bloqueado (SSRF)"

        # Resolve IP to verify against private, loopback, link-local, multicast
        addr_info = socket.getaddrinfo(hostname, None)
        for entry in addr_info:
            ip_str = entry[4][0]
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_reserved
                or ip_obj.is_link_local
                or ip_obj.is_multicast
            ):
                return False, f"Acesso a IP privado ou reservado bloqueado ({ip_str})"

        return True, "OK"
    except socket.gaierror:
        return False, "Falha de resolução DNS (domínio inexistente ou indisponível)"
    except Exception as exc:
        return False, f"Erro ao analisar segurança da URL: {exc}"


class StreamValidator:
    """Asynchronous validator for IPTV stream availability and validity."""

    def __init__(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        state_file: str = DEFAULT_STATE_FILE,
    ) -> None:
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = aiohttp.ClientTimeout(
            total=timeout_seconds,
            connect=min(5, timeout_seconds),
        )
        self.max_retries = max_retries
        self.state_file = state_file
        self.state: Dict[str, Dict[str, Any]] = self._load_state()

    def _load_state(self) -> Dict[str, Dict[str, Any]]:
        """Load persistent channel health state from disk."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read state file %s: %s", self.state_file, exc)
        return {}

    def save_state(self) -> None:
        """Atomically persist state to disk."""
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp_file = f"{self.state_file}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.state_file)
            logger.info("Persisted channel health state to %s", self.state_file)
        except Exception as exc:
            logger.error("Failed to save state file: %s", exc)

    @staticmethod
    def _is_valid_hls_header(data: bytes) -> bool:
        """Verify HLS playlist format without downloading full stream segments."""
        text = data[:2048].decode("utf-8", errors="ignore")
        if "#EXTM3U" not in text:
            return False
        # Check for typical HLS markers
        hls_markers = [
            "#EXT-X-STREAM-INF",
            "#EXTINF",
            "#EXT-X-TARGETDURATION",
            "#EXT-X-VERSION",
            "#EXT-X-MEDIA-SEQUENCE",
        ]
        return any(marker in text for marker in hls_markers)

    async def _test_stream_with_backoff(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> Tuple[bool, str]:
        """Attempt to validate stream with exponential backoff retries."""
        safe, reason = is_safe_url(url)
        if not safe:
            return False, reason

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Range": "bytes=0-4096",  # Read first chunk only
        }

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self.semaphore:
                    async with session.get(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                        allow_redirects=True,
                    ) as resp:
                        if resp.status not in (200, 206):
                            last_error = f"HTTP {resp.status}"
                        else:
                            # Read initial chunk only, do not download whole video
                            chunk = await resp.content.read(2048)
                            if self._is_valid_hls_header(chunk):
                                return True, "Online (HLS válido)"
                            # If not standard HLS text, check content-type or TS stream
                            ctype = resp.headers.get("Content-Type", "").lower()
                            if "mpegurl" in ctype or "apple.mpegurl" in ctype or "video/mp2t" in ctype:
                                return True, f"Online ({ctype})"
                            # Some streams return 200 with raw TS or video stream
                            if len(chunk) > 0 and (url.endswith(".ts") or "video" in ctype):
                                return True, "Online (Stream TS/Video)"

                            last_error = "Estrutura HLS/M3U inválida no corpo da resposta"
            except asyncio.TimeoutError:
                last_error = f"Timeout ({self.timeout.total}s)"
            except aiohttp.ClientError as exc:
                last_error = f"Erro de conexão: {type(exc).__name__}"
            except Exception as exc:
                last_error = f"Erro inesperado: {exc}"

            if attempt < self.max_retries:
                backoff = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        return False, last_error

    async def validate_channel(
        self,
        session: aiohttp.ClientSession,
        channel: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate an individual channel and update its failure state."""
        ch_id = channel.get("id") or channel.get("name")
        url = channel.get("url", "")
        masked_url = mask_sensitive_url(url)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Retrieve previous state
        prev = self.state.get(ch_id, {})
        consecutive_failures = prev.get("consecutive_failures", 0)

        is_online, details = await self._test_stream_with_backoff(session, url)

        if is_online:
            consecutive_failures = 0
            status = "online"
            logger.info("Channel '%s' is ONLINE (%s)", channel.get("name"), masked_url)
        else:
            consecutive_failures += 1
            if consecutive_failures < MAX_CONSECUTIVE_FAILURES:
                status = "degraded"
                logger.warning(
                    "Channel '%s' failed attempt %d/%d (%s): %s. Mantendo provisoriamente.",
                    channel.get("name"),
                    consecutive_failures,
                    MAX_CONSECUTIVE_FAILURES,
                    masked_url,
                    details,
                )
            else:
                status = "offline"
                logger.error(
                    "Channel '%s' OFFLINE após %d falhas consecutivas (%s): %s.",
                    channel.get("name"),
                    consecutive_failures,
                    masked_url,
                    details,
                )

        # Update channel record
        channel["status"] = status
        channel["status_details"] = details
        channel["consecutive_failures"] = consecutive_failures
        channel["last_checked"] = now_iso

        # Update persisted state cache
        self.state[ch_id] = {
            "name": channel.get("name"),
            "url": url,
            "status": status,
            "consecutive_failures": consecutive_failures,
            "last_checked": now_iso,
            "last_successful_check": now_iso if is_online else prev.get("last_successful_check"),
        }

        return channel

    async def validate_all(
        self,
        channels: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Validate all channels asynchronously.
        Returns:
            (active_channels, inactive_channels)
            Note: 'degraded' channels are retained in active_channels per requirement
            ("não remover um canal após uma única falha temporária").
        """
        logger.info("Starting validation of %d candidate channels...", len(channels))
        connector = aiohttp.TCPConnector(ssl=False, limit=None)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [self.validate_channel(session, ch) for ch in channels]
            validated = await asyncio.gather(*tasks, return_exceptions=False)

        self.save_state()

        active: List[Dict[str, Any]] = []
        inactive: List[Dict[str, Any]] = []

        for ch in validated:
            # Online and degraded channels are kept in the playlist
            if ch.get("status") in ("online", "degraded"):
                active.append(ch)
            else:
                inactive.append(ch)

        logger.info(
            "Validation finished: %d active (%d online, %d degraded), %d offline.",
            len(active),
            sum(1 for c in active if c.get("status") == "online"),
            sum(1 for c in active if c.get("status") == "degraded"),
            len(inactive),
        )
        return active, inactive
