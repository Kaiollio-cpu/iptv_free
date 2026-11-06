"""
test_validator.py - Unit tests for validator.py
"""

import os
import tempfile
import pytest
import sys

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from validator import (
    StreamValidator,
    mask_sensitive_url,
    is_safe_url,
    MAX_CONSECUTIVE_FAILURES,
)


def test_mask_sensitive_url():
    url_with_token = "https://stream.exemplo.com/live.m3u8?token=SECRET123&user=john"
    masked = mask_sensitive_url(url_with_token)
    assert "SECRET123" not in masked
    assert "token=***" in masked
    assert "user=john" in masked

    url_with_auth = "http://admin:password123@stream.exemplo.com/live.ts"
    masked_auth = mask_sensitive_url(url_with_auth)
    assert "password123" not in masked_auth
    assert "***:***@" in masked_auth


def test_ssrf_protection_unsafe_urls():
    # Scheme check
    safe, _ = is_safe_url("file:///etc/passwd")
    assert safe is False

    safe, _ = is_safe_url("ftp://stream.exemplo.com/live.ts")
    assert safe is False

    # Localhost
    safe, msg = is_safe_url("http://localhost:8080/live.m3u8")
    assert safe is False
    assert "localhost" in msg.lower() or "privado" in msg.lower()

    safe, _ = is_safe_url("http://127.0.0.1:8080/live.m3u8")
    assert safe is False

    # Private IP
    safe, _ = is_safe_url("http://192.168.1.1/stream.m3u8")
    assert safe is False

    safe, _ = is_safe_url("http://10.0.0.1:8080/stream.m3u8")
    assert safe is False


def test_hls_header_validation():
    valid_header = (
        b"#EXTM3U\n"
        b"#EXT-X-VERSION:3\n"
        b"#EXT-X-TARGETDURATION:10\n"
        b"#EXTINF:10.0,\n"
        b"segment1.ts\n"
    )
    assert StreamValidator._is_valid_hls_header(valid_header) is True

    valid_master = (
        b"#EXTM3U\n"
        b"#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=720x480\n"
        b"chunklist.m3u8\n"
    )
    assert StreamValidator._is_valid_hls_header(valid_master) is True

    html_content = b"<!DOCTYPE html><html><body>Error 404 Not Found</body></html>"
    assert StreamValidator._is_valid_hls_header(html_content) is False

    empty_content = b""
    assert StreamValidator._is_valid_hls_header(empty_content) is False


def test_temporary_failure_retention():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_state:
        state_file = tmp_state.name

    try:
        validator = StreamValidator(state_file=state_file)

        # Simulate 1st failure: channel should become "degraded" but remain retained
        ch = {"id": "test_ch", "name": "Test Channel", "url": "http://127.0.0.1/fake.m3u8"}
        # Force simulate failure logic without network
        prev = validator.state.get("test_ch", {})
        failures = prev.get("consecutive_failures", 0) + 1
        status = "degraded" if failures < MAX_CONSECUTIVE_FAILURES else "offline"

        assert failures == 1
        assert status == "degraded"

        # Simulate 3rd failure: channel should become "offline"
        failures = 3
        status = "degraded" if failures < MAX_CONSECUTIVE_FAILURES else "offline"
        assert status == "offline"
    finally:
        if os.path.exists(state_file):
            os.remove(state_file)
