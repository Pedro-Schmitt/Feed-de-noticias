"""Diário Oficial do MPGO (DOMP): a edição mais recente, com um breve resumo do que ela trata.

A página do DOMP no portal do MPGO lista as edições (data e número); cada edição é um PDF com um
índice por seção (Procuradoria-Geral, Subprocuradoria, Colégio de Procuradores, CSMP, Procuradorias,
Promotorias, Licitações). Cada documento começa numa página nova, com o órgão e os "Autos n.".

Com a variável ANTHROPIC_API_KEY, o Claude lê o começo de cada documento e escreve o resumo e os
destaques para o promotor; sem ela, o resumo é feito pelas contagens de cada seção e pelos atos
normativos da edição. Cada edição é lida uma vez só: a execução seguinte reaproveita o resumo já
publicado no site, enquanto a edição for a mesma.
"""

import io
import json
import re
from datetime import date

import requests

from informativos import MESES

TIMEOUT = 60
MPGO = "https://www.mpgo.mp.br"
PAGINA = MPGO + "/portal/domp"
MODELO = "claude-opus-5-5"
DESTAQUES = 6
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
# Quanto do começo de cada documento vai para o Claude, por seção (as das promotorias e licitações
# são quase todas de rotina: editais de cientificação, portarias de instauração, extratos)
TRECHO = {"06": 260, "07": 200}
TRECHO_PADRAO = 900
_EDICAO = re.compile(r"<td>\s*(\d{1,2}) de (\w+) de (\d{4})\s*</td>\s*<td>\s*<a href=\"(/portal/domp/edicao/(\d+))\"", re.S)
_NORMATIVO = re.compile(r"^(ATO CONJUNTO|ATO PGJ|ATO|RESOLUÇÃO|RECOMENDAÇÃO|INSTRUÇÃO NORMATIVA|PROVIMENTO)\b.*\bN[.ºo°]", re.I)

SISTEMA = """Você resume o Diário Oficial do Ministério Público de Goiás (DOMP) para Promotores de Justiça \
que têm poucos minutos por dia. Recebe o começo de cada documento da edição, por seção.

Escreva:
- resumo: duas ou três frases dizendo o que a edição traz de mais relevante para um membro do MP \
(atos normativos novos, decisões do Conselho Superior e do Colégio de Procuradores, promoções, remoções, \
designações e substituições, editais de concurso, de promoção ou de remoção, convocações). Depois, em \
poucas palavras, o volume do que é rotina (por exemplo: "e 120 publicações de promotorias, a maioria \
editais de cientificação de arquivamento").
- destaques: até seis itens, os mais importantes primeiro. titulo curto (ex.: "Ato Conjunto PGJ-CGMP n. 1/2026"; \
"Coordenação das Promotorias de Inhumas"); texto em uma ou duas frases, objetivo, com nomes, números e \
datas que estejam no documento. Atos de rotina das promotorias (instauração, arquivamento, cientificação) \
e extratos de contrato só entram se forem incomuns.
Use só o que está nos documentos; não invente nem deduza."""


def _esquema():
    item = {
        "type": "object",
        "properties": {"secao": {"type": "string"}, "titulo": {"type": "string"}, "texto": {"type": "string"}},
        "required": ["secao", "titulo", "texto"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"resumo": {"type": "string"}, "destaques": {"type": "array", "items": item}},
        "required": ["resumo", "destaques"],
        "additionalProperties": False,
    }


def ultima_edicao():
    """{"numero", "data" (aaaa-mm-dd), "link"} da edição mais recente."""
    resp = requests.get(PAGINA, timeout=TIMEOUT, headers=CABECALHOS)
    resp.raise_for_status()
    edicoes = []
    for dia, mes, ano, caminho, numero in _EDICAO.findall(resp.text):
        if mes.lower() not in MESES:
            continue
        data = date(int(ano), MESES.index(mes.lower()) + 1, int(dia))
        edicoes.append({"numero": int(numero), "data": data.isoformat(), "link": MPGO + caminho})
    if not edicoes:
        raise RuntimeError("nenhuma edição na página do DOMP")
    return max(edicoes, key=lambda e: e["numero"])


def _limpar(texto):
    return re.sub(r"\s+", " ", texto).strip()


def documentos(conteudo_pdf):
    """[{"secao": "01 - Procuradoria-Geral de Justiça", "texto"}] na ordem da edição.
    Um documento começa na página que traz "Autos" nas primeiras linhas; as outras o continuam."""
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(conteudo_pdf))
    secoes = sorted(((leitor.get_destination_page_number(o), o.title) for o in leitor.outline if hasattr(o, "title")))
    docs = []
    for i, pagina in enumerate(leitor.pages):
        texto = pagina.extract_text() or ""
        if i == 0:  # a capa repete o cabeçalho do DOMP antes do primeiro documento
            texto = texto.split("PROCURADORIA-GERAL DE JUSTIÇA", 1)[-1]
        secao = next((titulo for inicio, titulo in reversed(secoes) if inicio <= i), "")
        linhas = [l.strip() for l in texto.split("\n") if l.strip()]
        novo = not docs or docs[-1]["secao"] != secao or any(l.startswith("Autos") for l in linhas[:5])
        if novo:
            docs.append({"secao": secao, "texto": ""})
        docs[-1]["texto"] += " " + _limpar(texto)
    for d in docs:
        d["texto"] = d["texto"].strip()
    return [d for d in docs if d["texto"]]


