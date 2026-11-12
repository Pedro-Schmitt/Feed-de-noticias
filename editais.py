"""Editais de movimentação na carreira (promoção e remoção) do MPGO com inscrições abertas.

O Conselho Superior publica os editais numa página por ano, cada um com o PDF. O PDF diz a
promotoria, a entrância, a forma e o critério de provimento e o prazo: "pelo prazo de 10 (dez)
dias corridos, a contar do primeiro dia útil subsequente ao da publicação deste Edital no Diário
Oficial". A data de publicação vem no rodapé ("Diário Oficial do Ministério Público de 09/11/2026").
"""

import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests
from pypdf import PdfReader

TIMEOUT = 30
MPGO = "https://www.mpgo.mp.br"
PAGINA_ANO = MPGO + "/portal/conteudo/editais-{ano}"
DIAS_RECENTES = 30  # só os editais publicados nesse período podem estar abertos
PRAZO_PADRAO = 10
FUSO_BRASILIA = timezone(timedelta(hours=-3))
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Feriados nacionais de data fixa (dia, mês). Os móveis (Carnaval, Sexta-feira Santa, Corpus
# Christi) e pontos facultativos não entram: o prazo exibido é um cálculo, a conferir no edital
FERIADOS_FIXOS = {(1, 1), (21, 4), (1, 5), (7, 9), (12, 10), (2, 11), (15, 11), (20, 11), (25, 12)}

# Texto de cada PDF já lido (um edital publicado não muda)
_textos = {}


def _dia_util(dia):
    return dia.weekday() < 5 and (dia.day, dia.month) not in FERIADOS_FIXOS


def fim_das_inscricoes(publicado, dias):
    """Último dia do prazo: conta `dias` corridos a partir do primeiro dia útil após a publicação."""
    inicio = publicado + timedelta(days=1)
    while not _dia_util(inicio):
        inicio += timedelta(days=1)
    return inicio + timedelta(days=dias - 1)


def _texto_pdf(url):
    if url not in _textos:
        resp = requests.get(url, timeout=TIMEOUT, headers=CABECALHOS)
        resp.raise_for_status()
        paginas = PdfReader(io.BytesIO(resp.content)).pages
        _textos[url] = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in paginas))
    return _textos[url]


def _capitalizar(texto):
    """"PROMOTORIA DE JUSTIÇA DE RIALMA" -> "Promotoria de Justiça de Rialma"."""
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    palavras = texto.lower().split()
    return " ".join(p if i and p in pequenas else p[:1].upper() + p[1:] for i, p in enumerate(palavras))


def ler_edital(url, data_arquivo):
    texto = _texto_pdf(url)
    numero = re.search(r"EDITAL N\.?\s*(\d+/\d{4})", texto)
    publicado = re.search(r"Di[áa]rio Oficial do Minist[ée]rio P[úu]blico de (\d{2}/\d{2}/\d{4})", texto)
    publicado = datetime.strptime(publicado.group(1), "%d/%m/%Y").date() if publicado else data_arquivo
    prazo = re.search(r"pelo prazo de (\d+)", texto)
    dias = int(prazo.group(1)) if prazo else PRAZO_PADRAO

    entrancia = re.search(r"ENTR[ÂA]NCIA (INICIAL|INTERMEDI[ÁA]RIA|FINAL)", texto)
    if entrancia:
        entrancia = "Entrância " + entrancia.group(1).lower()
    elif "PROCURADORIAS" in texto:
        entrancia = "Procuradoria de Justiça"
    vaga = re.search(r"FORMA/CRIT[ÉE]RIO (.+?) ((?:REMO|PROMO)[ÇC][ÃA]O POR (?:ANTIGUIDADE|MERECIMENTO))", texto)
    subsidiario = re.search(r"Provimento [Ss]ubsidi[áa]rio: (\w+ por \w+)", texto)
    return {
        "numero": numero.group(1) if numero else "",
        "vaga": _capitalizar(vaga.group(1)) if vaga else "",
        "criterio": vaga.group(2).capitalize() if vaga else "",
        "subsidiario": subsidiario.group(1).capitalize() if subsidiario else "",
        "entrancia": entrancia or "",
        "dificil_provimento": "ifícil provimento" in texto,
        "publicado": publicado.isoformat(),
        "fim": fim_das_inscricoes(publicado, dias).isoformat(),
        "link": url,
    }


def editais_recentes(hoje):
    """[(url do PDF, data do arquivo)] dos editais dos últimos DIAS_RECENTES dias."""
    anos = {hoje.year, (hoje - timedelta(days=DIAS_RECENTES)).year}
    encontrados = []
    for ano in sorted(anos):
        resp = requests.get(PAGINA_ANO.format(ano=ano), timeout=TIMEOUT, headers=CABECALHOS)
        if resp.status_code == 404:  # página do ano ainda não criada
            continue
        resp.raise_for_status()
        for caminho in re.findall(r'href="(/portal/arquivos/(\d{4})/(\d{2})/(\d{2})/[^"]*Edital[^"]*\.pdf)"', resp.text, re.I):
            url, a, m, d = caminho
            data_arquivo = date(int(a), int(m), int(d))
            if data_arquivo >= hoje - timedelta(days=DIAS_RECENTES):
                encontrados.append((MPGO + url, data_arquivo))
    return list(dict.fromkeys(encontrados))


def coletar():
    """Editais com inscrições abertas hoje, do que termina antes para o que termina depois."""
    hoje = datetime.now(FUSO_BRASILIA).date()
    recentes = editais_recentes(hoje)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futuros = [executor.submit(ler_edital, url, data) for url, data in recentes]
    abertos = []
    for (url, _), futuro in zip(recentes, futuros):
        try:
            edital = futuro.result()
        except Exception as erro:  # um PDF com problema não derruba os outros
            print(f"[editais] Falha ao ler {url}: {erro}")
            continue
        if edital["fim"] >= hoje.isoformat():
            abertos.append(edital)
    abertos.sort(key=lambda e: (e["fim"], e["numero"]))
    return {
        "abertos": abertos,
        "pagina": PAGINA_ANO.format(ano=hoje.year),
    }


if __name__ == "__main__":
    dados = coletar()
    print(len(dados["abertos"]), "editais abertos")
    for e in dados["abertos"]:
        print(f"  {e['numero']} até {e['fim']} | {e['vaga']} | {e['criterio']} ({e['subsidiario']}) | "
              f"{e['entrancia']}{' | difícil provimento' if e['dificil_provimento'] else ''}")
