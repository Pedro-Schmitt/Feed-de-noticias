"""Informativos comentados do STF e do STJ publicados no Dizer o Direito, com a indicação
dos julgados que interessam ao Ministério Público estadual.

O Dizer o Direito é um blog do Blogger: o feed por marcador traz o índice de cada
informativo, com o ramo do Direito (negrito), o assunto (itálico) e cada julgado num
parágrafo que começa com "§", seguido das marcas ⭐ 🏛️ 🔄.
"""

import html
import io
import re
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from pypdf import PdfReader

TIMEOUT = 30
FEED = "https://www.blogger.com/feeds/2154959394178215399/posts/default/-/{rotulo}"
TRIBUNAIS = {
    "stf": "Informativo comentado STF",
    "stj": "informativo comentado STJ",
}
DIAS_NOVO = 7  # informativo publicado há menos que isso aparece como "novo"
QUANTIDADE = 3  # informativos mostrados por tribunal
CARACTERES_BUSCA = 50  # início da tese procurado no PDF para achar a página do julgado

# Texto das páginas de cada PDF já baixado (os PDFs não mudam depois de publicados)
_paginas_pdf = {}

MARCAS = {"⭐": "importante", "🏛": "repetitivo", "🔄": "mudanca"}

# Matérias de atuação do MP estadual. A mesma lista classifica os julgados dos informativos e
# as atribuições das promotorias (lista oficial do MPGO), para que um "converse" com o outro.
# É uma indicação automática por palavras-chave, não análise jurídica
CITA_MP = re.compile(r"Minist[ée]rio P[úu]blico|\bMPs?\b|\bparquet\b|promotor", re.I)
CITA_MP_ROTULO = "Cita o Ministério Público"
MATERIAS = [
    # "penal" sozinho fica de fora (pegaria "Polícia Penal"); o ramo penal é reconhecido pelo ramo do julgado
    ("Criminal", re.compile(r"\b(crimes?|criminal|criminais|drogas|entorpecentes?|tr[áa]fico|"
                            r"inqu[ée]rito policial|habeas corpus)\b", re.I)),
    ("Tribunal do Júri", re.compile(r"j[úu]ri", re.I)),
    ("Execução penal", re.compile(r"execu[çc][ãa]o penal|execu[çc][õo]es penais|indulto|livramento condicional|"
                                  r"progress[ãa]o de regime", re.I)),
    ("Violência doméstica", re.compile(r"viol[êe]ncia dom[ée]stica|Maria da Penha|feminic|contra a mulher", re.I)),
    ("Infância e juventude", re.compile(r"inf[âa]ncia|juventude|crian[çc]as?|adolescentes?|ato infracional|\bECA\b", re.I)),
    ("Família e sucessões", re.compile(r"fam[íi]lia|sucess[õo]es|\balimentos\b|div[óo]rcio|uni[ãa]o est[áa]vel|"
                                       r"casamento|curatela|interdi[çc]", re.I)),
    ("Patrimônio público", re.compile(r"patrim[ôo]nio p[úu]blico|improbidade|licita[çc]|er[áa]rio|fazendas? p[úu]blicas?",
                                      re.I)),
    ("Tutela coletiva", re.compile(r"a[çc][ãa]o civil p[úu]blica|inqu[ée]rito civil|ajustamento de conduta|\bTAC\b|"
                                   r"difusos|coletivos", re.I)),
    ("Meio ambiente e urbanismo", re.compile(r"ambient|urban[íi]s|patrim[ôo]nio hist[óo]rico|cultural|parcelamento do solo",
                                             re.I)),
    ("Consumidor", re.compile(r"consumidor", re.I)),
    ("Saúde", re.compile(r"\bsa[úu]de\b|\bSUS\b|medicamentos?", re.I)),
    ("Educação", re.compile(r"educa[çc][ãa]o|\bensino\b|escolas?\b", re.I)),
    ("Idoso e pessoa com deficiência", re.compile(r"\bidos[oa]s?\b|defici[êe]ncia", re.I)),
    ("Eleitoral", re.compile(r"eleitora", re.I)),
    ("Registros públicos", re.compile(r"registros? p[úu]blicos?|registro civil|cart[óo]rio|notaria", re.I)),
    ("Fundações", re.compile(r"funda[çc][õo]es|terceiro setor", re.I)),
    ("Controle externo da atividade policial", re.compile(r"atividade policial|controle externo", re.I)),
    ("Ordem tributária", re.compile(r"ordem tribut[áa]ria|sonega[çc][ãa]o|crimes? tribut", re.I)),
    ("Cidadania", re.compile(r"cidad[ãa]os?\b|cidadania|direitos humanos", re.I)),
]
TODAS_AS_MATERIAS = [nome for nome, _ in MATERIAS]


def materias_do_texto(texto):
    return [nome for nome, padrao in MATERIAS if padrao.search(texto)]


def materias_da_atribuicao(atribuicao):
    """Matérias de uma promotoria pela sua atribuição. "Plena" (comarca de promotoria única) ou
    sem nenhuma matéria reconhecida vale como todas."""
    achadas = materias_do_texto(atribuicao or "")
    plena = not achadas or bool(re.fullmatch(r"\s*plena\.?\s*", atribuicao or "", re.I))
    return {"materias": TODAS_AS_MATERIAS if plena else achadas, "plena": plena}


def _texto(trecho):
    trecho = re.sub(r"<!--.*?-->", " ", trecho, flags=re.S)
    trecho = re.sub(r"<[^>]+>", " ", trecho)
    return re.sub(r"\s+", " ", html.unescape(trecho)).strip()


