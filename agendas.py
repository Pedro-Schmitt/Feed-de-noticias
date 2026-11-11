"""Agendas oficiais: o que está em julgamento no STF e no CSMP do MPGO, e as agendas do
Presidente da República, do Senado Federal e da Câmara dos Deputados."""

import html
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import requests
from pypdf import PdfReader

TIMEOUT = 30
FUSO_BRASILIA = timezone(timedelta(hours=-3))  # sem horário de verão desde 2019
DIAS_A_FRENTE = 7  # sem nada hoje (ex.: fim de semana), mostra o próximo dia com agenda
TAMANHO_TEXTO = 220

# Alguns portais recusam pedidos sem cara de navegador
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
}


def _get(url, headers=None, **kwargs):
    resp = requests.get(url, timeout=TIMEOUT, headers={**CABECALHOS, **(headers or {})}, **kwargs)
    resp.raise_for_status()
    return resp


def _sem_html(texto):
    texto = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def _resumir(texto, tamanho=TAMANHO_TEXTO):
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if len(texto) <= tamanho:
        return texto
    return texto[:tamanho].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _lista(valor):
    """Os dados abertos do Senado viram objeto quando há um item só, e lista quando há vários."""
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def _nome_proprio(texto):
    """"MARTA MAIA DE MENEZES" -> "Marta Maia de Menezes"."""
    particulas = {"de", "da", "do", "dos", "das", "e"}
    palavras = texto.strip().title().split()
    return " ".join(p.lower() if i and p.lower() in particulas else p for i, p in enumerate(palavras))


def _data_br(texto):
    return datetime.strptime(texto, "%d/%m/%Y").date()


def hoje_brasilia():
    return datetime.now(FUSO_BRASILIA).date()


# --- STF: sessões presenciais (com a lista de processos) e sessões virtuais em andamento ---

STF_SERVICOS = "https://portal.stf.jus.br/pauta/services/"
STF_CALENDARIO = "https://portal.stf.jus.br/pauta/pesquisarCalendario.asp"


def _calendario_stf(mes, ano):
    return _get(f"{STF_SERVICOS}calendario-service.asp", params={"dados": "calendarios", "mes": mes, "ano": ano}).json()


def _processo_stf(incidente):
    processo = f"{incidente['classe']} {incidente['numero']}"
    if incidente.get("cadeia"):  # recurso dentro do processo, ex.: "EMB.DECL. NA ARGUIÇÃO..."
        processo += f" ({incidente['cadeia'].split(' NA ')[0].split(' NO ')[0].strip()})"
    tema = re.sub(r"^\s*1\.\s*", "", incidente.get("resumoTema") or "")
    return {
        "processo": processo,
        "relator": _nome_proprio(incidente.get("relator") or ""),
        "tema": _resumir(tema),
        "link": "https://portal.stf.jus.br/processos/listarProcessos.asp?"
                f"classe={incidente['classe']}&numeroProcesso={incidente['numero']}",
    }


def agenda_stf(hoje):
    calendario = _calendario_stf(hoje.month, hoje.year)
    dias = [date(hoje.year, hoje.month, d) for d in calendario["diasPresenciais"]]
    proximo = next((d for d in dias if d >= hoje), None)
    if proximo is None:  # sem sessões no resto do mês: procura no mês seguinte
        seguinte = (hoje.replace(day=1) + timedelta(days=32)).replace(day=1)
        dias = [seguinte.replace(day=d) for d in _calendario_stf(seguinte.month, seguinte.year)["diasPresenciais"]]
        proximo = dias[0] if dias else None

    presencial = None
    if proximo:
        data_br = proximo.strftime("%d/%m/%Y")
        dados = _get(f"{STF_SERVICOS}calendario-service.asp", params={"dados": "sessao-presencial", "data": data_br}).json()
        sessoes = []
        for colegiado in dados.get("colegiados") or []:
            for sessao in colegiado.get("sessoes") or []:
                tipo = {"O": "ordinária", "E": "extraordinária"}.get(sessao.get("tipo"), "")
                sessoes.append({
                    "colegiado": colegiado["descricao"],
                    "inicio": sessao["dataInicio"],
                    "descricao": f"{sessao['numero']}ª sessão {tipo}".strip(),
                    "processos": [_processo_stf(i) for i in sessao.get("incidentes") or []],
                })
        presencial = {
            "data": proximo.isoformat(),
            "sessoes": sessoes,
            "link": f"{STF_CALENDARIO}?data={data_br}",
        }

    virtuais = []
    for julgamento in calendario.get("julgamentosVirtuais") or []:
        inicio, fim = _data_br(julgamento["dataInicial"]), _data_br(julgamento["dataFinal"])
        if inicio <= hoje <= fim:
            virtuais.append({
                "inicio": inicio.isoformat(),
                "fim": fim.isoformat(),
                "plenario": int(julgamento["qtdProcessosPlenario"]),
                "primeira_turma": int(julgamento["qtdPrimeiraTurma"]),
                "segunda_turma": int(julgamento["qtdSegundaTurma"]),
                "link": f"{STF_CALENDARIO}?dataInicio={julgamento['dataInicial']}&dataFim={julgamento['dataFinal']}",
            })
    virtuais.sort(key=lambda v: v["inicio"])
    return {"presencial": presencial, "virtuais": virtuais}


