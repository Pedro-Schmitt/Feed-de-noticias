"""Informativos comentados do STF e do STJ publicados no Dizer o Direito, com a indicação dos
julgados que interessam ao Ministério Público estadual.

O Dizer o Direito é um blog do Blogger: o feed por marcador traz o índice de cada informativo,
com o ramo do Direito (negrito), o assunto (itálico) e cada julgado num parágrafo que começa com
"§", seguido das marcas ⭐ 🏛️ 🔄. O PDF completo é lido para levar cada julgado à sua página.

Como o tribunal publica o informativo semanas antes do comentário, os sites do STF e do STJ são
consultados à parte, só para o aviso dos informativos já publicados e ainda não comentados:
- STF: a página de informativos lista o número mais recente; cada edição é um HTML do Word
  (informativoNNNN.htm).
- STJ: a página do Informativo de Jurisprudência traz o número da última edição.
"""

import html
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from pypdf import PdfReader

TIMEOUT = 30
NAVEGADOR = {"User-Agent": "Mozilla/5.0"}
DIAS_NOVO = 7  # informativo publicado há menos que isso aparece como "novo"
QUANTIDADE = {"stf": 5, "stj": 3}  # informativos mostrados por tribunal (o quadro do STF tem mais espaço)
MAXIMO_PENDENTES = 6  # no aviso dos ainda não comentados
CARACTERES_BUSCA = 50  # início da tese procurado no PDF para achar a página do julgado
MARCAS = {"⭐": "importante", "🏛": "repetitivo", "🔄": "mudanca"}
_paginas_pdf = {}  # texto das páginas de cada PDF já baixado (não mudam depois de publicados)

STF_LISTA = "https://portal.stf.jus.br/textos/verTexto.asp?servico=informativoSTF"
STF_EDICAO = "https://www.stf.jus.br/arquivo/informativo/documento/informativo{numero}.htm"
STF_PDF = "https://www.stf.jus.br/arquivo/cms/informativoSTF/anexo/Informativo_PDF/Informativo_stf_{numero}.pdf"
STJ_BASE = "https://processo.stj.jus.br/jurisprudencia/externo/informativo/"
STJ_EDICAO = STJ_BASE + "?acao=pesquisarumaedicao&livre={numero:04d}.cod."
STJ_NOTA = STJ_BASE + "?livre=@CNOT={nota}"

# Dizer o Direito (blog do Blogger): feed por marcador
FEED_DOD = "https://www.blogger.com/feeds/2154959394178215399/posts/default/-/{rotulo}"
ROTULOS_DOD = {"stf": "Informativo comentado STF", "stj": "informativo comentado STJ"}

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]

