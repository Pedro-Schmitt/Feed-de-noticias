"""Coleta as principais notícias do Brasil a partir dos feeds RSS dos veículos."""

import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import requests

import editais
import informativos

TIMEOUT = 20
JANELA = timedelta(hours=48)  # notícias mais antigas que isso ficam de fora
JANELA_RECENTES = timedelta(hours=24)  # na escolha das principais, as das últimas 24h vêm antes
MAX_POR_FEED = 40
POR_SECAO = 5
POR_EDITORIA = 20  # a página mostra cinco e o botão "Carregar mais notícias" o resto
TAMANHO_RESUMO = 240

# Editorias exibidas no site, na ordem da página
SECOES = ["politica", "economia", "tecnologia", "mundo"]

# Esportes não aparece no site: as notícias dessa editoria são descartadas
IGNORADAS = {"esportes"}

# Todas as editorias reconhecidas, para classificar as notícias dos feeds gerais
CATEGORIAS = {
    "politica": "Política",
    "economia": "Economia",
    "brasil": "Brasil",
    "mundo": "Mundo",
    "esportes": "Esportes",
    "saude": "Saúde",
    "tecnologia": "Tecnologia e Cibersegurança",
}

# (veículo, categoria, url). Os feeds por editoria vêm antes dos gerais: quando a
# mesma notícia aparece nos dois, vale a categoria da editoria.
FEEDS = [
    ("G1", "politica", "https://g1.globo.com/rss/g1/politica/"),
    ("G1", "economia", "https://g1.globo.com/rss/g1/economia/"),
    ("G1", "mundo", "https://g1.globo.com/rss/g1/mundo/"),
    ("G1", "tecnologia", "https://g1.globo.com/rss/g1/tecnologia/"),
    ("Folha", "politica", "https://feeds.folha.uol.com.br/poder/rss091.xml"),
    ("Folha", "economia", "https://feeds.folha.uol.com.br/mercado/rss091.xml"),
    ("Folha", "mundo", "https://feeds.folha.uol.com.br/mundo/rss091.xml"),
    ("Folha", "tecnologia", "https://feeds.folha.uol.com.br/tec/rss091.xml"),
    ("Estadão", "politica", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/"),
    ("Estadão", "economia", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/"),
    ("Estadão", "mundo", "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/internacional/"),
    ("Agência Brasil", "politica", "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    ("Agência Brasil", "economia", "https://agenciabrasil.ebc.com.br/rss/economia/feed.xml"),
    ("Agência Brasil", "mundo", "https://agenciabrasil.ebc.com.br/rss/internacional/feed.xml"),
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
        categoria_noticia = categoria or _categoria_pela_url(link)
        if categoria_noticia in IGNORADAS:
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
            "categoria": categoria_noticia,
            "data": data.isoformat(timespec="seconds"),
            "imagem": _imagem(item),
        })
        if len(noticias) >= MAX_POR_FEED:
            break
    return noticias


# --- Principais: os assuntos noticiados por mais veículos, em cada editoria ---

def _palavras(titulo):
    sem_acento = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode()
    palavras = re.findall(r"[a-z0-9]+", sem_acento)
    # Os 6 primeiros caracteres bastam para juntar "presidente"/"presidencia", "tarifa"/"tarifas"
    return {p[:6] for p in palavras if len(p) >= 3 and p not in PALAVRAS_VAZIAS}


def _mesmo_assunto(a, b):
    comuns = len(a & b)
    return comuns >= 3 and comuns / min(len(a), len(b)) >= 0.45


def agrupar_assuntos(noticias):
    """Junta as notícias de veículos diferentes que tratam do mesmo assunto.
    Devolve uma lista de grupos (listas de índices); notícias sem par ficam sozinhas."""
    palavras = [_palavras(n["titulo"]) for n in noticias]
    pai = list(range(len(noticias)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    for i in range(len(noticias)):
        for j in range(i + 1, len(noticias)):
            if noticias[i]["fonte"] != noticias[j]["fonte"] and _mesmo_assunto(palavras[i], palavras[j]):
                pai[raiz(j)] = raiz(i)

    grupos = {}
    for i in range(len(noticias)):
        grupos.setdefault(raiz(i), []).append(i)
    return list(grupos.values())


def _candidato(noticias, grupo, opcoes, limite):
    """Resume um assunto: (chave de ordenação, notícia exibida, {veículo: notícia}).

    Vale mais o assunto noticiado por mais veículos; no empate, o mais recente.
    Assuntos com notícia depois de `limite` vêm antes dos mais antigos.
    """
    # Uma notícia por veículo (a mais recente)
    por_fonte = {}
    for i in sorted(grupo, key=lambda i: noticias[i]["data"], reverse=True):
        por_fonte.setdefault(noticias[i]["fonte"], i)
    # A notícia exibida sai de `opcoes`: de preferência de um veículo de FONTES_PREFERIDAS
    # (só as buscas jurídicas misturam sites pequenos), depois com foto e resumo
    principal = max(
        opcoes,
        key=lambda i: (
            noticias[i]["fonte"] in FONTES_PREFERIDAS,
            noticias[i]["imagem"] is not None,
            bool(noticias[i]["resumo"]),
            noticias[i]["data"],
        ),
    )
    mais_recente = max(noticias[i]["data"] for i in grupo)
    return (mais_recente >= limite, len(por_fonte), mais_recente), principal, por_fonte


def _montar(noticias, principal, por_fonte):
    fonte = noticias[principal]["fonte"]
    return {
        **{k: v for k, v in noticias[principal].items() if k not in ("categoria", "ciber")},
        "veiculos": len(por_fonte),
        "relacionadas": [
            {k: noticias[i][k] for k in ("fonte", "titulo", "link")}
            for f, i in por_fonte.items() if f != fonte
        ],
    }


# Cibersegurança entra em Tecnologia por uma busca no Google Notícias (os feeds de tecnologia
# quase não tratam do tema). No máximo MAXIMO_CIBER de cada cinco assuntos vêm só dessa busca,
# para a editoria não virar só de cibersegurança
BUSCA_CIBER = ('(cibersegurança OR "segurança cibernética" OR ciberataque OR "ataque hacker" OR ransomware '
               'OR "vazamento de dados" OR hackers OR "crime cibernético" OR "golpe digital") when:2d')
MAXIMO_CIBER = 2


def escolher_principais(noticias):
    """As POR_EDITORIA notícias principais de cada editoria em SECOES.
    Cada assunto aparece em uma editoria só (a primeira de SECOES em que ele entra)."""
    limite = (datetime.now(timezone.utc) - JANELA_RECENTES).isoformat()
    grupos = agrupar_assuntos(noticias)
    usados = set()
    secoes = []
    for secao in SECOES:
        candidatos = []
        for g, grupo in enumerate(grupos):
            da_secao = [i for i in grupo if noticias[i]["categoria"] == secao]
            if g not in usados and da_secao:
                candidatos.append((g, *_candidato(noticias, grupo, da_secao, limite)))

        candidatos.sort(key=lambda c: c[1], reverse=True)
        escolhidas, ciber = [], 0
        for g, _, principal, por_fonte in candidatos:
            if len(escolhidas) == POR_EDITORIA:
                break
            so_ciber = all(noticias[i].get("ciber") for i in grupos[g] if noticias[i]["categoria"] == secao)
            if so_ciber:
                # No máximo MAXIMO_CIBER a cada cinco (as cinco que aparecem primeiro, as dez seguintes...)
                if ciber >= MAXIMO_CIBER * (len(escolhidas) // 5 + 1):
                    continue
                ciber += 1
            usados.add(g)
            escolhidas.append(_montar(noticias, principal, por_fonte))
        secoes.append({"id": secao, "nome": CATEGORIAS[secao], "noticias": escolhidas})
    return secoes


# --- Miniaturas: notícias sem foto no feed (Folha, buscas do Google Notícias) ---

NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
_META_IMAGEM = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)["'][^>]*>""", re.I)
_CONTEUDO = re.compile(r"""content=["']([^"']+)""")


def _link_real(link):
    """O endereço da notícia por trás de um link do Google Notícias (que só redireciona via JavaScript)."""
    if "news.google.com" not in link:
        return link
    id_ = link.split("/articles/")[1].split("?")[0]
    pagina = requests.get(f"https://news.google.com/rss/articles/{id_}", headers=NAVEGADOR, timeout=10).text
    assinatura = re.search(r'data-n-a-sg="([^"]+)"', pagina).group(1)
    momento = re.search(r'data-n-a-ts="([^"]+)"', pagina).group(1)
    pedido = ["Fbv4je", f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                        f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{id_}",{momento},"{assinatura}"]']
    resp = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        headers={**NAVEGADOR, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        data="f.req=" + quote(json.dumps([[pedido]])),
        timeout=10,
    )
    return json.loads(json.loads(resp.text.split("\n\n")[1])[0][2])[1]


def _imagem_da_pagina(link):
    """A imagem de compartilhamento (og:image) da página da notícia, ou None."""
    try:
        pagina = requests.get(_link_real(link), headers=NAVEGADOR, timeout=10).text
        meta = _META_IMAGEM.search(pagina)
        url = meta and _CONTEUDO.search(meta.group(0))
        url = url and html.unescape(url.group(1))
        # Logotipo do veículo não serve de miniatura
        return url if url and url.startswith("https://") and "logo" not in url.lower() else None
    except Exception:
        return None


def completar_imagens(secoes):
    """Busca na página da notícia a imagem das que não vieram com foto."""
    sem_imagem = [n for secao in secoes for n in secao["noticias"] if not n.get("imagem")]
    with ThreadPoolExecutor(max_workers=8) as executor:
        for noticia, imagem in zip(sem_imagem, executor.map(lambda n: _imagem_da_pagina(n["link"]), sem_imagem)):
            noticia["imagem"] = imagem


# --- Notícias jurídicas: buscas no Google Notícias, que junta sites oficiais e imprensa ---

GOOGLE_NOTICIAS = "https://news.google.com/rss/search"

# (id, nome, busca). O "when:" limita a idade das notícias; o CSMP publica pouco,
# por isso olha um período bem maior
JURIDICO = [
    ("mpgo", "MPGO", '(MPGO OR "MP-GO" OR "Ministério Público de Goiás" OR "Ministério Público do Estado de Goiás") when:7d'),
    ("csmp", "CSMP do MPGO",
     '("Conselho Superior" OR CSMP) (MPGO OR "MP-GO" OR "Ministério Público de Goiás" OR "MP de Goiás") when:60d'),
    ("mp", "Outros MPs do País", '"Ministério Público" when:2d'),
    ("stf", "STF", "STF when:2d"),
    ("stj", "STJ", "STJ when:3d"),
    ("tjgo", "TJGO", '(TJGO OR "TJ-GO" OR "Tribunal de Justiça de Goiás") when:7d'),
]

# Notícias que vão acima da agenda do Presidente, do Senado e da Câmara (mesmo critério das jurídicas)
ORGAOS = [
    ("presidente", '(Lula OR "Presidente da República" OR Planalto) when:2d'),
    ("senado", '(Senado OR senadores) when:2d'),
    ("camara", '("Câmara dos Deputados" OR deputados) when:2d'),
]
POR_ORGAO = 3



FONTES_IGNORADAS = {"Instagram", "Facebook", "YouTube", "X", "TikTok", "LinkedIn"}

# Quando vários veículos dão o mesmo assunto, mostra a versão de um destes
# (nomes como aparecem no Google Notícias); os feeds RSS do site já são todos daqui
FONTES_PREFERIDAS = {
    # Sites oficiais
    "STF", "stf noticias", "Supremo Tribunal Federal", "STJ", "Superior Tribunal de Justiça",
    "Tribunal de Justiça do Estado de Goiás", "Portal MPGO", "Portal CNJ",
    "Ministério Público Federal", "MPF", "CNMP", "Conselho Nacional do Ministério Público",
    # Imprensa jurídica
    "Consultor Jurídico", "Migalhas", "JOTA Info", "Rota Jurídica",
    # Grandes veículos
    "G1", "O GLOBO", "Folha de S.Paulo", "Estadão", "CNN Brasil", "UOL Notícias",
    "Agência Brasil", "Poder360", "BBC News Brasil", "Valor Econômico", "VEJA",
    "Correio Braziliense", "Jornal Opção", "O Popular", "Mais Goiás", "A Redação",
}


def buscar_google_noticias(busca):
    resp = requests.get(
        GOOGLE_NOTICIAS,
        params={"q": busca, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"},
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    noticias = []
    for item in _ler_xml(resp.content).iter("item"):
        fonte = _texto(item, "source")
        titulo = _sem_html(_texto(item, "title"))
        if fonte and titulo.endswith(f" - {fonte}"):  # o Google acrescenta " - Veículo" ao título
            titulo = titulo[: -len(fonte) - 3]
        titulo = re.sub(r"(\s+#\w+)+$", "", titulo)  # hashtags no fim (ex.: "#Shorts")
        link = _texto(item, "link")
        data = _data(item)
        if not titulo or not link or data is None or not fonte or fonte in FONTES_IGNORADAS:
            continue
        noticias.append({
            "titulo": titulo,
            "resumo": "",
            "link": link,
            "fonte": fonte,
            "data": data.isoformat(timespec="seconds"),
            "imagem": None,
        })
    noticias.sort(key=lambda n: n["data"], reverse=True)
    return noticias


# --- De qual Ministério Público trata a notícia (quadro "Outros MPs do País") ---

# Ramos do Ministério Público da União e afins: (sigla, nome, padrão)
RAMOS_MPU = [
    ("MPDFT", "DF e Territórios", r"\bMPDFT\b|Minist[ée]rio P[úu]blico do Distrito Federal"),
    ("MPT", "Trabalho", r"\bMPT\b|Minist[ée]rio P[úu]blico do Trabalho"),
    ("MPM", "Militar", r"\bMPM\b|Minist[ée]rio P[úu]blico Militar"),
    ("MP Eleitoral", "Eleitoral", r"Minist[ée]rio P[úu]blico Eleitoral|\bMPE\b"),
    ("MP de Contas", "Contas", r"Minist[ée]rio P[úu]blico (?:de|junto ao) (?:Contas|Tribunal de Contas)|\bMPC\b"),
    ("MPF", "Federal", r"\bMPF\b|Minist[ée]rio P[úu]blico Federal|\bPGR\b|Procuradoria-Geral da Rep[úu]blica"),
]

# Estados: (UF, nome, outros termos: capital, cidades grandes e gentílico). Nomes compostos
# vêm antes dos que contêm ("Mato Grosso do Sul" antes de "Mato Grosso"). Ficam de fora
# cidades com nome ambíguo, como Natal (o feriado), Vitória e Santos
ESTADOS = [
    ("MS", "Mato Grosso do Sul", ["Campo Grande", "sul-mato-grossense"]),
    ("MT", "Mato Grosso", ["Cuiabá", "mato-grossense"]),
    ("RN", "Rio Grande do Norte", ["potiguar"]),
    ("RS", "Rio Grande do Sul", ["Porto Alegre", "gaúcho", "gaúcha"]),
    ("RJ", "Rio de Janeiro", ["fluminense", "carioca", "Niterói"]),
    ("ES", "Espírito Santo", ["capixaba"]),
    ("SP", "São Paulo", ["paulista", "Campinas", "Ribeirão Preto"]),
    ("MG", "Minas Gerais", ["Belo Horizonte", "mineiro", "mineira"]),
    ("BA", "Bahia", ["Salvador", "baiano", "baiana"]),
    ("PR", "Paraná", ["Curitiba", "paranaense", "Londrina"]),
    ("SC", "Santa Catarina", ["Florianópolis", "catarinense", "Joinville"]),
    ("GO", "Goiás", ["Goiânia", "goiano", "goiana", "Anápolis"]),
    ("DF", "Distrito Federal", ["Brasília", "brasiliense"]),
    ("PE", "Pernambuco", ["Recife", "pernambucano", "pernambucana"]),
    ("CE", "Ceará", ["Fortaleza", "cearense"]),
    ("PA", "Pará", ["Belém", "paraense"]),
    ("AM", "Amazonas", ["Manaus", "amazonense"]),
    ("MA", "Maranhão", ["São Luís", "maranhense"]),
    ("PI", "Piauí", ["Teresina", "piauiense"]),
    ("PB", "Paraíba", ["João Pessoa", "paraibano", "paraibana"]),
    ("AL", "Alagoas", ["Maceió", "alagoano", "alagoana"]),
    ("SE", "Sergipe", ["Aracaju", "sergipano", "sergipana"]),
    ("TO", "Tocantins", ["Palmas", "tocantinense"]),
    ("RO", "Rondônia", ["Porto Velho", "rondoniense"]),
    ("AC", "Acre", ["Rio Branco", "acreano", "acriano"]),
    ("AP", "Amapá", ["Macapá", "amapaense"]),
    ("RR", "Roraima", ["Boa Vista", "roraimense"]),
]
_PADROES_ESTADOS = [
    (uf, nome,
     re.compile(rf"\bMP-?{uf}\b|\bMPE-?{uf}\b|Minist[ée]rio P[úu]blico (?:do Estado )?(?:d[eoa] )?{nome}"),
     # nome do estado, cidades e a sigla depois de preposição ("vice-prefeito de SP"): com
     # maiúscula e palavra inteira (para "Pará" não pegar "para")
     re.compile(r"\b(?:" + "|".join(re.escape(t) for t in [nome] + [o for o in outros if o[0].isupper()])
                + rf"|(?:de|do|da|em|no|na) {uf})\b"),
     # gentílicos ("paulista", "Associação Paulista..."): sem diferenciar maiúscula. Sem nenhum,
     # o padrão nunca casa (um "(?:)" vazio casaria com qualquer texto)
     re.compile(r"\b(?:" + ("|".join(re.escape(o) for o in outros if o[0].islower()) or r"(?!x)x") + r")\b", re.I))
    for uf, nome, outros in ESTADOS
]


def identificar_mp(noticia):
    """{"sigla", "nome"} do MP de que a notícia trata, ou None se não der para saber."""
    texto = f"{noticia['titulo']} {noticia['fonte']}"
    for uf, nome, explicito, _, _ in _PADROES_ESTADOS:  # sigla ou nome do MP estadual
        if explicito.search(texto):
            return {"sigla": f"MP{uf}", "nome": nome}
    for sigla, nome, padrao in RAMOS_MPU:
        if re.search(padrao, texto):
            return {"sigla": sigla, "nome": nome}
    for uf, nome, _, local, gentilico in _PADROES_ESTADOS:  # só o estado, a cidade ou o gentílico
        if local.search(texto) or gentilico.search(texto):
            return {"sigla": f"MP{uf}", "nome": nome}
    return None


def escolher_juridicas(noticias, quantidade=POR_SECAO):
    """As principais de uma busca jurídica, pelo mesmo critério das editorias."""
    limite = (datetime.now(timezone.utc) - JANELA_RECENTES).isoformat()
    candidatos = [_candidato(noticias, grupo, grupo, limite) for grupo in agrupar_assuntos(noticias)]
    candidatos.sort(key=lambda c: c[0], reverse=True)
    return [_montar(noticias, principal, por_fonte) for _, principal, por_fonte in candidatos[:quantidade]]


def _resultado_ou_none(futuro, nome):
    try:
        return futuro.result()
    except Exception as erro:  # sem essa parte, o resto do site continua
        print(f"[coletor] Falha em {nome}: {erro}")
        return None


def coletar():
    """Busca todos os feeds em paralelo e devolve as principais notícias de cada editoria."""
    with ThreadPoolExecutor(max_workers=10) as executor:
        futuros = [executor.submit(buscar_feed, *feed) for feed in FEEDS]
        futuros_juridico = [executor.submit(buscar_google_noticias, busca) for _, _, busca in JURIDICO]
        futuro_ciber = executor.submit(buscar_google_noticias, BUSCA_CIBER)
        futuros_orgaos = [executor.submit(buscar_google_noticias, busca) for _, busca in ORGAOS]
        futuro_informativos = executor.submit(informativos.coletar)
        futuro_editais = executor.submit(editais.coletar)

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

    try:
        for item in futuro_ciber.result():
            chave = _chave_link(item["link"])
            if chave not in vistos:
                vistos.add(chave)
                noticias.append({**item, "categoria": "tecnologia", "ciber": True})
    except Exception as erro:  # sem a busca, Tecnologia fica só com os feeds
        print(f"[coletor] Falha na busca de cibersegurança: {erro}")
        falhas.append("Google Notícias: cibersegurança")

    noticias.sort(key=lambda n: n["data"], reverse=True)

    secoes = escolher_principais(noticias)
    completar_imagens(secoes)

    juridico = []
    for (id_, nome, busca), futuro in zip(JURIDICO, futuros_juridico):
        try:
            # O MPGO mostra sete: o quadro dele, na linha inteira, tem mais espaço
            escolhidas = escolher_juridicas(futuro.result(), 7 if id_ == "mpgo" else POR_SECAO)
        except Exception as erro:
            print(f"[coletor] Falha na busca jurídica {nome}: {erro}")
            falhas.append(f"Google Notícias: {nome}")
            escolhidas = []
        if id_ == "mp":
            for noticia in escolhidas:
                noticia["mp"] = identificar_mp(noticia)
        juridico.append({"id": id_, "nome": nome, "noticias": escolhidas})

    orgaos = {}
    for (id_, _), futuro in zip(ORGAOS, futuros_orgaos):
        try:
            orgaos[id_] = escolher_juridicas(futuro.result())[:POR_ORGAO]
        except Exception as erro:  # sem notícias, o quadro mostra só a agenda
            print(f"[coletor] Falha nas notícias de {id_}: {erro}")
            orgaos[id_] = None

    return {
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fontes": sorted({veiculo for veiculo, _, _ in FEEDS}),
        "total": len(noticias),
        "feeds": len(FEEDS) + len(JURIDICO) + 1,
        "falhas": falhas,
        "secoes": secoes,
        "juridico": juridico,
        "orgaos": orgaos,
        "informativos": futuro_informativos.result(),
        "editais": _resultado_ou_none(futuro_editais, "editais do MPGO"),
    }


if __name__ == "__main__":
    dados = coletar()
    print(f"{dados['total']} notícias, {len(dados['falhas'])} feeds com falha")
    for secao in dados["secoes"] + dados["juridico"]:
        print(f"\n== {secao['nome']}")
        for n in secao["noticias"]:
            print(f"  [{n['veiculos']}] {n['fonte']}: {n['titulo']}")