# --- CSMP do MPGO: pautas publicadas no portal (o conteúdo vem do PDF de cada pauta) ---

MPGO = "https://www.mpgo.mp.br"
CSMP_PAGINA = f"{MPGO}/portal/pagina/conselho-superior-do-ministerio-publico"
MAX_PAUTAS_CSMP = 4


def _itens_pauta(texto):
    """Itens numerados da pauta ("1. APROVAÇÃO DAS ATAS...;", "1 - JULGAMENTO DA PROPOSTA...")."""
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"(\d)\s+ª", r"\1ª", texto)  # "7 ª" -> "7ª"
    inicio = texto.find("RELAÇÃO DOS PROCEDIMENTOS PAUTADOS")
    if inicio >= 0:
        texto = texto[inicio:]
    for marca in ("SECRETARIA DO CONSELHO SUPERIOR", "Documento assinado", "Enviado para publicação"):
        fim = texto.find(marca)
        if fim > 0:
            texto = texto[:fim]

    itens, posicao, numero = [], 0, 1
    while True:
        achou = re.compile(rf"(?<![\d/.,]){numero}\s?(?:\.|-)\s+(?=[A-ZÀ-Ý0-9\"(])").search(texto, posicao)
        if not achou:
            return itens
        seguinte = re.compile(rf"(?<![\d/.,]){numero + 1}\s?(?:\.|-)\s+(?=[A-ZÀ-Ý0-9\"(])").search(texto, achou.end())
        trecho = texto[achou.end(): seguinte.start() if seguinte else len(texto)]
        # Títulos de blocos (ex.: "AUTOS EXTRAJUDICIAIS DA 19ª SESSÃO...: RELATOR: ...") param no ":"
        trecho = re.split(r";|:\s|\sRELATOR", trecho)[0]
        itens.append(_resumir(trecho.strip(" .;:").capitalize(), 160))
        posicao, numero = achou.end(), numero + 1


def _ler_pauta_csmp(link_noticia):
    pagina = _get(link_noticia).text
    pdfs = re.findall(r'href="([^"]+\.pdf)"', pagina, re.I)
    if not pdfs:
        return None, {}
    pdf = pdfs[0] if pdfs[0].startswith("http") else MPGO + pdfs[0]
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(_get(pdf).content)).pages)

    administrativo = set(re.findall(r"Autos Administrativos n\. (\d+)", texto))
    autos = set(re.findall(r"(?<!\d)(?:19|20)\d{10}(?!\d)", texto)) - administrativo
    relatores = []
    for relator in re.findall(r"RELATORA?:\s*([^\n]+)", texto):
        nome = _nome_proprio(relator.split(" - ")[0])
        if nome not in relatores:
            relatores.append(nome)
    return pdf, {"processos": len(autos), "relatores": relatores, "itens": _itens_pauta(texto)}


