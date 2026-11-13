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
# Cópia da lista de promotorias, usada quando o portal do MPGO está fora do ar (sem ela, o site
# sairia sem o seletor de promotoria e sem as notícias da região)
ARQUIVO_PROMOTORIAS = Path(__file__).with_name("dados") / "promotorias.json"
SITE_PUBLICADO = os.environ.get("SITE_PUBLICADO", "https://revista-do-promotor.web.app")
SITE_ANTIGO = "https://feed-de-atualizacoes---pedro.web.app"  # hoje redireciona para o novo

JANELA = timedelta(days=10)
CIDADES_POR_BUSCA = 7       # buscas longas demais fazem o Google devolver menos resultados
BUSCAS_POR_EXECUCAO = 90    # por execução do site estático (~2h15 para renovar as ~400 buscas)
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
    """[{nome, comarca, atribuicao}] da lista oficial do MPGO; com o portal fora do ar, a cópia do projeto."""
    try:
        return _ler_promotorias_do_portal()
    except Exception as erro:
        print(f"[regional] Portal do MPGO indisponível ({erro}); usando a cópia em {ARQUIVO_PROMOTORIAS.name}")
        return json.loads(ARQUIVO_PROMOTORIAS.read_text(encoding="utf-8"))


def _ler_promotorias_do_portal():
    """Lê a lista oficial do MPGO (um cartão por promotoria)."""
    pagina = _get(LISTA_PROMOTORIAS).content.decode("utf-8")
    promotorias = []
    for bloco in re.split(r'<div class="comarca">', pagina)[1:]:
        comarca = re.search(r"<h2>\s*Comarca:\s*([^(<]+)", bloco)
        if not comarca:
            continue
        nome_comarca = html.unescape(comarca.group(1)).strip(" -")
        # Municípios e distritos atendidos pela comarca além da sede (ex.: Ceres -> Carmo do Rio Verde)
        atendidos = []
        for linha in re.findall(r'<p class="municipio">(.*?)</p>', bloco, re.S):
            texto = html.unescape(re.sub(r"<[^>]+>", "", linha)).split(":", 1)[-1]
            atendidos += [n.strip(" .") for n in re.split(r",|\s+e\s+", texto) if n.strip(" .") and "$" not in n]
        for nome, cartao in re.findall(r"<h3>(.*?)</h3>(.*?)(?=<h3>|$)", bloco, re.S):
            atribuicao = re.search(r"Atribui[çc][ãa]o:\s*</strong>(.*?)</p>", cartao, re.S)
            promotorias.append({
                "nome": _capitalizar(html.unescape(re.sub(r"<[^>]+>", "", nome)).strip()),
                "comarca": nome_comarca,
                "municipios": atendidos,
                "atribuicao": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", atribuicao.group(1)))).strip()
                              if atribuicao else "",
            })
    return promotorias


CIDADES_POR_BUSCA_CAMARA = 4  # cada cidade rende quatro frases; mais que isso a busca fica longa


def buscas_camara(cidades, ambiguo):
    """Buscas de notícias das câmaras de vereadores das cidades (ambíguas só junto com "Goiás")."""
    def frases(c):
        if c == "Goiás":  # "Câmara de Goiás" pegaria a Assembleia e o estado inteiro
            return ['"Câmara Municipal da Cidade de Goiás"', '"vereadores da Cidade de Goiás"']
        return [f'"Câmara Municipal de {c}"', f'"Câmara de {c}"', f'"vereadores de {c}"', f'"vereador de {c}"']

    resultado = []
    for exige_goias in (False, True):
        grupo = [c for c in cidades if ambiguo(c) == exige_goias]
        for i in range(0, len(grupo), CIDADES_POR_BUSCA_CAMARA):
            termos = " OR ".join(f for c in grupo[i:i + CIDADES_POR_BUSCA_CAMARA] for f in frases(c))
            resultado.append(f"({termos}){' Goiás' if exige_goias else ''} when:10d")
    return resultado


