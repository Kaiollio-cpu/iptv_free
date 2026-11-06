"""Gera main.m3u a partir dos links de mídia do catálogo do OnePlay 3.1.4."""
import collections
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import urlopen

CATALOGO = 'https://gist.githubusercontent.com/zoreu/b1912aa40daaec0eabf1a74c51e310a0/raw/canais_servidor1.txt'
# Endereços públicos revisados. Nunca copiar cabeçalhos, contas ou query strings.
PUBLICOS = set("""
http://45.162.230.234:1935/agrobrasiltv/agrobrasiltv/playlist.m3u8
http://live-edge01.telecentro.net.ar/live/smil:c26.smil/playlist.m3u8
http://nbcnews2.akamaized.net/hls/live/723426-b/NBCNewsPlaymaker24x7Linear99a3a827-ua/VIDEO_0_6596000.m3u8
https://250weu.bozztv.com/ssh101/ssh101/kpoptv/playlist.m3u8
https://3abn-live.akamaized.net/hls/live/2010550/Kids/master.m3u8
https://5cf4a2c2512a2.streamlock.net/rbatv/rbatv/playlist-720p.m3u8
https://5d82644094cc0.streamlock.net:443/ricostv/ricostv/playlist.m3u8
https://cnn-cnninternational-1-eu.rakuten.wurl.tv/playlist.m3u8
https://d1zpubcqwsvgqw.cloudfront.net/out/v1/d33c00c8ecbe4aa9b7e834e607fbbacb/index.mpd
https://d1zx6l1dn8vaj5.cloudfront.net/out/v1/b89cc37caa6d418eb423cf092a2ef970/index.m3u8
https://d6yfbj4xxtrod.cloudfront.net/out/v1/7836eb391ec24452b149f3dc6df15bbd/index_10.m3u8
https://fox-foxnewsnow-samsungus.amagi.tv/playlist.m3u8
https://live-hls-web-aje.getaj.net/AJE/01.m3u8
https://ntv1.akamaized.net/hls/live/2014075/NASA-NTV1-HLS/master_2000.m3u8
https://ntv2.akamaized.net/hls/live/2013923/NASA-NTV2-HLS/master_2000.m3u8
https://rakuten-euronews-8-pt.samsung.wurl.com/manifest/playlist.m3u8
https://rbmn-live.akamaized.net/hls/live/590964/BoRB-AT/master.m3u8
https://stmv1.srvif.com/animetv/animetv/playlist.m3u8
https://stmv1.srvif.com/gmusic/gmusic/playlist.m3u8
https://stmv1.srvif.com/gospelcartoon/gospelcartoon/playlist.m3u8
https://stmv1.srvif.com/gospelf/gospelf/chunklist.m3u8
""".split())

def endereco(raw):
    url = raw.split('|', 1)[0]
    partes = urlsplit(url)
    if url in PUBLICOS:
        return url
    if (partes.netloc == 'stitcher-ipv4.pluto.tv'
            and partes.scheme in ('http', 'https')
            and re.fullmatch(r'/v1/stitch/embed/hls/channel/[0-9a-f]{24}/master\.m3u8', partes.path)):
        return 'https://stitcher-ipv4.pluto.tv' + partes.path
    return None

def limpar(valor):
    return ' '.join(re.sub(r'\[[^\]]*\]', '', valor).replace('"', '').split())

def reproduz(url):
    try:
        teste = subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error',
            '-protocol_whitelist', 'http,https,httpproxy,tcp,tls,crypto', '-rw_timeout', '8000000',
            '-threads', '1', '-i', url, '-map', '0:v:0', '-an', '-frames:v', '1',
            '-threads', '1', '-progress', 'pipe:1', '-f', 'null', '-'],
            capture_output=True, timeout=22)
        return teste.returncode == 0 and bool(re.search(rb'^frame=[1-9]\d*$', teste.stdout, re.M))
    except subprocess.TimeoutExpired:
        return False


