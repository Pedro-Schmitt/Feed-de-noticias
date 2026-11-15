"""Entendimentos do CNMP e do CNJ (atos normativos) e novidades legislativas federais e de Goiás,
cada um com as matérias de atuação do MP a que diz respeito (as mesmas dos informativos).

- CNMP: a página "Atos e Normas" lista os atos mais recentes; ficam as resoluções, recomendações,
  enunciados, súmulas, assentos e emendas regimentais (as portarias e os acordos, não).
- CNJ: a pesquisa de atos (atos.cnj.jus.br) por tipo: resoluções, recomendações, enunciados
  administrativos e provimentos da Corregedoria Nacional.
- Leis federais: dados abertos do Senado (lista de legislação por tipo e ano), com o link do texto
  no Planalto.
- Leis de Goiás: API do Legisla, da Casa Civil do Estado.
"""

import html
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests

from informativos import MESES, materias_do_texto

TIMEOUT = 30
NAVEGADOR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
FUSO_BRASILIA = timezone(timedelta(hours=-3))
POR_CONSELHO = 12
DIAS_LEGISLACAO = 60  # leis publicadas nesse período
POR_ESFERA = 25

CNMP = "https://www.cnmp.mp.br"
CNMP_LISTA = CNMP + "/portal/atos-e-normas?filter_order=a.data_publicacao&filter_order_Dir=desc&start={inicio}"
CNMP_PAGINAS = 5  # 20 atos por página, a maioria portarias
CNMP_TIPOS = re.compile(r"^(RESOLU[ÇC][ÃA]O|RECOMENDA[ÇC][ÃA]O|ENUNCIADO|S[ÚU]MULA|ASSENTO|EMENDA REGIMENTAL)", re.I)

CNJ = "https://atos.cnj.jus.br/"
# Resolução, Recomendação, Enunciado Administrativo, Provimento, Resolução Conjunta, Recomendação Conjunta
CNJ_TIPOS = [7, 13, 10, 20, 19, 26]
CNJ_PAGINAS = 2  # 10 atos por página

SENADO = "https://legis.senado.leg.br/dadosabertos/legislacao/lista"
SENADO_TIPOS = {"LEI": "Lei", "LCP": "Lei Complementar", "EMC": "Emenda Constitucional"}
LEGISLA = "https://legisla.casacivil.go.gov.br/api/v2/pesquisa/legislacoes"
LEGISLA_LINK = "https://legisla.casacivil.go.gov.br/pesquisa_legislacao/{id}"
LEGISLA_TIPOS = {2: 3, 1: 1, 13: 1}  # Lei Ordinária, Lei Complementar, Emenda Constitucional → páginas de 40

# Leis que não mudam a atuação do Promotor: homenagens, datas comemorativas, créditos orçamentários
RUIDO = re.compile(
    r"t[íi]tulo de cidad|utilidade p[úu]blica|denomina|calend[áa]rio|^\s*(institui|inclui|cria) (o|a) (dia|m[êe]s|semana|"
    r"festival|circuito)|^\s*institui os meses|cr[ée]dito (especial|suplementar|extraordin)|or[çc]ament[áa]ria|"
    r"capital (goiana|nacional|estadual)|honor[íi]fic|^\s*confere ao munic|doa[çc][ãa]o|denomin|"
    r"reconhecimento d[oa]s? (bem|bens)|patrim[ôo]nio (cultural )?imaterial|bens imateriais|^\s*reconhece a ra[çc]a", re.I)
PENAL = re.compile(r"C[óo]digo Penal|Processo Penal|Execu[çc][ãa]o Penal|\bpenas?\b|\bpris[ãa]o\b", re.I)


def _get(url, **kwargs):
    resp = requests.get(url, timeout=TIMEOUT, headers=NAVEGADOR, **kwargs)
    resp.raise_for_status()
    return resp


def _texto(trecho):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", trecho))).strip()


def _materias(texto):
    materias = materias_do_texto(texto)
    if PENAL.search(texto) and "Criminal" not in materias:
        materias.insert(0, "Criminal")
    return materias


