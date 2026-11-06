"""
test_generator.py - Unit tests for generator.py
"""

import os
import tempfile
import pytest
import sys

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from generator import M3UGenerator, CANONICAL_CATEGORIES


def test_generate_content_formatting():
    channels = [
        {
            "name": "TV Brasil",
            "category": "Canais Abertos",
            "tvg_id": "tvbrasil.br",
            "tvg_name": "TV Brasil",
            "tvg_logo": "https://exemplo.com/tvbrasil.png",
            "url": "https://stream.exemplo.com/tvbrasil.m3u8",
        },
        {
            "name": "CNN Brasil",
            "category": "Notícias",
            "tvg_id": "cnnbrasil.br",
            "tvg_name": "CNN Brasil",
            "tvg_logo": "https://exemplo.com/cnn.png",
            "url": "https://stream.exemplo.com/cnn.m3u8",
        },
    ]

    content = M3UGenerator.generate_content(channels)
    lines = content.strip().split("\n")

    assert lines[0] == "#EXTM3U"
    assert lines[1] == (
        '#EXTINF:-1 tvg-id="tvbrasil.br" tvg-name="TV Brasil" '
        'tvg-logo="https://exemplo.com/tvbrasil.png" group-title="Canais Abertos",TV Brasil'
    )
    assert lines[2] == "https://stream.exemplo.com/tvbrasil.m3u8"
    assert lines[3] == (
        '#EXTINF:-1 tvg-id="cnnbrasil.br" tvg-name="CNN Brasil" '
        'tvg-logo="https://exemplo.com/cnn.png" group-title="Notícias",CNN Brasil'
    )
    assert lines[4] == "https://stream.exemplo.com/cnn.m3u8"


def test_empty_playlist_protection():
    with tempfile.NamedTemporaryFile(suffix=".m3u", delete=False) as f:
        f.write(b"#EXTM3U\n# Existing valid content\n")
        tmp_name = f.name

    try:
        gen = M3UGenerator(output_path=tmp_name)
        result = gen.write_playlist([])
        assert result is False

        # Verify that original file was not modified/cleared
        with open(tmp_name, "rb") as f:
            data = f.read()
        assert b"# Existing valid content" in data
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def test_atomic_write_success():
    with tempfile.TemporaryDirectory() as tmp_dir:
        target_path = os.path.join(tmp_dir, "test.m3u")
        gen = M3UGenerator(output_path=target_path)
        channels = [
            {
                "name": "Band",
                "category": "Canais Abertos",
                "tvg_id": "band.br",
                "tvg_name": "Band",
                "tvg_logo": "https://exemplo.com/band.png",
                "url": "https://stream.exemplo.com/band.m3u8",
            }
        ]
        result = gen.write_playlist(channels)
        assert result is True
        assert os.path.exists(target_path)

        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "#EXTM3U" in content
        assert "Band" in content
        assert "Canais Abertos" in content

