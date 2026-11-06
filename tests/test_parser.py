"""
test_parser.py - Unit tests for parser.py
"""

import pytest
import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from parser import (
    ChannelParser,
    CANONICAL_CATEGORIES,
    normalize_text,
    detect_protocol,
    standardize_tvg_id,
)


def test_category_mapping():
    parser = ChannelParser()
    assert parser.map_category("abertos") == "Canais Abertos"
    assert parser.map_category("Canais Abertos") == "Canais Abertos"
    assert parser.map_category("sports") == "Esportes"
    assert parser.map_category("Esportes") == "Esportes"
    assert parser.map_category("filmes") == "Filmes e Séries"
    assert parser.map_category("movies") == "Filmes e Séries"
    assert parser.map_category("documentary") == "Documentários"
    assert parser.map_category("kids") == "Infantil"
    assert parser.map_category("news") == "Notícias"
    assert parser.map_category("entertainment") == "Entretenimento"
    assert parser.map_category("desconhecido_xyz") == "Outros"
    assert parser.map_category("") == "Outros"


def test_standardize_tvg_id():
    assert standardize_tvg_id("band", "Band") == "band.br"
    assert standardize_tvg_id("canal-brasil", "Canal Brasil") == "canal.brasil.br"
    assert standardize_tvg_id("tvbrasil.br", "TV Brasil") == "tvbrasil.br"


def test_detect_protocol():
    assert detect_protocol("https://stream.example/live.m3u8") == "HLS"
    assert detect_protocol("https://stream.example/live.m3u8?token=123") == "HLS"
    assert detect_protocol("http://stream.example/live.ts") == "MPEG-TS"


def test_paywall_restriction_filter():
    parser = ChannelParser()
    assert parser.is_paywall_restricted("HBO") is True
    assert parser.is_paywall_restricted("Telecine Premium") is True
    assert parser.is_paywall_restricted("Premiere 2") is True
    assert parser.is_paywall_restricted("Combate") is True
    assert parser.is_paywall_restricted("TV Brasil") is False
    assert parser.is_paywall_restricted("Band") is False


def test_build_channel_catalog_matching():
    parser = ChannelParser()
    reference_channels = [
        {
            "id": "cnnbrasil",
            "name": "CNN Brasil",
            "category": "Notícias",
            "logo_url": "https://logocanais.pics/imagens/cnnbrasil.png",
        },
        {
            "id": "hbo",
            "name": "HBO",
            "category": "Filmes e Séries",
            "logo_url": "https://logocanais.pics/imagens/hbo.png",
        },
        {
            "id": "unknown_chan",
            "name": "Canal Raro Desconhecido",
            "category": "Entretenimento",
            "logo_url": "",
        },
    ]

    public_streams = [
        {
            "name": "CNN Brasil (1080p)",
            "tvg_name": "CNN Brasil",
            "tvg_id": "CNNBrasil.br",
            "url": "https://d25usgadhphvwi.cloudfront.net/hls/main.m3u8",
        }
    ]

    eligible, excluded = parser.build_channel_catalog(reference_channels, public_streams)

    # HBO should be excluded due to paywall / DRM compliance
    # Unknown channel excluded due to no verified stream
    # CNN Brasil should be eligible
    assert len(eligible) == 1
    assert eligible[0]["name"] == "CNN Brasil"
    assert eligible[0]["category"] == "Notícias"
    assert eligible[0]["url"] == "https://d25usgadhphvwi.cloudfront.net/hls/main.m3u8"
    assert eligible[0]["is_authorized"] is True

    assert len(excluded) == 2
    excluded_names = {x["name"] for x in excluded}
    assert "HBO" in excluded_names
    assert "Canal Raro Desconhecido" in excluded_names


def test_organize_and_sort():
    parser = ChannelParser()
    raw_list = [
        {"name": "SBT", "category": "Canais Abertos", "url": "http://sbt.m3u8"},
        {"name": "Band", "category": "Canais Abertos", "url": "http://band.m3u8"},
        {"name": "CNN Brasil", "category": "Notícias", "url": "http://cnn.m3u8"},
        {"name": "Agro+", "category": "Notícias", "url": "http://agro.m3u8"},
        # Duplicate url
        {"name": "Band Clone", "category": "Canais Abertos", "url": "http://band.m3u8"},
    ]

    sorted_list = parser.organize_and_sort(raw_list)

    assert len(sorted_list) == 4
    # Check that Canais Abertos come before Notícias
    assert sorted_list[0]["category"] == "Canais Abertos"
    assert sorted_list[1]["category"] == "Canais Abertos"
    assert sorted_list[2]["category"] == "Notícias"
    assert sorted_list[3]["category"] == "Notícias"

    # Check alphabetical ordering within category
    assert sorted_list[0]["name"] == "Band"
    assert sorted_list[1]["name"] == "SBT"
    assert sorted_list[2]["name"] == "Agro+"
    assert sorted_list[3]["name"] == "CNN Brasil"
