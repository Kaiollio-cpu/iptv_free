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
            '-protocol_whitelist', 'http,https,tcp,tls,crypto', '-rw_timeout', '8000000',
            '-threads', '1', '-i', url, '-map', '0:v:0', '-an', '-frames:v', '1',
            '-threads', '1', '-progress', 'pipe:1', '-f', 'null', '-'],
            capture_output=True, timeout=22)
        return teste.returncode == 0 and bool(re.search(rb'^frame=[1-9]\d*$', teste.stdout, re.M))
    except subprocess.TimeoutExpired:
        return False

def main():
    with urlopen(CATALOGO, timeout=30) as resp:
        texto = resp.read().decode('utf-8-sig')
    por_url = collections.defaultdict(set)
    registros = 0
    for bloco in re.split(r'(?=^GRUPO=)', texto, flags=re.M):
        d = dict(re.findall(r'^(\w+)="([^"\r\n]*)"', bloco, re.M))
        if 'GRUPO' not in d:
            continue
        registros += 1
        if d.get('TIPO') not in ('NORMAL', 'NORMAL2'):
            continue
        url = endereco(d.get('URL', ''))
        if url and limpar(d.get('NOME', '')):
            por_url[url].add((limpar(d['GRUPO']), limpar(d['NOME'])))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        itens = [(grupo, nome, url) for url, ok in zip(por_url, pool.map(reproduz, por_url))
                 if ok for grupo, nome in por_url[url]]
    print(f'{registros} entradas, {len(por_url)} links diretos testados, {len(itens)} entradas reproduzíveis.')
    if not itens:
        raise SystemExit('Nenhum vídeo confirmado. Lista anterior preservada.')
    linhas = ['#EXTM3U']
    for grupo, nome, url in sorted(itens):
        linhas.extend([f'#EXTINF:-1 group-title="{grupo}",{nome}', url])
    tmp = Path('main.m3u.tmp')
    tmp.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    os.replace(tmp, 'main.m3u')

if __name__ == '__main__':
    main()