# Pares ID/URL revisados no diretório público iptv-org/iptv, streams/br.m3u.
ALTERNATIVAS = [
    ('BandNews.br', 'http://168.197.104.22/BAND_NEWS/index.m3u8'),
    ('BandNews.br', 'http://170.83.16.50/BAND_NEWS/index.m3u8'),
    ('BandNews.br', 'http://170.83.49.66:8083/BANDNEWSHD/index.m3u8'),
    ('BandNews.br', 'http://45.162.64.114/BAND_NEWS/index.m3u8'),
    ('BandNews.br', 'http://45.177.114.115/BAND_NEWS/index.m3u8'),
    ('BandNews.br', 'https://cdn-5.nxplay.com.br/BAND_NEWS/index.m3u8'),
    ('BandSports.br', 'http://170.83.16.50/BAND_SPORTS/index.m3u8'),
    ('BandSports.br', 'http://170.83.49.66:8083/BANDSPORTSHD/index.m3u8'),
    ('BandSports.br', 'http://45.162.64.114/BAND_SPORTS/index.m3u8'),
    ('BandSports.br', 'https://cdn-5.nxplay.com.br/BAND_SPORTS/index.m3u8'),
    ('CNNBrasil.br', 'https://d25usgadhphvwi.cloudfront.net/hls/main.m3u8'),
    ('FishTV.br', 'http://168.197.104.22/FISH_TV/index.m3u8'),
    ('FishTV.br', 'http://170.83.16.50/FISH_TV/index.m3u8'),
    ('FishTV.br', 'http://190.128.214.97:64333/play/a006/index.m3u8'),
    ('FishTV.br', 'http://45.162.64.114/FISH_TV/index.m3u8'),
    ('GNT.br', 'http://170.82.202.31/GNT/index.m3u8'),
    ('GloboNews.br', 'http://79.127.238.228:14093'),
    ('Gloob.br', 'http://45.235.0.78/Gloob/playlist.m3u8'),
    ('RBATV.br', 'https://cdn.live.br1.jmvstream.com/w/LVW-15748/LVW15748_Yed7yzLuRC/playlist.m3u8'),
    ('RedeTV.br', 'http://168.197.104.22/REDE_TV/index.m3u8'),
    ('RedeTV.br', 'http://170.83.16.50/REDE_TV/index.m3u8'),
    ('RedeTV.br', 'http://170.83.49.66:8083/REDETVHD/index.m3u8'),
    ('RedeTV.br', 'http://186.219.52.187/rede_tv/index.m3u8'),
    ('RedeTV.br', 'http://45.162.64.114/REDE_TV/index.m3u8'),
    ('RedeTV.br', 'https://hls.brasilstream.com.br/live/redetv/redetv/playlist.m3u8'),
    ('RedeVida.br', 'http://168.197.104.22/REDE_VIDA/index.m3u8'),
    ('RedeVida.br', 'http://170.84.165.204/REDEVIDA_HD/index.m3u8'),
    ('RedeVida.br', 'http://186.219.52.187/rede_vida/index.m3u8'),
    ('RedeVida.br', 'http://46.151.196.223:14244'),
    ('RedeVida.br', 'https://cdn-5.nxplay.com.br/REDE_VIDA/index.m3u8'),
    ('SBTNacional.br', 'https://6836041ea1117.streamlock.net/cverde/cverde/playlist.m3u8'),
    ('SBTNacional.br', 'https://cdn.live.br1.jmvstream.com/w/LVW-10801/LVW10801_Xvg4R0u57n/chunklist.m3u8'),
    ('SBTNacional.br', 'https://media.cdntvms.com.br/sbt_sat/index.m3u8'),
    ('SporTV2.br', 'http://195.178.110.110/sportv2/index.m3u8'),
    ('SporTV3.br', 'http://170.83.49.66:8083/SPORTV3HD/index.m3u8'),
    ('SporTV3.br', 'http://195.178.110.110/sportv3/index.m3u8'),
    ('TVAparecida.br', 'http://168.197.104.22/TV_APARECIDA/index.m3u8'),
    ('TVAparecida.br', 'http://170.83.16.50/TV_APARECIDA/index.m3u8'),
    ('TVAparecida.br', 'http://170.83.49.66:8083/TVAPARECIDAHD/index.m3u8'),
    ('TVAparecida.br', 'http://45.162.64.114/TV_APARECIDA/index.m3u8'),
    ('TVAparecida.br', 'http://45.177.114.115/TV_APARECIDA_HD/index.m3u8'),
    ('TVAparecida.br', 'https://cdn.jmvstream.com/w/LVW-9716/LVW9716_HbtQtezcaw/playlist.m3u8'),
    ('TVCancaoNova.br', 'http://168.197.104.22/CANCAO_NOVA/index.m3u8'),
    ('TVCancaoNova.br', 'http://170.83.16.50/CANCAO_NOVA/index.m3u8'),
    ('TVCancaoNova.br', 'http://186.219.52.187/cancao_nova/index.m3u8'),
    ('TVCancaoNova.br', 'http://45.162.64.114/CANCAO_NOVA/index.m3u8'),
    ('TVGazeta.br', 'http://186.219.52.187/gazeta/index.m3u8'),
    ('TVGazeta.br', 'http://45.162.64.114/TV_GAZETA/index.m3u8'),
    ('TVGazeta.br', 'https://tv.nuvemplay.live/hls/40gtv/stream.m3u8'),
    ('TVGloboSaoPaulo.br', 'http://170.84.165.204/Globo_HD/index.m3u8'),
    ('TVGloboSaoPaulo.br', 'https://cdn-5.nxplay.com.br/GLOBO_SP_TK/index.m3u8'),
    ('TelecineAction.br', 'http://46.151.196.223:14326'),
]