def _contagens(docs):
    contagem = {}
    for d in docs:
        contagem[d["secao"]] = contagem.get(d["secao"], 0) + 1
    return [{"nome": re.sub(r"^\d+\s*-\s*", "", nome), "documentos": n} for nome, n in contagem.items()]


def _titulo_ato(texto):
    """"ATO PGJ N. 10 2 , DE 1 3 DE NOVEMBRO DE 2026" → "Ato PGJ n. 102, de 13 de novembro de 2026"."""
    texto = re.sub(r"(?<=\d) (?=\d)", "", texto).replace(" ,", ",")
    palavras = []
    for p in texto.split():
        if p.isupper() and len(p) <= 4 and p.isalpha() and p not in ("ATO", "DE", "DA", "DO", "N."):
            palavras.append(p)  # siglas: PGJ, CGMP, CSMP
        elif "-" in p and p.replace("-", "").isupper():
            palavras.append(p)  # PGJ-CGMP
        else:
            palavras.append(p.lower())
    texto = " ".join(palavras).replace("ato conjunto", "Ato Conjunto").replace("instrução normativa", "Instrução Normativa")
    return texto[:1].upper() + texto[1:]


def _sem_ia(docs, contagens):
    """Resumo pelas contagens e pelos atos normativos (título e ementa)."""
    destaques = []
    for d in docs:
        if d["secao"][:2] in ("06", "07"):
            continue
        achado = re.search(r"((?:ATO CONJUNTO|ATO PGJ|ATO|RESOLUÇÃO|RECOMENDAÇÃO|INSTRUÇÃO NORMATIVA|PROVIMENTO)[^a-z]{0,80}?"
                           r"N[.ºo°]\s*\d+[^a-z]{0,60}?\d{4})\s+(.{20,400}?)\s+(?:O |A |Os |As )?(?:PROCURADOR|CONSELHO|COLÉGIO|CORREGEDOR|SUBPROCURADOR)",
                           d["texto"])
        if achado:
            destaques.append({"secao": re.sub(r"^\d+\s*-\s*", "", d["secao"]),
                              "titulo": _titulo_ato(achado.group(1)),
                              "texto": achado.group(2)})
    total = sum(c["documentos"] for c in contagens)
    por_secao = "; ".join(f"{c['nome']}: {c['documentos']}" for c in contagens)
    resumo = f"{total} publicações ({por_secao})."
    return resumo, destaques[:DESTAQUES]


def _com_ia(docs, edicao):
    import anthropic

    blocos, secao = [], None
    for d in docs:
        if d["secao"] != secao:
            secao = d["secao"]
            blocos.append(f"\n## {secao}")
        limite = TRECHO.get(secao[:2], TRECHO_PADRAO)
        blocos.append(f"- {d['texto'][:limite]}")
    pedido = f"Edição {edicao['numero']} do DOMP, de {edicao['data']}.\n" + "\n".join(blocos)
    resposta = anthropic.Anthropic().beta.messages.create(
        model=MODELO,
        max_tokens=8000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _esquema()}},
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
    )
    if resposta.stop_reason != "end_turn":
        raise RuntimeError(f"resposta incompleta do Claude ({resposta.stop_reason})")
    dados = json.loads(next(b.text for b in resposta.content if b.type == "text"))
    destaques = [{**d, "secao": re.sub(r"^\d+\s*-\s*", "", d["secao"])} for d in dados["destaques"][:DESTAQUES]]
    return dados["resumo"], destaques


def publicado():
    """O DOMP que o site publicado já mostra (para não ler de novo a mesma edição), ou None."""
    import os

    site = os.environ.get("SITE_PUBLICADO", "https://revista-do-promotor.web.app")
    try:
        return requests.get(f"{site}/api/noticias", timeout=30).json().get("domp")
    except Exception:
        return None


def coletar(anterior=None):
    """A edição mais recente com resumo, destaques e o número de publicações por seção.
    `anterior` é o que o site publicado já tem (por padrão, lido dele): se for a mesma edição,
    é reaproveitado."""
    import os

    edicao = ultima_edicao()
    anterior = anterior if anterior is not None else publicado()
    com_ia = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if anterior and anterior.get("numero") == edicao["numero"] and (anterior.get("ia") or not com_ia):
        return anterior
    resp = requests.get(edicao["link"], timeout=120, headers=CABECALHOS)
    resp.raise_for_status()
    docs = documentos(resp.content)
    contagens = _contagens(docs)
    resumo, destaques, ia = None, None, False
    if com_ia:
        try:
            resumo, destaques = _com_ia(docs, edicao)
            ia = True
        except Exception as erro:  # sem o Claude, fica o resumo pelas contagens
            print(f"[domp] Falha no resumo pelo Claude: {erro}")
    if not ia:
        resumo, destaques = _sem_ia(docs, contagens)
    return {**edicao, "pagina": PAGINA, "secoes": contagens, "resumo": resumo, "destaques": destaques, "ia": ia}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(coletar(), ensure_ascii=False, indent=1))
