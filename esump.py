"""Próximos cursos e eventos da Escola Superior do MPGO (ESUMP), para o quadro do MPGO.

A página "ESUMP – Cursos e Eventos" do portal do MPGO publica cada evento como uma notícia, com a
data de publicação, o título e o texto. A data do evento vem no texto ("será realizado no dia
19 de novembro de 2026", "nos dias 30 de novembro e 1º de dezembro de 2026") ou no título
("(19/11/2026)").
"""

import html
import re
from datetime import date, datetime, timedelta, timezone

import requests

from informativos import MESES

TIMEOUT = 30
MPGO = "https://www.mpgo.mp.br"
PAGINA = MPGO + "/portal/cursos_eventos"
PAGINAS = 2  # 14 eventos por página
QUANTIDADE = 8
DIAS_SEM_DATA = 21  # evento sem data reconhecida aparece enquanto a notícia for recente
FUSO_BRASILIA = timezone(timedelta(hours=-3))
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_MES = "|".join(MESES)
# "dia 19 de novembro de 2026", "dias 30 de novembro e 1º de dezembro de 2026", "dias 10 e 11 de novembro"
_DATA_TEXTO = re.compile(rf"\bdias?\s+(\d{{1,2}})º?(?:\s+de\s+({_MES}))?(?:\s*(?:,|e|a)\s*\d{{1,2}}º?)*"
                         rf"(?:\s+de\s+({_MES}))?(?:\s+de\s+(\d{{4}}))?", re.I)
_DATA_TITULO = re.compile(r"\((\d{1,2})/(\d{1,2})(?:/(\d{4}))?\)")


def _texto(trecho):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", trecho))).strip()


def data_do_evento(titulo, texto, publicado):
    """Primeiro dia do evento (date) ou None."""
    achada = _DATA_TITULO.search(titulo)
    if achada:
        dia, mes, ano = achada.groups()
        return date(int(ano or publicado.year), int(mes), int(dia))
    # No título, a data vale mais que no texto ("... é adiado para 19 de novembro")
    no_titulo = re.search(rf"\b(\d{{1,2}})º?\s+de\s+({_MES})\b(?:\s+de\s+(\d{{4}}))?", titulo, re.I)
    if no_titulo:
        ano = int(no_titulo.group(3) or publicado.year)
        return date(ano, MESES.index(no_titulo.group(2).lower()) + 1, int(no_titulo.group(1)))
    for achada in _DATA_TEXTO.finditer(texto):
        dia, mes1, mes2, ano = achada.groups()
        mes = mes1 or mes2
        if not mes:
            continue
        ano = int(ano) if ano else publicado.year
        try:
            data = date(ano, MESES.index(mes.lower()) + 1, int(dia))
        except ValueError:
            continue
        if not achada.group(4) and data < publicado - timedelta(days=7):  # "dia 5 de janeiro" publicado em dezembro
            data = data.replace(year=ano + 1)
        return data
    return None


def _pagina(numero):
    resp = requests.get(PAGINA, params={"page": numero} if numero > 1 else None, timeout=TIMEOUT, headers=CABECALHOS)
    resp.raise_for_status()
    eventos = []
    for bloco in resp.text.split('class="box title-section hover-shadow block"')[1:]:
        link = re.search(r'href="([^"]+)"', bloco)
        titulo = re.search(r"<h2[^>]*>(.*?)</h2>", bloco, re.S)
        publicado = re.search(r"ico-calendar\"></b>\s*(\d{2}/\d{2}/\d{4})", bloco)
        if not (link and titulo and publicado):
            continue
        titulo = _texto(titulo.group(1))
        corpo = re.search(r"<p[^>]*>(.*?)</p>", bloco, re.S)
        texto = _texto(corpo.group(1)) if corpo else ""
        publicado = datetime.strptime(publicado.group(1), "%d/%m/%Y").date()
        quando = data_do_evento(titulo, texto, publicado)
        eventos.append({
            "titulo": titulo,
            "link": MPGO + link.group(1) if link.group(1).startswith("/") else link.group(1),
            "publicado": publicado.isoformat(),
            "data": quando.isoformat() if quando else None,
            "inscricoes": bool(re.search(r"inscri[çc][õo]es (est[ãa]o )?abertas|abre inscri|abertas as inscri",
                                         f"{titulo} {texto}", re.I)),
        })
    return eventos


def coletar():
    """Os próximos eventos, do mais próximo para o mais distante (os sem data no fim)."""
    hoje = datetime.now(FUSO_BRASILIA).date()
    eventos, vistos = [], set()
    for numero in range(1, PAGINAS + 1):
        for e in _pagina(numero):
            if e["link"] in vistos:
                continue
            vistos.add(e["link"])
            futuro = e["data"] and e["data"] >= hoje.isoformat()
            recente_sem_data = not e["data"] and e["publicado"] >= (hoje - timedelta(days=DIAS_SEM_DATA)).isoformat()
            if futuro or recente_sem_data:
                eventos.append(e)
    eventos.sort(key=lambda e: (e["data"] is None, e["data"] or "", not e["inscricoes"], e["titulo"]))
    # Duas notícias do mesmo evento (a da abertura das inscrições e a das vagas custeadas, por
    # exemplo): mesma data e título parecido; fica a primeira
    unicos = []
    for e in eventos:
        palavras = _palavras(e["titulo"])
        if not any(o["data"] == e["data"] and len(palavras & _palavras(o["titulo"])) >= 3 for o in unicos):
            unicos.append(e)
    return {"eventos": unicos[:QUANTIDADE], "pagina": PAGINA}


def _palavras(titulo):
    return {p for p in re.findall(r"\w+", titulo.lower()) if len(p) > 5}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for e in coletar()["eventos"]:
        print(e["data"], "inscrições" if e["inscricoes"] else "", e["titulo"])
