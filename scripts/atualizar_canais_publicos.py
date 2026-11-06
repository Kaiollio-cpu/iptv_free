"""Atualizador público limitado às fontes sem credenciais revisadas.

Python 3.10+, ffmpeg e ffprobe no PATH.
python atualizar_canais_publicos.py --publicar
GITHUB_TOKEN: variável de ambiente com Contents:write no repositório.
Não executa código de addons nem exporta contas do BrazucaPlay.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CATALOGO = 'https://gist.githubusercontent.com/zoreu/b1912aa40daaec0eabf1a74c51e310a0/raw/canais_servidor1.txt'
# Lista explícita: não basta procurar palavras como password na URL.
# Nenhuma URL arbitrária extraída dos plugins pode ser publicada.
FONTES_PUBLICAS = {
    'https://5cf4a2c2512a2.streamlock.net/rbatv/rbatv/playlist-720p.m3u8':
        ('BAND - RBA TV HD', 'Abertos', 'RBATV.br'),
}
REPO = 'Kaiollio-cpu/iptv_free'
DESTINO = 'canais_publicos_HD.m3u'

def request(url, data=None, token=None):
    headers = {'User-Agent': 'iptv-public-checker', 'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = Request(url, headers=headers, data=json.dumps(data).encode() if data else None,
                  method='PUT' if data else 'GET')
    with urlopen(req, timeout=30) as response:
        return response.read()

def extrair(texto):
    urls = set(re.findall(r'^URL="([^"\r\n]+)"', texto, re.M))
    return sorted(urls.intersection(FONTES_PUBLICAS))

def falha(etapa, stderr):
    detalhe = re.search(rb'(?:HTTP error |Server returned |HTTP/\S+ )([45]\d\d)\b', stderr, re.I)
    motivo = 'HTTP ' + detalhe[1].decode() if detalhe else 'erro ao ler a transmissão'
    print(f'{etapa}: {motivo}.')
    return False

def verificar(url):
    etapa = 'Leitura do canal'
    # Uma resposta HTTP 200 ou manifesto acessível não comprova reprodução.
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-rw_timeout', '12000000',
            '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height',
            '-of', 'json', url], capture_output=True, timeout=25)
        if p.returncode:
            return falha(etapa, p.stderr)
        streams = json.loads(p.stdout).get('streams', [])
        if not streams:
            print('Nenhuma faixa de vídeo encontrada.')
            return False
        v = streams[0]
        if v.get('codec_name') != 'h264' or v.get('height') != 720 or v.get('width', 0) > 1280:
            print(f"Formato recebido: {v.get('codec_name')} {v.get('width')}x{v.get('height')}. Esperado: H.264 em 720p.")
            return False
        etapa = 'Decodificação de vídeo'
        p = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-rw_timeout', '12000000',
            '-i', url, '-map', '0:v:0', '-map', '0:a:0?', '-t', '2',
            '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'],
            capture_output=True, timeout=30)
        frames = [int(x) for x in re.findall(rb'frame=(\d+)', p.stdout)]
        if p.returncode:
            return falha(etapa, p.stderr)
        if not frames or max(frames) == 0:
            print('O player não conseguiu decodificar nenhum quadro.')
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f'{etapa}: tempo limite excedido.')
        return False
    except (ValueError, OSError) as erro:
        print(f'{etapa}: {type(erro).__name__}.')
        return False

def montar(urls):
    linhas = ['#EXTM3U']
    for url in sorted(urls, key=lambda u: FONTES_PUBLICAS[u][0]):
        nome, grupo, epg = FONTES_PUBLICAS[url]
        linhas += [f'#EXTINF:-1 tvg-id="{epg}" group-title="{grupo}",{nome}', url]
    return '\n'.join(linhas) + '\n'

def publicar(conteudo):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('Defina GITHUB_TOKEN fora do código.')
    endpoint = f'https://api.github.com/repos/{REPO}/contents/{DESTINO}'
    payload = {'message': 'Atualiza canais públicos HD verificados', 'branch': 'main',
               'content': base64.b64encode(conteudo.encode()).decode()}
    try:
        atual = json.loads(request(endpoint + '?ref=main', token=token))
        if base64.b64decode(atual.get('content', '')).decode() == conteudo:
            print('GitHub já está atualizado.')
            return
        payload['sha'] = atual['sha']
    except HTTPError as e:
        if e.code != 404:
            raise
    request(endpoint, payload, token)
    print(f'Publicado: {REPO}/{DESTINO}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publicar', action='store_true')
    args = parser.parse_args()
    if not all(shutil.which(x) for x in ('ffmpeg', 'ffprobe')):
        parser.error('Instale FFmpeg e adicione ffmpeg e ffprobe ao PATH.')
    candidatos = extrair(request(CATALOGO).decode('utf-8-sig'))
    bons = []
    for url in candidatos:
        nome = FONTES_PUBLICAS[url][0]
        for tentativa in range(2):
            if verificar(url):
                bons.append(url)
                print(f'OK: {nome}')
                break
            if tentativa == 0:
                time.sleep(2)
        else:
            print(f'Indisponível ou fora de H.264/720p: {nome}')
    # Nenhuma lista vazia é gravada/publicada. Falha transitória mantém o anterior.
    if not bons:
        print('Nenhum canal aprovado. Lista anterior preservada.')
        return 2
    conteudo = montar(bons)
    caminho = Path(DESTINO)
    temporario = caminho.with_suffix('.m3u.tmp')
    temporario.write_text(conteudo, encoding='utf-8')
    temporario.replace(caminho)
    print(f'{len(bons)} canal(is) verificado(s); arquivo: {DESTINO}')
    if args.publicar:
        publicar(conteudo)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        # Não registrar respostas, credenciais nem URLs redirecionadas.
        print(f'Atualização interrompida ({type(e).__name__}). GitHub não confirmado.', file=sys.stderr)
        sys.exit(1)