def agenda_csmp(hoje):
    pagina = _get(CSMP_PAGINA).text
    pautas, vistos = [], set()
    for link, rotulo in re.findall(r'<a[^>]+href="(/portal/noticia/pauta-[^"]+)"[^>]*>(.*?)</a>', pagina, re.S):
        if link in vistos:
            continue
        vistos.add(link)
        # O rótulo começa com a data de publicação ("05/11/2026 16h58 Pauta da ...")
        titulo = re.sub(r"^\d{2}/\d{2}/\d{4}\s+\d{1,2}h\d{2}\s*", "", _sem_html(rotulo))
        datas = [_data_br(d) for d in re.findall(r"\d{2}/\d{2}/\d{4}", titulo)]
        if not datas:
            continue
        inicio, fim = min(datas), max(datas)
        situacao = "proxima" if hoje < inicio else "andamento" if hoje <= fim else "realizada"
        pautas.append({
            "titulo": re.sub(r"\s*-\s*(?:Dia\s+|de\s+)?\d{2}/\d{2}/\d{4}.*$", "", titulo).strip(),
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "situacao": situacao,
            "link": MPGO + link,
        })

    # Primeiro as sessões em andamento e as próximas; se não houver, a mais recente
    atuais = [p for p in pautas if p["situacao"] != "realizada"]
    escolhidas = atuais or sorted(pautas, key=lambda p: p["fim"], reverse=True)[:1]
    escolhidas = sorted(escolhidas, key=lambda p: p["inicio"])[:MAX_PAUTAS_CSMP]
    for pauta in escolhidas:
        try:
            pauta["pdf"], detalhes = _ler_pauta_csmp(pauta["link"])
            pauta.update(detalhes)
        except Exception as erro:  # sem o PDF, a sessão aparece só com título e data
            print(f"[agendas] Falha ao ler a pauta {pauta['titulo']}: {erro}")
    return escolhidas


# --- Presidente da República: agenda publicada pelo Planalto, uma página por dia ---

PLANALTO_AGENDA = "https://www.gov.br/planalto/pt-br/acompanhe-o-planalto/agenda-do-presidente-da-republica"


def _compromissos_planalto(pagina):
    compromissos = []
    for bloco in re.findall(r'<li class="item-compromisso-wrapper">(.*?)</li>', pagina, re.S):
        hora = re.search(r'class="compromisso-inicio">([^<]+)<', bloco)
        titulo = re.search(r'class="compromisso-titulo">(.*?)</h\d>', bloco, re.S)
        local = re.search(r'class="compromisso-local">(.*?)</div>', bloco, re.S)
        if titulo:
            compromissos.append({
                "hora": hora.group(1).strip() if hora else "",
                "titulo": _sem_html(titulo.group(1)),
                "local": _sem_html(local.group(1)) if local else "",
            })
    return compromissos


def agenda_presidente(hoje):
    # A página principal tem os links dos dias; o endereço inclui o nome do presidente,
    # por isso é tirado dela em vez de ficar fixo aqui
    principal = _get(PLANALTO_AGENDA).text
    links = re.findall(r'href="([^"]+/agenda-do-presidente-da-republica)/\d{4}-\d{2}-\d{2}"', principal)
    base = links[0] if links else PLANALTO_AGENDA

    # A agenda do dia costuma sair pela manhã: até lá, mostra a última publicada
    for atras in range(4):
        dia = hoje - timedelta(days=atras)
        resp = requests.get(f"{base}/{dia.isoformat()}", timeout=TIMEOUT, headers=CABECALHOS)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        aviso = re.search(r'<div class="portalMessage info">(.*?)</div>', resp.text, re.S)
        return {
            "data": dia.isoformat(),
            "aviso": _sem_html(aviso.group(1)) if aviso else "",
            "compromissos": _compromissos_planalto(resp.text),
            "link": f"{base}/{dia.isoformat()}",
        }
    return {"data": None, "aviso": "", "compromissos": [], "link": PLANALTO_AGENDA}


# --- Senado Federal: Plenário e comissões (dados abertos) ---

SENADO_DADOS = "https://legis.senado.leg.br/dadosabertos"
MAX_MATERIAS = 6


def _sessoes_senado(dia):
    dados = _get(f"{SENADO_DADOS}/plenario/agenda/dia/{dia:%Y%m%d}.json", headers={"Accept": "application/json"}).json()
    sessoes = []
    for sessao in _lista((dados.get("AgendaPlenario", {}).get("Sessoes") or {}).get("Sessao")):
        materias = _lista((sessao.get("Materias") or {}).get("Materia"))
        evento = (sessao.get("Evento") or {}).get("DescricaoEvento", "")
        sessoes.append({
            "hora": sessao.get("Hora", ""),
            "tipo": (sessao.get("TipoSessao") or "").strip().capitalize(),
            "casa": "Congresso Nacional" if sessao.get("Casa") == "CN" else "Senado",
            "situacao": sessao.get("SituacaoSessao", ""),
            "descricao": _resumir(evento),
            "materias": [
                {
                    "identificacao": m.get("DescricaoIdentificacaoMateria", ""),
                    "ementa": _resumir(m.get("Ementa", ""), 160),
                    "link": f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{m.get('CodigoMateria')}",
                }
                for m in materias[:MAX_MATERIAS]
            ],
            "total_materias": len(materias),
        })
    return sessoes