# --- Radar: acontecimentos da comarca que podem pedir a atuação da promotoria ---
# Palavras de notícia (não de julgado) para cada matéria das atribuições, comparadas sem acento.
# Os nomes são os mesmos de informativos.MATERIAS, para casar com as matérias da promotoria.
RADAR = [
    ("Criminal", r"homicid|assassin|latrocin|baleado|esfaquead|morto a tiros|roubo|furto|assalt|"
                 r"trafic|drogas|entorpecente|\bpres[oa]s?\b|prisao|prende|flagrante|policia civil|policia militar|"
                 r"\bPM\b|operacao policial|deflagr|estupro|golpe|estelionat|faccao|arma de fogo|apreend|crime|criminos|suspeito|"
                 r"investigad|delegad|tiroteio|sequestr|extorsao|receptacao"),
    ("Tribunal do Júri", r"\bjuri\b|homicid|feminicid|tentativa de homicidio"),
    ("Execução penal", r"presidio|cadeia publica|unidade prisional|detentos?|reeducand|fuga de presos|tornozeleira|"
                       r"saidinha|regime semiaberto"),
    ("Violência doméstica", r"violencia domestica|maria da penha|feminicid|medida protetiva|contra a mulher|"
                            r"agressao a mulher|(agred|agrid|espanc|ameac|esfaque)\w* (a |sua )?(propria )?"
                            r"(mulher|companheira|esposa|namorada|ex)"),
    ("Infância e juventude", r"crianca|adolescente|menor de idade|bebe|conselho tutelar|ato infracional|"
                             r"estupro de vulneravel|abuso sexual|creche|abrigo|acolhimento institucional"),
    ("Família e sucessões", r"pensao alimenticia|guarda d[oa]s? filh|adocao|adota|heranca"),
    # "Prefeitura" sozinha fica de fora: quase toda notícia da cidade cita a prefeitura
    ("Patrimônio público", r"licitac|improbidade|desvio|superfatur|contrato emergencial|dispensa de licitacao|"
                           r"nepotismo|concurso publico|servidor(es)? public|funcionario fantasma|rachadinha|"
                           r"dinheiro publico|recursos publicos|tribunal de contas|\bTCM\b|irregularidade|"
                           r"prefeit[oa] (e |foi )?(afastad|cassad|investigad|denunciad|condenad|pres[oa])|"
                           r"vereador(es)? (e |foi |sao )?(afastad|cassad|investigad|denunciad|condenad|pres[oa])"),
    ("Tutela coletiva", r"acao civil publica|ajustamento de conduta|\bTAC\b"),
    ("Meio ambiente e urbanismo", r"desmat|queimada|incendio|poluic|poluid|contamina|lixao|esgoto|nascente|"
                                  r"mortandade|peixes mortos|loteamento|ambiental|ibama|semad|barragem|agrotoxic|"
                                  r"garimpo|mineracao|enchente|alagamento|erosao|patrimonio historico|obra irregular"),
    ("Consumidor", r"consumidor|procon|preco abusivo|combustivel adulterado|cobranca indevida|interdita"),
    ("Saúde", r"hospital|\bUPA\b|\bSUS\b|posto de saude|unidade de saude|medic[oa]s?\b|dengue|vacina|medicamento|"
              r"leitos?\b|\bUTI\b|surto|saude"),
    ("Educação", r"escola|educac|ensino|transporte escolar|merenda|professor|alunos?\b|estudantes?\b"),
    ("Idoso e pessoa com deficiência", r"idos[oa]|pessoa com deficiencia|\bPcD\b|acessibilidade|asilo|\bILPI\b|autis"),
    ("Eleitoral", r"eleitora|eleic[ao]|compra de votos|candidat"),
    ("Registros públicos", r"cartorio|registro civil"),
    ("Fundações", r"fundacao"),
    ("Controle externo da atividade policial", r"abuso de autoridade|morto pela policia|morte em (acao|confronto)|"
                                               r"confronto com a policia|policia(l|is) (pres|investigad|denunciad)"),
    ("Ordem tributária", r"sonegac|fraude fiscal|nota fiscal fria"),
    ("Cidadania", r"direitos humanos|situacao de rua|falta de agua|sem agua|abastecimento de agua|saneamento|transporte publico|"
                  r"moradia|despejo"),
]
RADAR = [(nome, re.compile(padrao, re.I)) for nome, padrao in RADAR]


