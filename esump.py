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
# "no dia 18/11/2026", "nos dias 25 e 26/11"
_DATA_NUMERICA = re.compile(r"\bdias?\s+(\d{1,2})(?:\s*(?:,|e|a)\s*\d{1,2})*/(\d{1,2})(?:/(\d{4}))?")
DIAS_BUSCA_PAGINA = 45  # evento sem data na lista: a data é procurada na página da notícia


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
    # No texto, vale a primeira data ("no dia 18/11/2026", "nos dias 30 de novembro e 1º de dezembro"),
    # menos os prazos ("inscrições até o dia 25/11/2026")
    candidatas = []
    for achada in _DATA_NUMERICA.finditer(texto):
        dia, mes, ano = achada.groups()
        try:
            candidatas.append((achada.start(), date(int(ano or publicado.year), int(mes), int(dia))))
        except ValueError:
            continue
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
        candidatas.append((achada.start(), data))
    candidatas = [(pos, data) for pos, data in candidatas if not re.search(r"\baté\s+(?:o\s+)?$", texto[max(0, pos - 10):pos], re.I)]
    return min(candidatas)[1] if candidatas else None


def _pagina_da_noticia(link):
    """(html do corpo, texto do corpo) da página da notícia, ou ("", "")."""
    try:
        resp = requests.get(link, timeout=TIMEOUT, headers=CABECALHOS)
        resp.raise_for_status()
    except requests.RequestException:
        return "", ""
    pagina = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", resp.text, flags=re.S | re.I)
    texto = _texto(pagina)
    inicio = texto.find("Visualizações")  # o corpo vem depois da data e das visualizações
    fim = texto.find("Contatos da Esump", inicio)
    corpo = texto[inicio:fim if fim > inicio else inicio + 6000] if inicio >= 0 else ""
    return pagina, corpo


# Ficha no fim das notícias de evento: "CURSO PRESENCIAL TEMA: ... DATA: ... HORÁRIO: ... LOCAL: ..."
_ROTULOS = r"TEMA|DATA|HOR[ÁA]RIO|LOCAL|P[ÚU]BLICO-ALVO|PROGRAMA[ÇC][ÃA]O|INSCRI[ÇC][ÃÕ]O?E?S?|FACILITADORA?\(?E?S?\)?|EXPOSITOR[A-Z()]*|PALESTRANTE[A-Z()]*|CARGA HOR[ÁA]RIA|MODALIDADE|VAGAS"
_TIPO_FICHA = re.compile(r"\b((?:CURSO|SEMIN[ÁA]RIO|OFICINA|WEBINAR|PALESTRA|WORKSHOP|CONGRESSO|ENCONTRO|F[ÓO]RUM|DI[ÁA]LOGOS?|RODA DE CONVERSA|CAPACITA[ÇC][ÃA]O|EVENTO)"
                         r"(?:\s+(?:PRESENCIAL|ON-?LINE|H[ÍI]BRID[OA]|EAD|INSTITUCIONA(?:L|IS)))?)\s+TEMA\s*:")
_HORA = re.compile(r"\b(?:das|às|a partir das)\s+(\d{1,2}h(?:\d{2})?|\d{1,2}(?=\s+(?:às|a)\s+\d{1,2}\s*h))"
                   r"(?:\s*(?:às|a)\s+(\d{1,2}\s*h(?:oras|\d{2})?))?", re.I)
_LOCAL = re.compile(r"\b(?:no|na|pela)\s+((?:audit[óo]rio|sala|plataforma|espa[çc]o|centro de treinamento)\b(?:Dra?\.ᵃ?|[^.;]){0,160}?)(?=[.;]|,\s+(?:das|às|com|e\s+será|que)\b|$)", re.I)
_PRAZO = re.compile(r"inscri[çc][ãõ]o?e?s?\b[^.]{0,140}?\b(?:até|prorrogad[ao]s? para)\s+(?:(?:as|às)\s+(\d{1,2}h\d{0,2})\s+d[oa]\s+)?(?:o\s+)?(?:dia\s+)?"
                    rf"(\d{{1,2}}/\d{{1,2}}(?:/\d{{4}})?|\d{{1,2}}º?\s+de\s+(?:{_MES})(?:\s+de\s+\d{{4}})?)(?:,?\s*às\s+(\d{{1,2}}h\d{{0,2}}))?", re.I)
