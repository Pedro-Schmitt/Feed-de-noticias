"""Notícias da cidade e da região de cada promotoria do MPGO.

O promotor escolhe a promotoria em que trabalha; o site sabe a comarca dela pela lista oficial
do MPGO ("Conheça o MPGO > Promotorias de Justiça > Encontre uma promotoria") e a região pela
divisão do IBGE em regiões geográficas imediatas (ex.: Rialma fica em "Ceres - Rialma - Goianésia").

Como o site publicado é estático, as notícias de todas as comarcas e regiões são geradas antes,
aos poucos (o Google bloqueia muitas buscas seguidas): cada execução atualiza as mais antigas e
guarda tudo em regional/estado.json, que a execução seguinte lê do próprio site publicado.
"""

import html
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import coletor
import informativos

TIMEOUT = 30
LISTA_PROMOTORIAS = ("https://www.mpgo.mp.br/portal/arquivos/2024/09/25/14_38_13_51_Lista_das_Promotorias_de_"
                     "Justi_a_Minist_rio_P_blico_de_Goi_s.html_25_9_2024.html")
IBGE_GOIAS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/52/municipios?view=nivelado"
IBGE_BRASIL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"
# Cópia dos dados do IBGE guardada no projeto: a API do IBGE não responde aos servidores do
# GitHub Actions (fora do Brasil). Municípios e regiões quase nunca mudam; para atualizar,
# rode "python regional.py --atualizar-ibge" num computador no Brasil
ARQUIVO_IBGE = Path(__file__).with_name("dados") / "ibge_municipios.json"
SITE_PUBLICADO = os.environ.get("SITE_PUBLICADO", "https://feed-de-atualizacoes---pedro.web.app")

JANELA = timedelta(days=10)
CIDADES_POR_BUSCA = 7       # buscas longas demais fazem o Google devolver menos resultados
BUSCAS_POR_EXECUCAO = 60    # por execução do site estático (~1h30 para renovar as 170 buscas)
PAUSA_ENTRE_BUSCAS = 1.0    # segundos, para não parecer um robô apressado ao Google

# Nomes de cidade que também são palavras comuns ou nomes de outras coisas: só entram
# junto com "Goiás" (além das que existem em outros estados, achadas pela lista do IBGE)
NOMES_COMUNS = {"Posse", "Formosa", "Formoso", "Piranhas", "Mineiros", "Trindade", "Jataí", "Rio Verde",
                "Uruana", "Aragarças", "Inhumas", "Goiás", "Cristalina", "Porangatu", "Campos Belos"}

# Cidades que ficam fora das buscas de região: mesmo exigindo "Goiás", trazem notícias de
# outros lugares com o mesmo nome (Santa Isabel-SP, bairros e ruas São Patrício)
FORA_DAS_REGIOES = {"Santa Isabel", "São Patrício"}

CABECALHOS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def _get(url, **kwargs):
    resp = requests.get(url, timeout=TIMEOUT, headers=CABECALHOS, **kwargs)
    resp.raise_for_status()
    return resp