def materias_da_noticia(noticia):
    """Matérias das atribuições a que a notícia da comarca pode dizer respeito (pelo título e resumo)."""
    texto = _sem_acento(f"{noticia['titulo']} {noticia.get('resumo', '')}")
    return [nome for nome, padrao in RADAR if padrao.search(texto)]


# --- Agendas das câmaras que publicam as sessões no SAPL (sistema do Interlegis) ---
# Só uma parte das câmaras de Goiás usa o SAPL; a lista guarda as que publicaram sessões
# em 2026 (cidade -> endereço sapl.<nome>.go.leg.br)
ARQUIVO_SAPL = Path(__file__).with_name("dados") / "camaras_sapl.json"
SESSOES_POR_CAMARA = 4


def agenda_sapl(nome_sapl, hoje):
    """Sessões da câmara a partir de três dias atrás: as próximas e as que acabaram de acontecer."""
    base = f"https://sapl.{nome_sapl}.go.leg.br"
    dados = _get(f"{base}/api/sessao/sessaoplenaria/",
                 params={"data_inicio__gte": (hoje - timedelta(days=3)).isoformat(),
                         "o": "data_inicio", "page_size": 20}).json()
    sessoes = sorted(dados["results"], key=lambda s: (s["data_inicio"], s.get("hora_inicio") or ""))
    # As próximas sessões primeiro; o que sobrar do espaço fica com as últimas realizadas
    proximas = [s for s in sessoes if s["data_inicio"] >= hoje.isoformat()][:SESSOES_POR_CAMARA]
    passadas = [s for s in sessoes if s["data_inicio"] < hoje.isoformat()]
    passadas = passadas[len(passadas) - (SESSOES_POR_CAMARA - len(proximas)):] if len(proximas) < SESSOES_POR_CAMARA else []
    dados = {"results": passadas + proximas}
    return {
        "link": f"{base}/sessao/pesquisar-sessao",
        "sessoes": [{
            "data": s["data_inicio"],
            "hora": s.get("hora_inicio") or "",
            "titulo": re.sub(r" da \d+ª Sessão Legislativa.*", "", s["__str__"]),
            "link": f"{base}/sessao/{s['id']}",
            "pauta": s.get("upload_pauta") or None,
            "finalizada": bool(s.get("finalizada")),
        } for s in dados["results"]],
    }


def agendas_camaras(mapa):
    """{cidade: agenda ou None} das câmaras com SAPL que estão em alguma comarca."""
    cidades = {c for local in mapa["locais"].values() if local["tipo"] == "camara" for c in local["municipios"]}
    return agendas_das_cidades(cidades)


def agendas_das_cidades(cidades):
    from concurrent.futures import ThreadPoolExecutor
    sapl = json.loads(ARQUIVO_SAPL.read_text(encoding="utf-8"))
    hoje = datetime.now(timezone(timedelta(hours=-3))).date()

    def uma(cidade):
        try:
            return cidade, agenda_sapl(sapl[cidade], hoje)
        except Exception as erro:
            print(f"[regional] Sem agenda da Câmara de {cidade}: {erro}")
            return cidade, None

    with ThreadPoolExecutor(8) as executor:
        return dict(executor.map(uma, [c for c in sapl if c in cidades]))


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

    def buscas(cidades):
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
        # Os outros municípios atendidos pela comarca (os distritos ficam de fora: nomes como
        # "Caiçara" ou "São João" trariam notícias de qualquer lugar)
        atendidos = []
        for nome in next(p for p in promotorias if p["comarca"] == comarca).get("municipios", []):
            m = municipios.get(_sem_acento(nome))
            if m and m["municipio-nome"] != cidade and m["municipio-nome"] not in atendidos:
                atendidos.append(m["municipio-nome"])
        todas = [cidade, *atendidos]
        locais[id_cidade] = {
            "nome": f"Comarca de {cidade}" if atendidos else cidade,
            "tipo": "cidade",
            "municipios": todas,
            "buscas": busca_cidade + buscas(atendidos),
        }

        # Câmaras de vereadores de todos os municípios da comarca
        id_camara = "camara-" + _slug(cidade)
        locais[id_camara] = {
            "nome": "Câmaras Municipais" if atendidos else f"Câmara Municipal de {cidade}",
            "tipo": "camara",
            "municipios": todas,
            "buscas": buscas_camara(todas, ambiguo),
        }

        regiao = municipio["regiao-imediata-nome"]
        id_regiao = "regiao-" + _slug(regiao)
        if id_regiao not in locais:
            vizinhas = sorted(m["municipio-nome"] for m in goias
                              if m["regiao-imediata-nome"] == regiao and m["municipio-nome"] != "Goiás"
                              and m["municipio-nome"] not in FORA_DAS_REGIOES)
            locais[id_regiao] = {"nome": f"Região de {regiao}", "tipo": "regiao", "buscas": buscas(vizinhas)}
        comarcas[comarca] = {"cidade": id_cidade, "regiao": id_regiao, "camara": id_camara}

    return {
        "promotorias": [p for p in promotorias if p["comarca"] in comarcas],
        "comarcas": comarcas,
        "locais": locais,
    }