def _data_por_extenso(texto):
    """"27 DE OUTUBRO DE 2026" → "2026-10-27" (None se não houver data)."""
    achada = re.search(r"(\d{1,2})[º°o]?\s+de\s+([a-zç]+)\s+de\s+(\d{4})", texto, re.I)
    if not achada or achada.group(2).lower() not in MESES:
        return None
    return date(int(achada.group(3)), MESES.index(achada.group(2).lower()) + 1, int(achada.group(1))).isoformat()


def _data_br(texto):
    """"12/11/2026" → "2026-11-12"."""
    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _tipo_legivel(tipo):
    """"RESOLUÇÃO CONJUNTA PRESI-CN" → "Resolução Conjunta PRESI-CN"."""
    return " ".join(p if "-" in p or p in {"CNMP", "CN"} else p.capitalize() for p in tipo.split())


# --- CNMP ---

def _cnmp_pagina(inicio):
    pagina = _get(CNMP_LISTA.format(inicio=inicio)).text
    atos = []
    for bloco in pagina.split('<h3 class="result-title')[1:]:
        link = re.search(r'href="([^"]+)"', bloco)
        titulo = _texto(re.search(r"<a[^>]*>(.*?)</a>", bloco, re.S).group(1)) if link else ""
        if not link or not CNMP_TIPOS.match(titulo):
            continue
        descricao = re.search(r'class="result-text">(.*?)</p>', bloco, re.S)
        partes = re.match(r"(.+?)\s+N[º°o.]*\s*(\d+)", titulo, re.I)
        nome = f"{_tipo_legivel(partes.group(1))} nº {partes.group(2)}" if partes else titulo.rstrip(".")
        ementa = _texto(descricao.group(1)) if descricao else ""
        atos.append({
            "titulo": nome,
            "data": _data_por_extenso(titulo),
            "ementa": ementa,
            "link": CNMP + link.group(1) if link.group(1).startswith("/") else link.group(1),
            "materias": _materias(ementa),
        })
    return atos


def cnmp():
    with ThreadPoolExecutor(max_workers=CNMP_PAGINAS) as executor:
        paginas = list(executor.map(_cnmp_pagina, [20 * i for i in range(CNMP_PAGINAS)]))
    atos = list({a["link"]: a for pagina in paginas for a in pagina}.values())
    atos.sort(key=lambda a: a["data"] or "", reverse=True)
    return atos[:POR_CONSELHO]


# --- CNJ ---

def _cnj_pagina(numero):
    params = [("atos", "sim")] + [("tipoAto[]", t) for t in CNJ_TIPOS] + [
        ("numero", ""), ("ano", ""), ("argumento", ""), ("origem", ""), ("situacao", ""), ("page", numero)]
    pagina = _get(CNJ + "atos", params=params).text
    corpo = pagina[pagina.find("<tbody>"):pagina.find("</tbody>")]
    atos = []
    for linha in re.findall(r"<tr>(.*?)</tr>", corpo, re.S):
        celulas = [_texto(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)]
        link = re.search(r'href="([^"]+)"', linha)
        if len(celulas) < 6 or not link:
            continue
        tipo, numero_ato, data, origem, situacao, ementa = celulas[:6]
        atos.append({
            "titulo": f"{tipo} nº {numero_ato}" + (" (Corregedoria)" if origem == "Corregedoria" else ""),
            "data": _data_br(data),
            "ementa": ementa,
            "situacao": situacao,
            "link": CNJ + link.group(1).lstrip("/"),
            "materias": _materias(ementa),
        })
    return atos


def cnj():
    with ThreadPoolExecutor(max_workers=CNJ_PAGINAS) as executor:
        paginas = list(executor.map(_cnj_pagina, range(1, CNJ_PAGINAS + 1)))
    atos = list({a["link"]: a for pagina in paginas for a in pagina}.values())
    atos.sort(key=lambda a: a["data"] or "", reverse=True)
    return atos[:POR_CONSELHO]


# --- Legislação ---

