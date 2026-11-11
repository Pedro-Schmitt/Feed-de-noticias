"""Coleta as principais notícias do Brasil a partir dos feeds RSS dos veículos."""

import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests

TIMEOUT = 20
JANELA = timedelta(hours=48)  # notícias mais antigas que isso ficam de fora
JANELA_DESTAQUES = timedelta(hours=24)
MAX_POR_FEED = 40
MAX_DESTAQUES = 8
TAMANHO_RESUMO = 240

CATEGORIAS = {
    "politica": "Política",
    "economia": "Economia",
    "brasil": "Brasil",
    "mundo": "Mundo",
    "esportes": "Esportes",
    "saude": "Saúde",
    "tecnologia": "Tecnologia",
}

# (veículo, categoria, url). Os feeds por editoria vêm antes dos gerais: quando a
# mesma notícia aparece nos dois, vale a categoria da editoria.
FEEDS = [
    ("G1", "politica", "https://g1.globo.com/rss/g1/politica/"),
    ("G1", "economia", "https://g1.globo.com/rss/g1/economia/"),
    ("G1", "mundo", "https://g1.globo.com/rss/g1/mundo/"),
    ("G1", "saude", "https://g1.globo.com/rss/g1/saude/"),
    ("G1", "tecnologia", "https://g1.globo.com/rss/g1/tecnologia/"),
    ("ge", "esportes", "https://ge.globo.com/rss/ge/"),
    ("Folha", "politica", "https://feeds.folha.uol.com.br/poder/rss091.xml"),
    ("Folha", "economia", "https://feeds.folha.uol.com.br/mercado/rss091.xml"),
    ("Folha", "mundo", "https://feeds.folha.uol.com.br/mundo/rss091.xml"),
    ("Folha", "esportes", "https://feeds.folha.uol.com.br/esporte/rss091.xml"),
    ("Folha", "saude", "https://feeds.folha.uol.com.br/equilibrioesaude/rss091.xml"),
    ("Folha", "tecnologia", "https://feeds.folha.uol.com.br/tec/rss091.xml"),
    ("Estadão", "politica", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/"),
    ("Estadão", "economia", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/"),
    ("Estadão", "mundo", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/internacional/"),
    ("Estadão", "esportes", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/esportes/"),
    ("Estadão", "brasil", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/brasil/"),
    ("Agência Brasil", "politica", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Brasil", "economia", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("Agência Brasil", "mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
    ("Agência Brasil", "esportes", "https://agenciabrasil.ebc.com.br/rss/esportes/feed.xml"),
    ("Agência Brasil", "saude", "https://agenciabrasil.ebc.com.br/rss/saude/feed.xml"),
    # Feeds gerais: a categoria é deduzida do endereço da notícia
    ("G1", None, "https://g1.globo.com/rss/g1/"),
    ("Folha", None, "https://feeds.folha.uol.com.br/emcimadahora/rss091.xml"),
    ("Agência Brasil", None, "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"),
    ("CNN Brasil", None, "https://www.cnnbrasil.com.br/feed/"),
    ("Poder360", None, "https://www.poder360.com.br/feed/"),
    ("BBC Brasil", None, "https://feeds.bbci.co.uk/portuguese/rss.xml"),
]

# Trechos do caminho da URL que indicam a editoria (usados nos feeds gerais)
SEGMENTOS = {
    "politica": "politica", "poder": "politica",
    "economia": "economia", "mercado": "economia", "economia-e-negocios": "economia",
    "mundo": "mundo", "internacional": "mundo", "poder-internacional": "mundo",
    "esporte": "esportes", "esportes": "esportes", "futebol": "esportes",
    "saude": "saude", "equilibrioesaude": "saude", "ciencia-e-saude": "saude",
    "tecnologia": "tecnologia", "tec": "tecnologia", "link": "tecnologia",
}

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}

PALAVRAS_VAZIAS = set(
    "a ao aos apos as ate com como contra da das de do dos e ela ele em entre era foi "
    "ha isso mais mas na nas nem no nos o os ou para pela pelas pelo pelos por que se "
    "sem ser sera sobre sua suas seu seus tem ter um uma umas uns vai diz dizem apos "
    "nao sim ja ainda quem onde quando qual quais nesta neste hoje agora veja deixa "
    "deixam apos durante".split()
)


def _texto(no, caminho):
    return (no.findtext(caminho, default="", namespaces=NS) or "").strip()


def _sem_html(texto):
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def _resumir(texto):
    if len(texto) <= TAMANHO_RESUMO:
        return texto
    corte = texto[:TAMANHO_RESUMO].rsplit(" ", 1)[0]
    return corte.rstrip(",.;:") + "…"


def _limpar_link(link):
    # A Folha passa os links por um redirecionador: .../rss091/*https://www1.folha...
    if "/*http" in link:
        link = link.split("/*", 1)[1]
    partes = urlsplit(link)
    if partes.netloc.endswith("bbc.com"):  # parâmetros de rastreamento do RSS
        link = partes._replace(query="").geturl()
    return link


def _chave_link(link):
    partes = urlsplit(link)
    return partes.netloc.removeprefix("www.") + partes.path.rstrip("/")


def _categoria_pela_url(link):
    partes = urlsplit(link)
    if partes.netloc.startswith("ge.globo.com"):
        return "esportes"
    for segmento in partes.path.strip("/").split("/")[:2]:
        if segmento in SEGMENTOS:
            return SEGMENTOS[segmento]
    return "brasil"


def _imagem(item):
    for caminho in ("media:content", "media:thumbnail", "enclosure"):
        no = item.find(caminho, NS)
        if no is not None and no.get("url") and no.get("medium", "image") == "image":
            if caminho != "enclosure" or no.get("type", "").startswith("image"):
                url = no.get("url")
                # A BBC manda miniaturas de 240px; a mesma imagem existe em 480px
                return url.replace("/ace/ws/240/", "/ace/ws/480/")
    destaque = _texto(item, "imagem-destaque")  # Agência Brasil
    if destaque:
        return destaque
    for caminho in ("description", "content:encoded"):
        achou = re.search(r'<img[^>]+src="(https://[^"]+)"', item.findtext(caminho, "", NS) or "")
        if achou:
            return html.unescape(achou.group(1))
    return None


def _data(item):
    texto = _texto(item, "pubDate")
    if not texto:
        return None
    try:
        data = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return None
    if data.tzinfo is None:  # "-0000" vira data sem fuso: é UTC
        data = data.replace(tzinfo=timezone.utc)
    return data.astimezone(timezone.utc)


def _ler_xml(conteudo):
    try:
        return ET.fromstring(conteudo)
    except ET.ParseError:
        # Alguns feeds trazem "&" sem escapar; corrige e tenta de novo
        texto = conteudo.decode("utf-8", errors="replace")
        texto = re.sub(r"&(?!#?\w+;)", "&amp;", texto)
        texto = re.sub(r"^<\?xml[^>]*\?>", "", texto.lstrip())
        return ET.fromstring(texto)


def buscar_feed(veiculo, categoria, url):
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    raiz = _ler_xml(resp.content)
    limite = datetime.now(timezone.utc) - JANELA
    noticias = []
    for item in raiz.iter("item"):
        titulo = _sem_html(_texto(item, "title"))
        link = _limpar_link(_texto(item, "link"))
        data = _data(item)
        if not titulo or not link or data is None or data < limite:
            continue
        resumo = (
            _texto(item, "atom:subtitle")
            or _sem_html(_texto(item, "description"))
            or _sem_html(_texto(item, "content:encoded"))
        )
        noticias.append({
            "titulo": titulo,
            "resumo": _resumir(resumo),
            "link": link,
            "fonte": veiculo,
            "categoria": categoria or _categoria_pela_url(link),
            "data": data.isoformat(timespec="seconds"),
            "imagem": _imagem(item),
        })
        if len(noticias) >= MAX_POR_FEED:
            break
    return noticias


# --- Destaques: assuntos que aparecem em vários veículos ao mesmo tempo ---

def _palavras(titulo):
    sem_acento = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode()
    palavras = re.findall(r"[a-z0-9]+", sem_acento)
    # Os 6 primeiros caracteres bastam para juntar "presidente"/"presidencia", "tarifa"/"tarifas"
    return {p[:6] for p in palavras if len(p) >= 3 and p not in PALAVRAS_VAZIAS}


def _mesmo_assunto(a, b):
    comuns = len(a & b)
    return comuns >= 3 and comuns / min(len(a), len(b)) >= 0.45


def agrupar_assuntos(noticias):
    """Junta notícias recentes de veículos diferentes que tratam do mesmo assunto."""
    limite = datetime.now(timezone.utc) - JANELA_DESTAQUES
    recentes = [
        i for i, n in enumerate(noticias) if datetime.fromisoformat(n["data"]) >= limite
    ]
    palavras = {i: _palavras(noticias[i]["titulo"]) for i in recentes}
    pai = {i: i for i in recentes}

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for pos, i in enumerate(recentes):
        for j in recentes[pos + 1:]:
            if noticias[i]["fonte"] != noticias[j]["fonte"] and _mesmo_assunto(palavras[i], palavras[j]):
                pai[raiz(j)] = raiz(i)

    grupos = {}
    for i in recentes:
        grupos.setdefault(raiz(i), []).append(i)
    return [g for g in grupos.values() if len({noticias[i]["fonte"] for i in g}) >= 2]


def escolher_destaques(noticias):
    destaques = []
    for grupo in agrupar_assuntos(noticias):
        # Uma notícia por veículo (a mais recente), começando pela que tem foto e resumo
        por_fonte = {}
        for i in sorted(grupo, key=lambda i: noticias[i]["data"], reverse=True):
            por_fonte.setdefault(noticias[i]["fonte"], i)
        ids = sorted(
            por_fonte.values(),
            key=lambda i: (noticias[i]["imagem"] is not None, len(noticias[i]["resumo"])),
            reverse=True,
        )
        for i in grupo:
            noticias[i]["veiculos_assunto"] = len(por_fonte)
        destaques.append({
            "principal": ids[0],
            "relacionadas": ids[1:],
            "veiculos": len(por_fonte),
            "data": max(noticias[i]["data"] for i in grupo),
        })
    destaques.sort(key=lambda d: (d["veiculos"], d["data"]), reverse=True)
    return destaques[:MAX_DESTAQUES]


def coletar():
    """Busca todos os feeds em paralelo e devolve as notícias e os destaques."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        futuros = [executor.submit(buscar_feed, *feed) for feed in FEEDS]

    noticias, vistos, falhas = [], set(), []
    for (veiculo, _, url), futuro in zip(FEEDS, futuros):
        try:
            itens = futuro.result()
        except Exception as erro:
            print(f"[coletor] Falha em {veiculo} ({url}): {erro}")
            falhas.append(url)
            continue
        for item in itens:
            chave = _chave_link(item["link"])
            if chave not in vistos:
                vistos.add(chave)
                noticias.append(item)

    noticias.sort(key=lambda n: n["data"], reverse=True)
    for i, noticia in enumerate(noticias):
        noticia["id"] = i
    destaques = escolher_destaques(noticias)

    return {
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categorias": CATEGORIAS,
        "fontes": sorted({veiculo for veiculo, _, _ in FEEDS}),
        "feeds": len(FEEDS),
        "falhas": falhas,
        "destaques": destaques,
        "noticias": noticias,
    }


if __name__ == "__main__":
    dados = coletar()
    print(f"{len(dados['noticias'])} notícias, {len(dados['falhas'])} feeds com falha")
    for d in dados["destaques"]:
        n = dados["noticias"][d["principal"]]
        print(f"  [{d['veiculos']} veículos] {n['fonte']}: {n['titulo']}")
        for i in d["relacionadas"]:
            print(f"        - {dados['noticias'][i]['fonte']}: {dados['noticias'][i]['titulo']}")