def gerar(texto):
    fontes = collections.defaultdict(list)
    for epg, url in ALTERNATIVAS:
        fontes[epg].append(url)
    canais = {}
    for bloco in re.split(r'(?=^GRUPO=)', texto, flags=re.M):
        d = dict(re.findall(r'^(\w+)="([^"\r\n]*)"', bloco, re.M))
        if not d or not d.get('NOME') or re.search('adult|a casa das brasileirinhas', d['GRUPO'], re.I):
            continue
        epg = d.get('EPGID', '')
        nome = re.sub(r'\s*\(OPÇÃO \d+\)\s*$', '', limpar(d['NOME']), flags=re.I)
        key = (limpar(d['GRUPO']), nome)
        candidatos = canais.setdefault(key, [])
        if d['TIPO'] in ('NORMAL', 'NORMAL2'):
            direto = endereco(d['URL'])
            if direto:
                candidatos.append(direto)
        candidatos.extend(fontes.get(epg, []))
    urls = sorted({u for candidatos in canais.values() for u in candidatos})
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        ativos = {u for u, ok in zip(urls, pool.map(reproduz, urls)) if ok}
    linhas = ['#EXTM3U']
    for (grupo, nome), candidatos in sorted(canais.items()):
        url = next((u for u in candidatos if u in ativos), None)
        if url:
            linhas.extend([f'#EXTINF:-1 group-title="{grupo}",{nome}', url])
    if len(linhas) == 1:
        raise SystemExit('Nenhum fluxo decodificado. Publicação cancelada.')
    print(f'{len(urls)} URLs testadas, {(len(linhas)-1)//2} canais com vídeo.')
    return '\n'.join(linhas)+'\n'

def main():
    with urlopen(CATALOGO, timeout=30) as resp:
        texto = resp.read().decode('utf-8-sig')
    tmp = Path('main.m3u.tmp')
    tmp.write_text(gerar(texto), encoding='utf-8')
    os.replace(tmp, 'main.m3u')

if __name__ == '__main__':
    main()