def _comissoes_senado(dia):
    dados = _get(f"{SENADO_DADOS}/comissao/agenda/{dia:%Y%m%d}.json", headers={"Accept": "application/json"}).json()
    reunioes = []
    for reuniao in _lista((dados.get("AgendaReuniao", {}).get("reunioes") or {}).get("reuniao")):
        if reuniao.get("isExibirNoPortal") == "false":
            continue
        colegiado = reuniao.get("colegiadoCriador") or {}
        reunioes.append({
            "hora": (reuniao.get("dataInicio") or "")[11:16],
            "sigla": colegiado.get("sigla", ""),
            "nome": colegiado.get("nome", ""),
            "titulo": reuniao.get("titulo", ""),
            "situacao": reuniao.get("situacao", ""),
            "link": reuniao.get("urlUltimaPautaSimplesPublicada") or "https://www25.senado.leg.br/web/atividade/agenda",
        })
    reunioes.sort(key=lambda r: r["hora"])
    return reunioes


def agenda_senado(hoje):
    for adiante in range(DIAS_A_FRENTE):
        dia = hoje + timedelta(days=adiante)
        plenario, comissoes = _sessoes_senado(dia), _comissoes_senado(dia)
        if plenario or comissoes:
            return {"data": dia.isoformat(), "plenario": plenario, "comissoes": comissoes,
                    "link": "https://www25.senado.leg.br/web/atividade/agenda"}
    return {"data": None, "plenario": [], "comissoes": [], "link": "https://www25.senado.leg.br/web/atividade/agenda"}


# --- Câmara dos Deputados: eventos do dia (dados abertos) ---

CAMARA_EVENTOS = "https://dadosabertos.camara.leg.br/api/v2/eventos"


def agenda_camara(hoje):
    for adiante in range(DIAS_A_FRENTE):
        dia = hoje + timedelta(days=adiante)
        dados = _get(CAMARA_EVENTOS, params={
            "dataInicio": dia.isoformat(), "dataFim": dia.isoformat(),
            "itens": 100, "ordem": "ASC", "ordenarPor": "dataHoraInicio",
        }, headers={"Accept": "application/json"}).json()["dados"]
        if not dados:
            continue
        eventos = []
        for evento in dados:
            orgao = (evento.get("orgaos") or [{}])[0]
            linhas = [l.strip() for l in (evento.get("descricao") or "").splitlines() if l.strip()]
            eventos.append({
                "hora": (evento.get("dataHoraInicio") or "")[11:16],
                "tipo": evento.get("descricaoTipo", ""),
                "orgao": orgao.get("sigla", ""),
                "nome_orgao": orgao.get("apelido") or orgao.get("nome", ""),
                "titulo": _resumir(linhas[0] if linhas else "", 160),
                "situacao": evento.get("situacao", ""),
                "link": f"https://www.camara.leg.br/evento-legislativo/{evento['id']}",
            })
        # As sessões do Plenário vêm primeiro; o resto por horário
        eventos.sort(key=lambda e: (e["orgao"] != "PLEN", e["hora"]))
        return {"data": dia.isoformat(), "eventos": eventos, "link": "https://www.camara.leg.br/agenda"}
    return {"data": None, "eventos": [], "link": "https://www.camara.leg.br/agenda"}


AGENDAS = {
    "stf": agenda_stf,
    "csmp": agenda_csmp,
    "presidente": agenda_presidente,
    "senado": agenda_senado,
    "camara": agenda_camara,
}


def coletar():
    """Busca as cinco agendas em paralelo. Uma agenda com falha vira None, sem derrubar as outras."""
    hoje = hoje_brasilia()
    with ThreadPoolExecutor(max_workers=len(AGENDAS)) as executor:
        futuros = {nome: executor.submit(funcao, hoje) for nome, funcao in AGENDAS.items()}

    dados = {"atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "hoje": hoje.isoformat()}
    falhas = []
    for nome, futuro in futuros.items():
        try:
            dados[nome] = futuro.result()
        except Exception as erro:
            print(f"[agendas] Falha na agenda {nome}: {erro}")
            dados[nome] = None
            falhas.append(nome)
    dados["falhas"] = falhas
    return dados


if __name__ == "__main__":
    import json
    print(json.dumps(coletar(), ensure_ascii=False, indent=1)[:6000])