_LINK_INSCRICAO = re.compile(r"(?:INSCRI[ÇC][ÃÕ]O?E?S?\s*:|inscrever|inscri[çc][ãõ]o?e?s?[^<]{0,80}(?:link|aqui))[^<]{0,40}(?:<[^a][^>]*>\s*)*<a[^>]+href=\"([^\"]+)\"", re.I)


def _campo(corpo, rotulo):
    achado = re.search(rf"\b(?:{rotulo})\s*:\s*(.+?)\s*(?=\b(?:{_ROTULOS})\s*:|$)", corpo)
    return achado.group(1).strip(" .;“”\"") if achado else ""


def _data_texto(texto, publicado):
    """"25/11/2026" ou "16 de novembro" → date."""
    numerica = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$", texto)
    if numerica:
        dia, mes, ano = numerica.groups()
        return date(int(ano or publicado.year), int(mes), int(dia))
    extenso = re.match(rf"(\d{{1,2}})º?\s+de\s+({_MES})(?:\s+de\s+(\d{{4}}))?", texto, re.I)
    if extenso:
        return date(int(extenso.group(3) or publicado.year), MESES.index(extenso.group(2).lower()) + 1, int(extenso.group(1)))
    return None


def _nome_do_evento(titulo, corpo, tema):
    """O nome do evento: o TEMA da ficha; senão o nome entre aspas no texto ("Congresso Internacional
    “...”"); senão o título da notícia sem "Inscrições abertas para" e afins."""
    if tema:
        return tema
    aspas = re.search(r"((?:[A-ZÁÉÍÓÚ][\wáéíóúâêôãõç]+\s+){0,3})[“\"]([^”\"]{12,200})[”\"]", corpo[len(titulo) * 2:][:2500])
    if aspas:
        antes = aspas.group(1).strip()
        return f"{antes}: {aspas.group(2).strip()}" if antes and antes.lower() not in ("o", "a") else aspas.group(2).strip()
    nome = re.sub(r"^.*?\b(?:abre|abrem|abertas?)\s+(?:as\s+)?inscri[çc][õo]es\s+(?:para|do|da|no|na)\s+", "", titulo, flags=re.I)
    nome = re.sub(r"^inscri[çc][õo]es\s+abertas\s+para\s+", "", nome, flags=re.I)
    nome = re.sub(r":\s*inscri[çc][õo]es.*$", "", nome, flags=re.I)
    return nome[:1].upper() + nome[1:]


