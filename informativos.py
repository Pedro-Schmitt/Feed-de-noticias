"""Informativos de jurisprudência do STF e do STJ, lidos nos sites dos próprios tribunais, com a
indicação dos julgados que interessam ao Ministério Público estadual.

A fonte primária é o tribunal: o informativo sai primeiro no site dele e só semanas depois é
comentado no Dizer o Direito. Cada informativo traz o link do tribunal e, quando já publicada,
a versão comentada do Dizer o Direito (feed do Blogger, pelo número do informativo).

- STF: a página de informativos lista o número mais recente; cada edição é um HTML do Word
  (informativoNNNN.htm) com, para cada julgado, o ramo e os assuntos em maiúsculas, o título
  com o processo e o "Resumo:" cujo primeiro parágrafo é a tese.
- STJ: a página do Informativo de Jurisprudência traz o número da última edição; cada edição
  lista as notas com processo, ramo do Direito, tema e destaque (a tese), e cada nota tem
  endereço próprio (?livre=@CNOT=NNNNNN).
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

import requests

TIMEOUT = 30
NAVEGADOR = {"User-Agent": "Mozilla/5.0"}
DIAS_NOVO = 7  # informativo publicado há menos que isso aparece como "novo"
QUANTIDADE = {"stf": 5, "stj": 3}  # informativos mostrados por tribunal (o quadro do STF tem mais espaço)

STF_LISTA = "https://portal.stf.jus.br/textos/verTexto.asp?servico=informativoSTF"
STF_EDICAO = "https://www.stf.jus.br/arquivo/informativo/documento/informativo{numero}.htm"
STF_PDF = "https://www.stf.jus.br/arquivo/cms/informativoSTF/anexo/Informativo_PDF/Informativo_stf_{numero}.pdf"
STJ_BASE = "https://processo.stj.jus.br/jurisprudencia/externo/informativo/"
STJ_EDICAO = STJ_BASE + "?acao=pesquisarumaedicao&livre={numero:04d}.cod."
STJ_NOTA = STJ_BASE + "?livre=@CNOT={nota}"

# Versão comentada no Dizer o Direito (blog do Blogger), procurada pelo número do informativo
FEED_DOD = "https://www.blogger.com/feeds/2154959394178215399/posts/default/-/{rotulo}"
ROTULOS_DOD = {"stf": "Informativo comentado STF", "stj": "informativo comentado STJ"}
POSTS_DOD = 15  # o Dizer o Direito comenta com algumas semanas de atraso

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


# --- Dizer o Direito ---

def comentados(tribunal):
    """{número do informativo: {"link", "pdf", "data"}} dos últimos posts do Dizer o Direito."""
    resp = requests.get(FEED_DOD.format(rotulo=quote(ROTULOS_DOD[tribunal])),
                        params={"alt": "json", "max-results": POSTS_DOD}, timeout=TIMEOUT, headers=NAVEGADOR)
    resp.raise_for_status()
    achados = {}
    for entrada in resp.json()["feed"].get("entry", []):
        numero = re.search(r"\d{3,4}", entrada["title"]["$t"])
        if not numero:
            continue
        conteudo = entrada.get("content", {}).get("$t", "")
        pdfs = re.findall(r'href="([^"]+\.pdf)"', conteudo)
        achados.setdefault(str(int(numero.group(0))), {
            "link": next(l["href"] for l in entrada["link"] if l["rel"] == "alternate"),
            "pdf": next((p for p in pdfs if "resumid" not in p.lower()), None),
            "data": datetime.fromisoformat(entrada["published"]["$t"]).astimezone(timezone.utc).isoformat(timespec="seconds"),
        })
    return achados


def ultimos_informativos(tribunal, quantidade=None):
    quantidade = quantidade or QUANTIDADE[tribunal]
    ultimo, ler = (ultimo_stf(), informativo_stf) if tribunal == "stf" else (ultimo_stj(), informativo_stj)
    with ThreadPoolExecutor(max_workers=quantidade + 1) as executor:
        dod = executor.submit(comentados, tribunal)
        edicoes = list(executor.map(lambda n: _ou_none(ler, n), range(ultimo, ultimo - quantidade, -1)))
        try:
            dod = dod.result()
        except Exception as erro:
            print(f"[informativos] Falha no Dizer o Direito ({tribunal.upper()}): {erro}")
            dod = {}
    for info in edicoes:
        if info:
            info["comentado"] = dod.get(info["numero"])
    return [info for info in edicoes if info]


def _ou_none(ler, numero):
    try:
        return ler(numero)
    except Exception as erro:
        print(f"[informativos] Falha no informativo {numero}: {erro}")
        return None


def coletar():
    """Os últimos informativos do STF e do STJ. Um tribunal com falha vira None."""
    dados = {}
    for tribunal in ("stf", "stj"):
        try:
            dados[tribunal] = ultimos_informativos(tribunal) or None
        except Exception as erro:
            print(f"[informativos] Falha nos informativos do {tribunal.upper()}: {erro}")
            dados[tribunal] = None
    return dados


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for tribunal, lista in coletar().items():
        for info in lista or []:
            comentado = info["comentado"]["link"] if info["comentado"] else "ainda não comentado"
            print(f"\n== {tribunal.upper()} {info['numero']} ({(info['data'] or '?')[:10]}, novo={info['novo']}) "
                  f"{len(info['julgados_mp'])} de {info['total']} julgados de interesse do MP · DoD: {comentado}")
            for j in info["julgados_mp"]:
                print(f"  [{', '.join(j['interesse_mp'])}] {j['ramo']} / {j['assunto'][:60]}: {j['tese'][:90]}")