# --- Notícias de cada local ---

def noticias_do_local(local):
    """As 20 principais notícias recentes de uma cidade ou região (a página mostra cinco de início)."""
    limite = (datetime.now(timezone.utc) - JANELA).isoformat()
    itens, vistos = [], set()
    for busca in local["buscas"]:
        for noticia in coletor.buscar_google_noticias(busca):
            if noticia["data"] >= limite and noticia["link"] not in vistos:
                vistos.add(noticia["link"])
                itens.append(noticia)
        time.sleep(PAUSA_ENTRE_BUSCAS)
    itens.sort(key=lambda n: n["data"], reverse=True)
    return coletor.escolher_juridicas(itens, coletor.POR_EDITORIA)


def atualizar_estado(mapa, estado, orcamento=BUSCAS_POR_EXECUCAO):
    """Atualiza os locais nunca coletados (ou cujos municípios mudaram) e depois os mais antigos,
    até gastar o orçamento de buscas."""
    def prioridade(id_):
        antigo = estado.get(id_, {})
        return antigo.get("municipios") == mapa["locais"][id_].get("municipios"), antigo.get("atualizado", "")
    fila = sorted(mapa["locais"], key=prioridade)
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
            **({"municipios": local["municipios"]} if "municipios" in local else {}),
            "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "noticias": noticias,
        }
        gastas += len(local["buscas"])
    return gastas


def estado_publicado():
    """O estado da última publicação (lido do próprio site), para continuar de onde parou."""
    # O endereço antigo vale para a primeira publicação no novo, que ainda não tem o estado
    for site in (SITE_PUBLICADO, SITE_ANTIGO):
        try:
            return _get(f"{site}/regional/estado.json").json()
        except Exception as erro:
            print(f"[regional] Sem estado anterior em {site} ({erro})")
    print("[regional] Começa do zero")
    return {}


def dados_promotorias(mapa):
    """O que o seletor da página precisa: promotorias, comarca de cada uma e nome de cada local."""
    return {
        "promotorias": [{**p, **informativos.materias_da_atribuicao(p["atribuicao"])} for p in mapa["promotorias"]],
        "comarcas": mapa["comarcas"],
        "nomes": {id_: local["nome"] for id_, local in mapa["locais"].items()},
    }


def arquivo_do_local(local, dados, agendas):
    """O que a página recebe de um local: as notícias guardadas mais o radar e as agendas."""
    if local["tipo"] == "cidade" and dados:
        # O radar da página filtra estas notícias pelas matérias da promotoria escolhida
        dados = {**dados, "noticias": [{**n, "materias": materias_da_noticia(n)} for n in dados["noticias"]]}
    if local["tipo"] == "camara":
        dados = {"nome": local["nome"], "tipo": "camara", "municipios": local["municipios"],
                 **(dados or {"noticias": None}),
                 "agendas": {c: agendas.get(c) for c in local["municipios"] if c in agendas}}
    return dados


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
    agendas = agendas_camaras(mapa)
    print(f"[regional] Agendas de {sum(a is not None for a in agendas.values())} de {len(agendas)} câmaras com SAPL")
    for id_, local in mapa["locais"].items():
        dados = arquivo_do_local(local, estado.get(id_), agendas)
        if dados:
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