def _planalto(tipo, numero, ano):
    if tipo == "LCP":
        return f"https://www.planalto.gov.br/ccivil_03/leis/lcp/Lcp{numero}.htm"
    if tipo == "EMC":
        return f"https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc{numero}.htm"
    inicio = 2023 + 4 * ((ano - 2023) // 4)  # as pastas do Planalto vão por mandato: _ato2023-2026
    return f"https://www.planalto.gov.br/ccivil_03/_ato{inicio}-{inicio + 3}/{ano}/lei/L{numero}.htm"


def _lei(esfera, titulo, data, ementa, link):
    return {"esfera": esfera, "titulo": titulo, "data": data, "ementa": ementa, "link": link,
            "materias": _materias(ementa)}


def _federais(tipo, ano):
    raiz = ET.fromstring(_get(SENADO, params={"tipo": tipo, "ano": ano}).content)
    leis = []
    for doc in raiz.iter("documento"):
        numero = (doc.findtext("numero") or "").strip()
        data = _data_br(doc.findtext("dataassinatura") or "")
        if not numero or not data:
            continue
        numero_fmt = f"{int(numero):,}".replace(",", ".") if tipo == "LEI" else numero
        leis.append(_lei("federal", f"{SENADO_TIPOS[tipo]} nº {numero_fmt}", data,
                         (doc.findtext("ementa") or "").strip(), _planalto(tipo, numero, int(data[:4]))))
    return leis


def _estaduais(tipo, paginas):
    leis = []
    for pagina in range(1, paginas + 1):
        dados = _get(LEGISLA, params={"page": pagina, "qtd_por_pagina": 40, "tipo_legislacao": tipo}).json()
        for r in dados["resultados"]:
            data = _data_br(r.get("data_legislacao") or "")
            if not data:
                continue
            leis.append(_lei("estadual", f"{r['tipo_legislacao']['nome']} nº {r['numero']}", data,
                             (r.get("ementa") or "").strip(), LEGISLA_LINK.format(id=r["id"])))
    return leis


def legislacao():
    hoje = datetime.now(FUSO_BRASILIA).date()
    limite = (hoje - timedelta(days=DIAS_LEGISLACAO)).isoformat()
    anos = sorted({hoje.year, (hoje - timedelta(days=DIAS_LEGISLACAO)).year})
    with ThreadPoolExecutor(max_workers=8) as executor:
        federais = [executor.submit(_federais, tipo, ano) for tipo in SENADO_TIPOS for ano in anos]
        estaduais = [executor.submit(_estaduais, tipo, paginas) for tipo, paginas in LEGISLA_TIPOS.items()]
    saida = {}
    for esfera, futuros in (("federal", federais), ("estadual", estaduais)):
        leis = []
        for futuro in futuros:
            try:
                leis.extend(futuro.result())
            except Exception as erro:  # um tipo com falha não derruba os outros
                print(f"[normas] Falha na legislação {esfera}: {erro}")
        if not leis and futuros:
            saida[esfera] = None
            continue
        leis = [lei for lei in leis if lei["data"] >= limite and not RUIDO.search(lei["ementa"])]
        leis.sort(key=lambda lei: (lei["data"], lei["titulo"]), reverse=True)
        saida[esfera] = leis[:POR_ESFERA]
    saida["dias"] = DIAS_LEGISLACAO
    return saida


def _ou_none(funcao, nome):
    try:
        return funcao()
    except Exception as erro:  # sem essa parte, o resto do site continua
        print(f"[normas] Falha em {nome}: {erro}")
        return None


def coletar():
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_cnmp = executor.submit(_ou_none, cnmp, "CNMP")
        f_cnj = executor.submit(_ou_none, cnj, "CNJ")
        f_leis = executor.submit(_ou_none, legislacao, "legislação")
    return {"conselhos": {"cnmp": f_cnmp.result(), "cnj": f_cnj.result()}, "legislacao": f_leis.result()}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    dados = coletar()
    for nome, atos in dados["conselhos"].items():
        print(f"\n== {nome}: {len(atos or [])}")
        for a in atos or []:
            print(f"  {a['data']} {a['titulo']} {a['materias']} | {a['ementa'][:90]}")
    for esfera in ("federal", "estadual"):
        leis = (dados["legislacao"] or {}).get(esfera) or []
        print(f"\n== {esfera}: {len(leis)}")
        for lei in leis:
            print(f"  {lei['data']} {lei['titulo']} {lei['materias']} | {lei['ementa'][:90]}")