def _sem_acento(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower().strip()


def _slug(texto):
    return re.sub(r"[^a-z0-9]+", "-", _sem_acento(texto)).strip("-")


def _capitalizar(texto):
    """"1ª PROMOTORIA DE JUSTIÇA DE SÃO LUÍS DE MONTES BELOS" -> "1ª Promotoria de Justiça de São Luís de Montes Belos"."""
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    palavras = texto.lower().split()
    return " ".join(p if i and p in pequenas else p[:1].upper() + p[1:] for i, p in enumerate(palavras))


# --- Promotorias, comarcas e regiões ---

def ler_promotorias():
    """[{nome, comarca, atribuicao}] da lista oficial do MPGO (um cartão por promotoria)."""
    pagina = _get(LISTA_PROMOTORIAS).content.decode("utf-8")
    promotorias = []
    for bloco in re.split(r'<div class="comarca">', pagina)[1:]:
        comarca = re.search(r"<h2>\s*Comarca:\s*([^(<]+)", bloco)
        if not comarca:
            continue
        nome_comarca = html.unescape(comarca.group(1)).strip(" -")
        for nome, cartao in re.findall(r"<h3>(.*?)</h3>(.*?)(?=<h3>|$)", bloco, re.S):
            atribuicao = re.search(r"Atribui[çc][ãa]o:\s*</strong>(.*?)</p>", cartao, re.S)
            promotorias.append({
                "nome": _capitalizar(html.unescape(re.sub(r"<[^>]+>", "", nome)).strip()),
                "comarca": nome_comarca,
                "atribuicao": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", atribuicao.group(1)))).strip()
                              if atribuicao else "",
            })
    return promotorias


def montar_mapa():
    """Promotorias para o seletor e, para cada comarca, a cidade e a região com suas buscas.

    {"promotorias": [{nome, comarca}], "comarcas": {comarca: {cidade, regiao}},
     "locais": {id: {nome, tipo, buscas}}}
    """
    ibge = json.loads(ARQUIVO_IBGE.read_text(encoding="utf-8"))
    goias = ibge["goias"]
    fora_de_goias = set(ibge["nomes_fora_de_goias"])
    municipios = {_sem_acento(m["municipio-nome"]): m for m in goias}

    def ambiguo(nome):
        return nome in NOMES_COMUNS or _sem_acento(nome) in fora_de_goias

    def buscas(cidades, extra_ceres=False):
        unicas = [c for c in cidades if not ambiguo(c)]
        ambiguas = [c for c in cidades if ambiguo(c)]
        resultado = []
        for grupo, exige_goias in ((unicas, False), (ambiguas, True)):
            for i in range(0, len(grupo), CIDADES_POR_BUSCA):
                fatia = grupo[i:i + CIDADES_POR_BUSCA]
                frases = " OR ".join(f'"em {c}" OR "de {c}"' for c in fatia)
                resultado.append(f"({frases}){' Goiás' if exige_goias else ''} when:10d")
        return resultado

    locais, comarcas = {}, {}
    promotorias = ler_promotorias()
    for comarca in sorted({p["comarca"] for p in promotorias}):
        municipio = municipios.get(_sem_acento(comarca))
        if not municipio:
            print(f"[regional] Comarca sem município no IBGE: {comarca}")
            continue
        cidade = municipio["municipio-nome"]
        id_cidade = "cidade-" + _slug(cidade)
        if cidade == "Goiás":  # a antiga capital: "em Goiás" pegaria o estado inteiro
            busca_cidade = ['("Cidade de Goiás" OR "Goiás Velho") when:10d']
        else:
            frases = f'"em {cidade}" OR "de {cidade}" OR "{cidade}-GO" OR "{cidade} (GO)"'
            busca_cidade = [f"({frases}){' Goiás' if ambiguo(cidade) else ''} when:10d"]
        locais[id_cidade] = {"nome": cidade, "tipo": "cidade", "buscas": busca_cidade}

        regiao = municipio["regiao-imediata-nome"]
        id_regiao = "regiao-" + _slug(regiao)
        if id_regiao not in locais:
            vizinhas = sorted(m["municipio-nome"] for m in goias
                              if m["regiao-imediata-nome"] == regiao and m["municipio-nome"] != "Goiás"
                              and m["municipio-nome"] not in FORA_DAS_REGIOES)
            locais[id_regiao] = {"nome": f"Região de {regiao}", "tipo": "regiao", "buscas": buscas(vizinhas)}
        comarcas[comarca] = {"cidade": id_cidade, "regiao": id_regiao}

    return {
        "promotorias": [p for p in promotorias if p["comarca"] in comarcas],
        "comarcas": comarcas,
        "locais": locais,
    }


# --- Notícias de cada local ---

def noticias_do_local(local):
    """As cinco principais notícias recentes de uma cidade ou região."""
    limite = (datetime.now(timezone.utc) - JANELA).isoformat()
    itens, vistos = [], set()
    for busca in local["buscas"]:
        for noticia in coletor.buscar_google_noticias(busca):
            if noticia["data"] >= limite and noticia["link"] not in vistos:
                vistos.add(noticia["link"])
                itens.append(noticia)
        time.sleep(PAUSA_ENTRE_BUSCAS)
    itens.sort(key=lambda n: n["data"], reverse=True)
    return coletor.escolher_juridicas(itens)


def atualizar_estado(mapa, estado, orcamento=BUSCAS_POR_EXECUCAO):
    """Atualiza os locais nunca coletados e depois os mais antigos, até gastar o orçamento de buscas."""
    fila = sorted(mapa["locais"], key=lambda id_: estado.get(id_, {}).get("atualizado", ""))
    gastas = 0
    for id_ in fila:
        local = mapa["locais"][id_]
        if gastas and gastas + len(local["buscas"]) > orcamento:
            break
        try:
            noticias = noticias_do_local(local)
        except Exception as erro:  # Google recusou: para por aqui e tenta na próxima execução
            print(f"[regional] Falha em {local['nome']}: {erro}")
            break
        estado[id_] = {
            "nome": local["nome"],
            "tipo": local["tipo"],
            "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noticias": noticias,
        }
        gastas += len(local["buscas"])
    return gastas


def estado_publicado():
    """O estado da última publicação (lido do próprio site), para continuar de onde parou."""
    try:
        return _get(f"{SITE_PUBLICADO}/regional/estado.json").json()
    except Exception as erro:
        print(f"[regional] Sem estado anterior ({erro}): começa do zero")
        return {}


def dados_promotorias(mapa):
    """O que o seletor da página precisa: promotorias, comarca de cada uma e nome de cada local."""
    return {
        "promotorias": [{**p, **informativos.materias_da_atribuicao(p["atribuicao"])} for p in mapa["promotorias"]],
        "comarcas": mapa["comarcas"],
        "nomes": {id_: local["nome"] for id_, local in mapa["locais"].items()},
    }


def gerar(saida):
    """Grava promotorias.json, regional/estado.json e um regional/<id>.json por cidade e região."""
    mapa = montar_mapa()
    estado = estado_publicado()
    estado = {id_: v for id_, v in estado.items() if id_ in mapa["locais"]}
    gastas = atualizar_estado(mapa, estado)
    print(f"[regional] {gastas} buscas; {len(estado)} de {len(mapa['locais'])} locais com notícias")

    pasta = Path(saida) / "regional"
    pasta.mkdir(parents=True, exist_ok=True)
    escrever = lambda caminho, dados: caminho.write_text(
        json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    escrever(pasta / "estado.json", estado)
    for id_, dados in estado.items():
        escrever(pasta / f"{id_}.json", dados)
    escrever(Path(saida) / "promotorias.json", dados_promotorias(mapa))


def atualizar_ibge():
    """Baixa do IBGE os municípios de Goiás (com a região imediata) e os nomes dos demais."""
    goias = _get(IBGE_GOIAS).json()
    brasil = _get(IBGE_BRASIL).json()
    dados = {
        "goias": [{"municipio-nome": m["municipio-nome"], "regiao-imediata-nome": m["regiao-imediata-nome"]}
                  for m in goias],
        "nomes_fora_de_goias": sorted({_sem_acento(m["municipio-nome"]) for m in brasil if m["UF-sigla"] != "GO"}),
    }
    ARQUIVO_IBGE.parent.mkdir(exist_ok=True)
    ARQUIVO_IBGE.write_text(json.dumps(dados, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"[regional] {len(dados['goias'])} municípios de Goiás gravados em {ARQUIVO_IBGE}")


if __name__ == "__main__":
    import sys
    if "--atualizar-ibge" in sys.argv:
        atualizar_ibge()
        sys.exit()
    mapa = montar_mapa()
    print(len(mapa["promotorias"]), "promotorias,", len(mapa["comarcas"]), "comarcas,",
          len(mapa["locais"]), "locais,", sum(len(l["buscas"]) for l in mapa["locais"].values()), "buscas no total")
    rialma = mapa["comarcas"].get("Rialma")
    print("Rialma ->", rialma, [mapa["locais"][i] for i in rialma.values()] if rialma else "")