# Matérias de atuação do MP estadual. A mesma lista classifica os julgados dos informativos e
# as atribuições das promotorias (lista oficial do MPGO), para que um "converse" com o outro.
# É uma indicação automática por palavras-chave, não análise jurídica
CITA_MP = re.compile(r"Minist[ée]rio P[úu]blico|\bMPs?\b|\bparquet\b|promotor", re.I)
CITA_MP_ROTULO = "Cita o Ministério Público"
MATERIAS = [
    # "penal" sozinho fica de fora (pegaria "Polícia Penal"); o ramo penal é reconhecido pelo ramo do julgado
    ("Criminal", re.compile(r"\b(crimes?|criminal|criminais|drogas|entorpecentes?|tr[áa]fico|"
                            r"inqu[ée]rito policial|habeas corpus)\b", re.I)),
    ("Tribunal do Júri", re.compile(r"\bj[úu]ri\b|\bjurados?\b|pron[úu]ncia", re.I)),
    ("Execução penal", re.compile(r"execu[çc][ãa]o penal|execu[çc][õo]es penais|indulto|livramento condicional|"
                                  r"progress[ãa]o de regime", re.I)),
    ("Violência doméstica", re.compile(r"viol[êe]ncia dom[ée]stica|Maria da Penha|feminic|contra (a )?mulher", re.I)),
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


def _interesse_mp(ramo, assunto, tese):
    """Por que o julgado interessa ao MP estadual: cita o MP e/ou as matérias (lista vazia se nenhum)."""
    motivos = [CITA_MP_ROTULO] if CITA_MP.search(tese) or CITA_MP.search(assunto) else []
    materias = materias_do_texto(f"{ramo} {assunto} {tese}")
    if "PENAL" in ramo.upper() and "Criminal" not in materias:  # ramo penal ou processual penal
        materias.insert(0, "Criminal")
    return motivos + materias


def _texto(trecho):
    trecho = re.sub(r"<!--.*?-->|<!\[[^\]]*\]>", " ", trecho, flags=re.S)
    trecho = re.sub(r"<(script|style)\b.*?</\1>", " ", trecho, flags=re.S | re.I)
    trecho = re.sub(r"<[^>]+>", " ", trecho)
    texto = re.sub(r"\s+", " ", html.unescape(trecho)).strip()
    # O HTML do Word do STF deixa espaços dentro dos parênteses: "( NECRIMs )"
    return re.sub(r"\(\s+", "(", re.sub(r"\s+([),;.])", r"\1", texto))


def _pagina(url):
    resp = requests.get(url, timeout=TIMEOUT, headers=NAVEGADOR)
    resp.raise_for_status()
    # Os dois tribunais publicam em Latin-1/Windows-1252
    return resp.content.decode("cp1252", errors="replace")


def _data_por_extenso(texto):
    """"10 de novembro de 2026" → ISO (meia-noite de Brasília, em UTC)."""
    achou = re.search(r"(\d{1,2})º? de (\w+) de (\d{4})", texto)
    if not achou or achou.group(2).lower() not in MESES:
        return None
    dia, mes, ano = int(achou.group(1)), MESES.index(achou.group(2).lower()) + 1, int(achou.group(3))
    return datetime(ano, mes, dia, 3, tzinfo=timezone.utc).isoformat(timespec="seconds")


def _novo(data):
    return bool(data) and (datetime.now(timezone.utc) - datetime.fromisoformat(data)).days < DIAS_NOVO


_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "à", "em", "na", "no", "por", "com"}


def _ramo(texto):
    """"DIREITO PROCESSUAL PENAL" → "Direito Processual Penal"."""
    palavras = texto.lower().split()
    return " ".join(p if p in _MINUSCULAS and i else p.capitalize() for i, p in enumerate(palavras))


def _link_trecho(url, texto):
    """Link que já rola a página até o trecho (fragmento de texto, aceito pelos navegadores atuais)."""
    palavras = re.sub(r"[“”\"()]", " ", texto).split()[:8]
    if not palavras:
        return url
    return f"{url}#:~:text={quote(' '.join(palavras), safe='').replace('-', '%2D')}"


# --- STF ---

_STF_RAMO = re.compile(r"^(DIREITO [^–]+?)\s+–\s+(.+)$")
_STF_FIM = re.compile(r"^\d\s+(INOVA|CLIPPING|TRANSCRI)")


