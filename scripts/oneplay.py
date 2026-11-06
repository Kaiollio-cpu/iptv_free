"""Gera main.m3u a partir dos links de mídia do catálogo do OnePlay 3.1.4."""
import collections
import os
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
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

ACOES = {
    'EMBEDFLIX': 'player_embedflix',
    'AOVIVOGRATIS': 'player_aovivogratis',
    'PLAYERTV': 'player_playertv',
    'DAZN1': 'player_dazn1',
}

def gerar(texto):
    itens = set()
    contagens = collections.Counter()
    for bloco in re.split(r'(?=^GRUPO=)', texto, flags=re.M):
        d = dict(re.findall(r'^(\w+)="([^"\r\n]*)"', bloco, re.M))
        if not d:
            continue
        grupo, nome = limpar(d['GRUPO']), limpar(d['NOME'])
        tipo, valor = d['TIPO'], d['URL']
        if re.search(r'Adult|A Casa das Brasileirinhas', grupo, re.I):
            contagens['grupo protegido no Kodi'] += 1
            continue
        if not valor or valor == 'url_error':
            contagens['sem endereço'] += 1
            continue
        if tipo in ('NORMAL', 'NORMAL2'):
            url = endereco(valor)
            if not url:
                contagens['endereço não exportável'] += 1
                continue
        elif tipo in ACOES and re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', valor):
            params = {'action': ACOES[tipo], 'url': valor, 'name': nome, 'playable': 'true'}
            url = 'plugin://plugin.video.OnePlay/?' + urlencode(params)
        else:
            contagens['tipo não reconhecido'] += 1
            continue
        itens.add((grupo, nome, url))
    if not itens:
        raise ValueError('Catálogo vazio. Publicação cancelada.')
    linhas = ['#EXTM3U']
    for grupo, nome, url in sorted(itens):
        linhas.extend([f'#EXTINF:-1 group-title="{grupo}",{nome}', url])
    print(f'{len(itens)} entradas exportadas; exclusões: {dict(contagens)}')
    return '\n'.join(linhas) + '\n'

def main():
    with urlopen(CATALOGO, timeout=30) as resp:
        texto = resp.read().decode('utf-8-sig')
    tmp = Path('main.m3u.tmp')
    tmp.write_text(gerar(texto), encoding='utf-8')
    os.replace(tmp, 'main.m3u')

if __name__ == '__main__':
    main()