def detalhar(evento):
    """Completa o evento com a página da notícia: nome, tipo, data, horário, local, período e link
    das inscrições."""
    publicado = date.fromisoformat(evento["publicado"])
    pagina, corpo = _pagina_da_noticia(evento["link"])
    if not corpo:
        return evento
    ficha = _TIPO_FICHA.search(corpo)
    trecho_ficha = corpo[ficha.start():] if ficha else ""
    tema = _campo(trecho_ficha, "TEMA") if ficha else ""
    quando_ficha = _campo(trecho_ficha, "DATA") if ficha else ""
    data = (data_do_evento(evento["titulo"], f"dia {quando_ficha}", publicado) if quando_ficha else None) \
        or (date.fromisoformat(evento["data"]) if evento["data"] else None) \
        or data_do_evento(evento["titulo"], corpo, publicado)
    hora = _campo(trecho_ficha, r"HOR[ÁA]RIO") if ficha else ""
    if not hora:
        achada = _HORA.search(corpo)
        if achada:
            inicio, fim = achada.group(1), achada.group(2)
            inicio = inicio if "h" in inicio else f"{inicio}h"
            hora = f"{inicio} às {re.sub(r'\s*horas', 'h', fim).replace(' ', '')}" if fim else inicio
    local = _campo(trecho_ficha, "LOCAL") if ficha else ""
    if not local:
        achado = _LOCAL.search(corpo)
        local = achado.group(1).strip() if achado else ""
    prazo = _PRAZO.search(corpo)
    ate = _data_texto(prazo.group(2), publicado) if prazo else None
    link = _LINK_INSCRICAO.search(pagina)
    return {
        **evento,
        "titulo": _nome_do_evento(evento["titulo"], corpo, tema),
        "noticia": evento["titulo"],
        "tipo": ficha.group(1).capitalize().replace("On-line", "on-line").replace("Online", "on-line") if ficha else "",
        "data": data.isoformat() if data else None,
        "quando": quando_ficha,
        "hora": hora[0].lower() + hora[1:] if hora else "",
        "local": local[0].upper() + local[1:] if local else "",
        "inscricoes_ate": ate.isoformat() if ate else None,
        "inscricoes_ate_hora": (prazo.group(1) or prazo.group(3) or "") if prazo else "",
        "inscricao": html.unescape(link.group(1)) if link else "",
    }


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
    """Os próximos eventos (não as notícias): nome, data, horário, local e inscrições, do mais
    próximo para o mais distante (os sem data no fim)."""
    from concurrent.futures import ThreadPoolExecutor

    hoje = datetime.now(FUSO_BRASILIA).date()
    noticias, vistos = [], set()
    for numero in range(1, PAGINAS + 1):
        for e in _pagina(numero):
            if e["link"] not in vistos:
                vistos.add(e["link"])
                noticias.append(e)
    # A data e os detalhes vêm da página de cada notícia recente ou de evento ainda por vir
    candidatas = [e for e in noticias if (e["data"] and e["data"] >= hoje.isoformat())
                  or e["publicado"] >= (hoje - timedelta(days=DIAS_BUSCA_PAGINA)).isoformat()]
    with ThreadPoolExecutor(max_workers=6) as executor:
        detalhados = list(executor.map(detalhar, candidatas))
    eventos = []
    for e in detalhados:
        futuro = e["data"] and e["data"] >= hoje.isoformat()
        recente_sem_data = not e["data"] and e["publicado"] >= (hoje - timedelta(days=DIAS_SEM_DATA)).isoformat()
        if futuro or recente_sem_data:
            eventos.append(e)
    eventos.sort(key=lambda e: (e["data"] is None, e["data"] or "", not e["inscricoes"], e["publicado"]))
    # Duas notícias do mesmo evento (a da abertura das inscrições e a das vagas custeadas, por
    # exemplo): mesma data e nome parecido; fica a mais completa
    unicos = []
    for e in eventos:
        palavras = _palavras(e["titulo"])
        igual = next((o for o in unicos if o["data"] == e["data"] and len(palavras & _palavras(o["titulo"])) >= 3), None)
        if not igual:
            unicos.append(e)
        elif sum(bool(e.get(k)) for k in ("hora", "local", "inscricao")) > sum(bool(igual.get(k)) for k in ("hora", "local", "inscricao")):
            unicos[unicos.index(igual)] = e
    return {"eventos": unicos[:QUANTIDADE], "pagina": PAGINA}


def _palavras(titulo):
    return {p for p in re.findall(r"\w+", titulo.lower()) if len(p) > 5}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for e in coletar()["eventos"]:
        print(e["data"], "|", e["titulo"], "|", e.get("tipo"), "|", e.get("hora"), "|", e.get("local"), "|",
              e.get("inscricoes_ate"), e.get("inscricoes_ate_hora"), "|", e.get("inscricao"))