def _interesse_mp(ramo, assunto, tese):
    """Por que o julgado interessa ao MP estadual: cita o MP e/ou as matérias (lista vazia se nenhum)."""
    motivos = [CITA_MP_ROTULO] if CITA_MP.search(tese) or CITA_MP.search(assunto) else []
    materias = materias_do_texto(f"{ramo} {assunto} {tese}")
    if "PENAL" in ramo.upper() and "Criminal" not in materias:  # ramo penal ou processual penal
        materias.insert(0, "Criminal")
    return motivos + materias


def ler_indice(conteudo):
    """Julgados do índice: [{ramo, assunto, tese, marcas, interesse_mp}]."""
    inicio = conteudo.find("NDICE DO INFORMATIVO")
    if inicio < 0:
        return []
    julgados, ramo, assunto = [], "", ""
    for paragrafo in re.findall(r"<p\b[^>]*>(.*?)</p>", conteudo[inicio:], re.S):
        texto = _texto(paragrafo)
        if not texto or texto.startswith("NDICE") or "julgado importante" in texto:
            continue
        if texto.upper() != texto and len(texto) >= 40:
            # Alguns itens vêm sem o marcador "§"; o "§" no meio é de artigo de lei
            tese = texto[1:] if texto.startswith("§") else texto
            marcas = [nome for simbolo, nome in MARCAS.items() if simbolo in tese]
            tese = re.sub(r"[⭐🏛🔄️]", "", tese).strip()
            julgados.append({
                "ramo": ramo,
                "assunto": assunto,
                "tese": tese,
                "marcas": marcas,
                "interesse_mp": _interesse_mp(ramo, assunto, tese),
            })
        elif texto.upper() == texto:  # títulos: ramo em negrito, assunto em itálico
            if re.search(r"<b\b", paragrafo):
                ramo, assunto = texto, ""
            else:
                assunto = texto
    return julgados


def _sem_espacos(texto):
    # A extração do PDF às vezes quebra palavras ("fixo u"): compara sem espaço nenhum
    return re.sub(r"\s+", "", texto).lower()


def paginas_pdf(url):
    if url not in _paginas_pdf:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        leitor = PdfReader(io.BytesIO(resp.content))
        _paginas_pdf[url] = [_sem_espacos(p.extract_text() or "") for p in leitor.pages]
    return _paginas_pdf[url]


def localizar_julgados(url, julgados):
    """Anota em cada julgado a página do PDF completo onde ele começa.

    O PDF começa pelo índice; no corpo, cada julgado abre com a mesma tese do índice e
    eles seguem a mesma ordem, então a busca continua de onde parou a anterior.
    """
    paginas = paginas_pdf(url)

    def no_corpo(pagina, chave):
        # No índice do PDF cada tese vem logo depois do marcador "▪"; no corpo, não
        posicao = pagina.find(chave)
        while posicao >= 0:
            if posicao == 0 or pagina[posicao - 1] != "▪":
                return True
            posicao = pagina.find(chave, posicao + 1)
        return False

    a_partir = 0
    for julgado in julgados:
        chave = _sem_espacos(julgado["tese"])[:CARACTERES_BUSCA]
        achou = next((i for i in range(a_partir, len(paginas)) if chave and no_corpo(paginas[i], chave)), None)
        if achou is not None:
            julgado["pagina"] = achou + 1
            a_partir = achou


def _informativo(entrada):
    titulo = entrada["title"]["$t"]
    numero = re.search(r"\d{3,4}", titulo)
    publicado = datetime.fromisoformat(entrada["published"]["$t"])
    conteudo = entrada.get("content", {}).get("$t", "")
    julgados = ler_indice(conteudo)
    pdfs = re.findall(r'href="([^"]+\.pdf)"', conteudo)
    completo = next((p for p in pdfs if "resumid" not in p.lower()), None)
    julgados_mp = [j for j in julgados if j["interesse_mp"]]
    if completo and julgados_mp:
        try:
            localizar_julgados(completo, julgados)
        except Exception as erro:  # sem a página, o link abre o PDF no começo
            print(f"[informativos] Falha ao ler o PDF {completo}: {erro}")
    return {
        "numero": numero.group(0) if numero else "",
        "titulo": titulo,
        "data": publicado.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "novo": (datetime.now(timezone.utc) - publicado).days < DIAS_NOVO,
        "link": next(l["href"] for l in entrada["link"] if l["rel"] == "alternate"),
        "pdf": completo,
        "total": len(julgados),
        "julgados_mp": julgados_mp,
    }


def ultimos_informativos(rotulo, quantidade=QUANTIDADE):
    resp = requests.get(
        FEED.format(rotulo=quote(rotulo)),
        params={"alt": "json", "max-results": quantidade},
        timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    return [_informativo(entrada) for entrada in resp.json()["feed"].get("entry", [])]


def coletar():
    """Os três últimos informativos do STF e do STJ. Um tribunal com falha vira None."""
    dados = {}
    for tribunal, rotulo in TRIBUNAIS.items():
        try:
            dados[tribunal] = ultimos_informativos(rotulo)
        except Exception as erro:
            print(f"[informativos] Falha nos informativos do {tribunal.upper()}: {erro}")
            dados[tribunal] = None
    return dados


if __name__ == "__main__":
    for tribunal, lista in coletar().items():
        for info in lista or []:
            print(f"\n== {tribunal.upper()} {info['numero']} ({info['data'][:10]}, novo={info['novo']}) "
                  f"{len(info['julgados_mp'])} de {info['total']} julgados de interesse do MP")
            for j in info["julgados_mp"]:
                print(f"  p.{j.get('pagina', '?')} [{', '.join(j['interesse_mp'])}] {j['ramo']} / {j['assunto']}: {j['tese'][:90]}")