def _stf_julgados(pagina, url):
    paragrafos = [_texto(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", pagina, re.S | re.I)]
    julgados, atual, esperando_tese = [], None, False
    for texto in paragrafos:
        if not texto or texto in ("Sumário",):
            continue
        if _STF_FIM.match(texto):
            break
        ramo = _STF_RAMO.match(texto)
        if ramo and texto.upper() == texto:
            if atual is None or atual["titulo"]:  # começa outro julgado
                atual = {"ramo": ramo.group(1), "extra": ramo.group(2), "titulo": "", "tese": ""}
                julgados.append(atual)
            else:  # segundo ramo do mesmo julgado
                atual["extra"] += f" {texto}"
            esperando_tese = False
            continue
        if atual is None:
            continue
        if texto.startswith("Resumo:"):
            resto = texto[len("Resumo:"):].strip()
            if resto:
                atual["tese"] = atual["tese"] or resto
            else:
                esperando_tese = True
        elif esperando_tese:
            atual["tese"] = atual["tese"] or texto
            esperando_tese = False
        elif not atual["titulo"] and not texto.startswith("ODS"):
            atual["titulo"] = texto

    resultado = []
    for j in julgados:
        if not j["titulo"] or not j["tese"]:
            continue
        resultado.append({
            "ramo": _ramo(j["ramo"]),
            "assunto": j["titulo"],
            "tese": j["tese"],
            "marcas": ["repetitivo"] if re.search(r"\bRG\b|repercuss[ãa]o geral", j["titulo"]) else [],
            "interesse_mp": _interesse_mp(j["ramo"], f"{j['extra']} {j['titulo']}", j["tese"]),
            "link": _link_trecho(url, j["tese"]),
        })
    return resultado


def ultimo_stf():
    numeros = [int(n) for n in re.findall(r"informativo(\d{4})\.htm", _pagina(STF_LISTA), re.I)]
    if not numeros:
        raise RuntimeError("número do último informativo não encontrado")
    return max(numeros)


def informativo_stf(numero):
    url = STF_EDICAO.format(numero=numero)
    pagina = _pagina(url)
    data = _data_por_extenso(_texto(pagina[:20000]).split("divulgação:", 1)[-1])
    julgados = _stf_julgados(pagina, url)
    return {
        "numero": str(numero),
        "data": data,
        "novo": _novo(data),
        "link": url,
        "pdf": STF_PDF.format(numero=numero),
        "total": len(julgados),
        "julgados_mp": [j for j in julgados if j["interesse_mp"]],
    }


# --- STJ ---

def _stj_celula(bloco, rotulo):
    """Texto da célula ao lado do rótulo ("Ramo do Direito", "Tema", "Processo")."""
    achou = re.search(rf'clsInformativoLabel">\s*(?:<[^>]+>\s*)*{rotulo}.*?clsInformativoTexto(?:Formatado)?">(.*?)</div>',
                      bloco, re.S)
    return _texto(achou.group(1)) if achou else ""


def _stj_julgados(pagina):
    julgados = []
    for bloco in pagina.split('class="clsInformativoBlocoItem"')[1:]:
        nota = re.search(r"@CNOT=(\d+)", bloco)
        destaque = re.search(r'>Destaque</div>.*?clsInformativoTextoFormatado">(.*?)</div>', bloco, re.S)
        if not nota or not destaque:
            continue
        ramo = _stj_celula(bloco, "Ramo do Direito")
        tema = _stj_celula(bloco, r"(?:<span>)?Tema")
        processo = _stj_celula(bloco, r"(?:<label.*?</label>\s*</div>\s*)?Processo")
        tese = _texto(destaque.group(1))
        julgados.append({
            "ramo": _ramo(ramo),
            "assunto": tema,
            "tese": tese,
            "marcas": ["repetitivo"] if re.search(r"\(Tema\s+[\d.]+\)|repetitivo", processo, re.I) else [],
            "interesse_mp": _interesse_mp(ramo, tema, tese),
            "link": STJ_NOTA.format(nota=nota.group(1)),
        })
    return julgados


def ultimo_stj():
    achou = re.search(r'id="idInformativoEdicaoAtual" value="(\d+)"', _pagina(STJ_BASE))
    if not achou:
        raise RuntimeError("número da última edição não encontrado")
    return int(achou.group(1))


def informativo_stj(numero):
    url = STJ_EDICAO.format(numero=numero)
    pagina = _pagina(url)
    cabecalho = re.search(r'clsInformativoTitulo">(.*?)</span>', pagina, re.S)
    data = _data_por_extenso(_texto(cabecalho.group(1))) if cabecalho else None
    julgados = _stj_julgados(pagina)
    return {
        "numero": str(numero),
        "data": data,
        "novo": _novo(data),
        "link": url,
        "pdf": None,
        "total": len(julgados),
        "julgados_mp": [j for j in julgados if j["interesse_mp"]],
    }


# --- Dizer o Direito (fonte dos informativos mostrados) ---

def ler_indice(conteudo):
    """Julgados do índice do post: [{ramo, assunto, tese, marcas, interesse_mp}]."""
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
        resp = requests.get(url, timeout=60, headers=NAVEGADOR)
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
        "numero": str(int(numero.group(0))) if numero else "",
        "titulo": titulo,
        "data": publicado.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "novo": (datetime.now(timezone.utc) - publicado).days < DIAS_NOVO,
        "link": next(l["href"] for l in entrada["link"] if l["rel"] == "alternate"),
        "pdf": completo,
        "total": len(julgados),
        "julgados_mp": julgados_mp,
    }


def comentados(tribunal):
    resp = requests.get(FEED_DOD.format(rotulo=quote(ROTULOS_DOD[tribunal])),
                        params={"alt": "json", "max-results": QUANTIDADE[tribunal]},
                        timeout=TIMEOUT, headers=NAVEGADOR)
    resp.raise_for_status()
    return [_informativo(entrada) for entrada in resp.json()["feed"].get("entry", [])]


# --- Aviso: já publicados pelo tribunal, ainda não comentados ---

def pendentes(tribunal, ultimo_comentado):
    """Informativos que o tribunal já publicou e o Dizer o Direito ainda não comentou:
    [{numero, data, link, pdf, total, de_interesse}], do mais novo para o mais antigo."""
    ultimo, ler = (ultimo_stf(), informativo_stf) if tribunal == "stf" else (ultimo_stj(), informativo_stj)
    numeros = list(range(ultimo, max(ultimo_comentado, ultimo - MAXIMO_PENDENTES), -1))
    with ThreadPoolExecutor(max_workers=max(len(numeros), 1)) as executor:
        edicoes = list(executor.map(lambda n: _ou_none(ler, n), numeros))
    saida = []
    for numero, info in zip(numeros, edicoes):
        url = (STF_EDICAO if tribunal == "stf" else STJ_EDICAO).format(numero=numero)
        saida.append({
            "numero": str(numero),
            "data": info["data"] if info else None,
            "link": url,
            "pdf": info["pdf"] if info else None,
            "total": info["total"] if info else None,
        })
    return saida


def _ou_none(ler, numero):
    try:
        return ler(numero)
    except Exception as erro:
        print(f"[informativos] Falha no informativo {numero}: {erro}")
        return None


def coletar():
    """Os últimos informativos comentados do Dizer o Direito (STF e STJ) e, à parte, os que os
    tribunais já publicaram e ainda não foram comentados. Uma parte com falha vira None."""
    dados = {"pendentes": {}}
    for tribunal in ("stf", "stj"):
        try:
            dados[tribunal] = comentados(tribunal) or None
        except Exception as erro:
            print(f"[informativos] Falha nos informativos do {tribunal.upper()}: {erro}")
            dados[tribunal] = None
        numeros = [int(i["numero"]) for i in dados[tribunal] or [] if i["numero"]]
        try:
            dados["pendentes"][tribunal] = pendentes(tribunal, max(numeros)) if numeros else None
        except Exception as erro:
            print(f"[informativos] Falha ao consultar o site do {tribunal.upper()}: {erro}")
            dados["pendentes"][tribunal] = None
    return dados


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    dados = coletar()
    for tribunal in ("stf", "stj"):
        for info in dados[tribunal] or []:
            print(f"\n== {tribunal.upper()} {info['numero']} ({info['data'][:10]}, novo={info['novo']}) "
                  f"{len(info['julgados_mp'])} de {info['total']} julgados de interesse do MP")
            for j in info["julgados_mp"]:
                print(f"  p.{j.get('pagina', '?')} [{', '.join(j['interesse_mp'])}] {j['ramo']} / {j['assunto'][:50]}: {j['tese'][:80]}")
        print(f"\n   Pendentes {tribunal.upper()}:",
              [(p["numero"], (p["data"] or "")[:10], p["total"]) for p in dados["pendentes"][tribunal] or []])
