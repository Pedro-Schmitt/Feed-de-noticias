"""Instituições das cidades da comarca que merecem o acompanhamento do Promotor: escolas,
hospitais, UBS, CAPS, CRAS, CREAS, Centros POP, unidades prisionais, unidades de acolhimento e
centros-dia, cada tipo ligado às matérias de atribuição a que diz respeito.

As bases são oficiais e públicas, mas grandes e atualizadas uma ou duas vezes por ano; por isso
ficam numa cópia em dados/instituicoes.json, só com os municípios de Goiás. Para atualizar:

    python instituicoes.py --atualizar [--censo microdados_censo_escolar_AAAA.zip | --manter-escolas]

(o servidor do INEP às vezes manda a cadeia de certificados incompleta e o Python recusa a
conexão; nesse caso, baixe o .zip pelo navegador ou pelo curl e passe o caminho em --censo, ou
use --manter-escolas para atualizar o resto e reaproveitar as escolas da cópia atual)

Fontes:
- Escolas: Censo Escolar do INEP (microdados da educação básica), escolas em atividade.
- Hospitais, prontos-socorros, UBS e CAPS: CNES, pela API de dados abertos do Ministério da Saúde.
- Unidades prisionais: SISDEPEN (Senappen), estabelecimentos com cela física.
- Assistência social (CRAS, CREAS, Centro POP, centro-dia, acolhimento e família acolhedora):
  Censo SUAS (MDS), com endereço e telefone informados pelas próprias unidades.
"""

import csv
import io
import json
import re
import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import requests

ARQUIVO = Path(__file__).parent / "dados" / "instituicoes.json"
UF, CODIGO_UF = "GO", "52"

CENSO_ESCOLAR = "https://download.inep.gov.br/dados_abertos/microdados_censo_escolar_{ano}.zip"
CNES = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
SISDEPEN = ("https://www.gov.br/senappen/pt-br/servicos/sisdepen/bases-de-dados/2025/"
            "19o-ciclo-base-de-dados-2025-2-semestre.csv/@@download/file")
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/52/municipios"
CENSO_SUAS = "https://raw.githubusercontent.com/Sagicad-MDS/censo-suas-2024/main/Censo%20SUAS%202024/"
# Arquivo de cada unidade do Censo SUAS e a coluna do telefone (muda de um questionário para outro)
SUAS_ARQUIVOS = {
    "cras": ("1_CRAS/Censo_SUAS_2024_CRAS_Dados_Gerais.csv", "q0_12"),
    "creas": ("2_CREAS/Censo_SUAS_2024_CREAS_Dados_Gerais.csv", "q0_12"),
    "pop": ("3_CENTRO%20POP/Censo_SUAS_2024_Centro_POP_Dados_Gerais.csv", "q0_12"),
    "acolhimento": ("4%20-%20UNIDADE%20DE%20ACOLHIMENTO/Censo_SUAS_2024_Unidade_Acolhimento_Dados_Gerais.csv", "q0_12"),
    "centrodia": ("6_CENTRO%20DIA/Censo_SUAS_2024_Centro_Dia_Dados_Gerais.csv", "q0_11"),
    "familia": ("7_FAM%C3%8DLIA%20ACOLHEDORA/Censo_SUAS_2024_Familia_Acolhedora_Dados_Gerais.csv", "q0_12"),
}

# Tipos de instituição, na ordem em que aparecem, com as matérias de atribuição de cada um.
# "Cidadania" entra onde a promotoria do cidadão costuma atuar nas comarcas menores (saúde,
# educação, idosos, assistência social); "Criminal" leva às unidades prisionais porque, sem vara
# de execução própria, é a promotoria criminal que acompanha o presídio
TIPOS = [
    {"id": "escolas", "nome": "Escolas", "materias": ["Educação", "Infância e juventude", "Cidadania"]},
    {"id": "hospitais", "nome": "Hospitais e unidades de pronto atendimento", "materias": ["Saúde", "Cidadania"]},
    {"id": "ubs", "nome": "Unidades Básicas de Saúde (UBS)", "materias": ["Saúde", "Cidadania"]},
    {"id": "caps", "nome": "Centros de Atenção Psicossocial (CAPS)", "materias": ["Saúde", "Cidadania"]},
    {"id": "cras", "nome": "Centros de Referência de Assistência Social (CRAS)",
     "materias": ["Cidadania", "Infância e juventude", "Idoso e pessoa com deficiência"]},
    {"id": "creas", "nome": "Centros de Referência Especializados de Assistência Social (CREAS)",
     "materias": ["Cidadania", "Infância e juventude", "Idoso e pessoa com deficiência", "Violência doméstica"]},
    {"id": "pop", "nome": "Centros POP (população em situação de rua)", "materias": ["Cidadania"]},
    {"id": "prisionais", "nome": "Unidades prisionais",
     "materias": ["Execução penal", "Criminal", "Controle externo da atividade policial"]},
    {"id": "acolhimento", "nome": "Acolhimento de crianças e adolescentes", "materias": ["Infância e juventude"]},
    {"id": "idosos", "nome": "Acolhimento de idosos (ILPI) e de pessoas com deficiência",
     "materias": ["Idoso e pessoa com deficiência", "Cidadania"]},
    {"id": "centrodia", "nome": "Centros-dia (idosos e pessoas com deficiência)",
     "materias": ["Idoso e pessoa com deficiência", "Cidadania"]},
    {"id": "mulheres", "nome": "Acolhimento de mulheres em situação de violência",
     "materias": ["Violência doméstica", "Cidadania"]},
]

# Tipos de unidade do CNES
CNES_TIPOS = {
    1: ("ubs", "Posto de saúde"), 2: ("ubs", "Centro de saúde / UBS"),
    5: ("hospitais", "Hospital geral"), 7: ("hospitais", "Hospital especializado"),
    15: ("hospitais", "Unidade mista"), 20: ("hospitais", "Pronto-socorro geral"),
    21: ("hospitais", "Pronto-socorro especializado"), 62: ("hospitais", "Hospital-dia"),
    73: ("hospitais", "Pronto atendimento (UPA)"), 70: ("caps", "CAPS"),
}
DEPENDENCIA_ESCOLA = {"1": "Federal", "2": "Estadual", "3": "Municipal", "4": "Privada"}
PUBLICO_SUAS = [  # público atendido (Censo SUAS) → tipo
    (re.compile(r"crian|jovens egressos", re.I), "acolhimento"),
    (re.compile(r"idos|defici", re.I), "idosos"),
    (re.compile(r"mulheres", re.I), "mulheres"),
]

_MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "na", "no"}
_SIGLAS = {"UBS", "CAPS", "PSF", "ESF", "UPA", "CMEI", "CEI", "CEPI", "APAE", "AD", "II", "III", "IV", "SUS",
           "UTI", "CRAS", "CREAS", "ILPI", "CPP", "UPR", "CAIS", "HMI", "HUGO", "HGG", "CRER", "HC", "UFG", "IFG",
           "SESI", "SENAI", "SESC", "SENAC", "EJA", "CEJA", "CEU", "CIEP", "CPMG", "CEPMG", "EMEF", "VI", "VII", "VIII", "IX", "XI", "XII"}


def _nome(texto):
    """"ESCOLA MUNICIPAL SAO JOSE" → "Escola Municipal Sao Jose" (siglas continuam em maiúsculas)."""
    texto = re.sub(r"\s+", " ", texto or "").strip()
    if texto not in (texto.upper(), texto.lower()):  # já vem com maiúsculas e minúsculas
        return texto
    saida = []
    for i, p in enumerate(texto.split(" ")):
        if p in _SIGLAS:
            saida.append(p)
        elif p in _ABREVIACOES:
            saida.append(_ABREVIACOES[p])
        elif p.lower() in _MINUSCULAS and i:
            saida.append(p.lower())
        else:
            saida.append(p[:1].upper() + p[1:].lower())
    return " ".join(saida)


_ABREVIACOES = {"DR": "Dr.", "DRA": "Dra.", "PROF": "Prof.", "PROFA": "Profa.", "ESC": "Esc.", "MUN": "Mun.",
                "EST": "Est.", "COL": "Col.", "STA": "Sta.", "STO": "Sto.", "N": "n.", "SRA": "Sra."}


def _baixar(url, destino, timeout=600):
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as resp:
        resp.raise_for_status()
        with open(destino, "wb") as arquivo:
            for parte in resp.iter_content(1 << 20):
                arquivo.write(parte)
    return destino


def _escolas(pasta, zip_local=None):
    """(municípios {código IBGE de 7 dígitos: nome}, ano, {nome do município: [escolas]})."""
    anos = [] if zip_local else range(date.today().year, date.today().year - 4, -1)
    caminho, ano = zip_local, None
    for ano in anos:
        try:
            caminho = _baixar(CENSO_ESCOLAR.format(ano=ano), pasta / "censo.zip")
            break
        except requests.RequestException as erro:  # o ano que ainda não saiu dá 404 ou derruba a conexão
            print(f"[instituicoes] Censo Escolar {ano} indisponível: {type(erro).__name__}")
            continue
    else:
        if not zip_local:
            raise RuntimeError("microdados do Censo Escolar não encontrados")
    if zip_local:
        ano = int(re.search(r"(20\d\d)", Path(zip_local).name).group(1))
    print(f"[instituicoes] Censo Escolar {ano}")
    municipios, escolas = {}, {}
    with zipfile.ZipFile(caminho) as z:
        nome = next(n for n in z.namelist() if re.search(r"microdados_ed_basica_\d{4}\.csv$", n))
        with z.open(nome) as bruto:
            for linha in csv.DictReader(io.TextIOWrapper(bruto, encoding="cp1252"), delimiter=";"):
                if linha["SG_UF"] != UF:
                    continue
                municipios[linha["CO_MUNICIPIO"]] = linha["NO_MUNICIPIO"]
                if linha["TP_SITUACAO_FUNCIONAMENTO"] != "1":  # 1 = em atividade
                    continue
                matriculas = int(linha["QT_MAT_BAS"] or 0)
                detalhe = [DEPENDENCIA_ESCOLA.get(linha["TP_DEPENDENCIA"], ""),
                           f"{matriculas} matrículas" if matriculas else "",
                           "zona rural" if linha["TP_LOCALIZACAO"] == "2" else _nome(linha["NO_BAIRRO"])]
                escolas.setdefault(linha["NO_MUNICIPIO"], []).append(
                    {"nome": _nome(linha["NO_ENTIDADE"]), "detalhe": " · ".join(d for d in detalhe if d),
                     "ordem": -matriculas})
    return municipios, ano, escolas


def _cnes(municipios):
    """{nome do município: {"hospitais"|"ubs"|"caps": [unidades]}} pela API do CNES."""
    por_codigo6 = {codigo[:6]: nome for codigo, nome in municipios.items()}
    saida = {}
    for tipo, (grupo, descricao) in CNES_TIPOS.items():
        pagina = 0
        while True:
            resp = requests.get(CNES, params={"codigo_uf": CODIGO_UF, "codigo_tipo_unidade": tipo,
                                              "limit": 20, "offset": pagina}, timeout=60)
            resp.raise_for_status()
            lista = resp.json()["estabelecimentos"]
            for e in lista:
                municipio = por_codigo6.get(str(e["codigo_municipio"]))
                if not municipio or e.get("codigo_motivo_desabilitacao_estabelecimento"):
                    continue
                # A natureza jurídica diz quem mantém a unidade: 1xxx administração pública, 2xxx empresa,
                # 3xxx entidade sem fins lucrativos (a "esfera" do CNES vem quase sempre como municipal)
                natureza = str(e.get("descricao_natureza_juridica_estabelecimento") or "")[:1]
                mantenedor = {"1": "Público", "2": "Privado", "3": "Filantrópico"}.get(natureza, "")
                # UBS e CAPS são serviço público: os "centros de saúde" de empresas e consultórios ficam de fora
                if grupo != "hospitais" and natureza != "1":
                    continue
                sus = "atende pelo SUS" if grupo == "hospitais" and e.get("estabelecimento_faz_atendimento_ambulatorial_sus") == "SIM" else ""
                detalhe = [descricao if grupo == "hospitais" else "", mantenedor if grupo == "hospitais" else "", sus,
                           _nome(e.get("bairro_estabelecimento") or "")]
                saida.setdefault(municipio, {}).setdefault(grupo, []).append({
                    "nome": _nome(e.get("nome_fantasia") or e.get("nome_razao_social")),
                    "detalhe": " · ".join(d for d in detalhe if d),
                    "ordem": 0 if e.get("estabelecimento_possui_atendimento_hospitalar") else 1,
                })
            if len(lista) < 20:
                break
            pagina += 1
        print(f"[instituicoes] CNES tipo {tipo} ({descricao}): {pagina * 20 + len(lista)}")
    return saida


def _numero(texto):
    try:
        return int(float(texto or 0))
    except ValueError:
        return 0


def _prisionais(pasta, municipios):
    caminho = _baixar(SISDEPEN, pasta / "sisdepen.csv")
    leitor = csv.reader(io.StringIO(caminho.read_text(encoding="utf-8-sig")), delimiter=";")
    cabecalho = next(leitor)
    col = {nome: i for i, nome in enumerate(cabecalho)}
    capacidade = [i for i, c in enumerate(cabecalho) if c.startswith("1.3 Capacidade") and c.endswith("| Total")]
    populacao = [i for i, c in enumerate(cabecalho) if c.startswith("4.1 População prisional") and c.endswith("| Total")]
    saida = {}
    for linha in leitor:
        if len(linha) < len(cabecalho) or linha[col["UF"]] != UF or linha[col["Tipo do Estabelecimento"]] != "Cela física":
            continue
        if linha[col["Situação do Estabelecimento"]] != "Ativo":
            continue
        municipio = municipios.get(str(_numero(linha[col["Código IBGE"]])), linha[col["Município"]])
        vagas = sum(_numero(linha[i]) for i in capacidade)
        presos = sum(_numero(linha[i]) for i in populacao)
        detalhe = [f"{vagas} vagas" if vagas else "", f"{presos} presos" if presos else ""]
        saida.setdefault(municipio, []).append({"nome": linha[col["Nome do Estabelecimento"]].strip(),
                                                "detalhe": " · ".join(d for d in detalhe if d), "ordem": -presos})
    return saida


def _endereco(linha, coluna_telefone):
    """(endereço, telefone) de uma unidade do Censo SUAS."""
    tipo = linha.get("q0_2", "").strip()
    tipo = "" if tipo.isdigit() else tipo  # no CREAS o tipo de logradouro vem como código
    rua = _nome(linha.get("q0_3", ""))
    if rua and tipo and not rua.lower().startswith(tipo.lower()):
        rua = f"{tipo} {rua}"
    numero = linha.get("q0_4", "").strip()
    numero = "s/n" if numero.lower() in {"", "0", "sn", "s/n"} else numero
    bairro = _nome(linha.get("q0_6", ""))
    endereco = ", ".join(p for p in [rua, numero if rua else "", bairro] if p)
    telefone = re.sub(r"\s+", " ", linha.get(coluna_telefone, "")).strip()
    return endereco, telefone if re.search(r"\d{4}", telefone) else ""


# Nomes que não identificam a unidade ("Unidade de Acolhimento", "CREAS")
_GENERICO = re.compile(r"^(unidade de acolhimento|creas|cras|centro pop|creas pop|centro-dia e similares)$", re.I)
_PREFIXO = re.compile(r"^(unidade de acolhimento|centro-dia e similares)\s*[-–:]?\s*(?=\S)", re.I)


def _suas_linhas(pasta, arquivo):
    caminho = _baixar(CENSO_SUAS + arquivo, pasta / arquivo.rsplit("/", 1)[-1])
    return csv.DictReader(io.StringIO(caminho.read_text(encoding="cp1252")), delimiter=";")


def _assistencia(pasta, municipios):
    """{nome do município: {tipo: [unidades]}} do Censo SUAS: CRAS, CREAS, Centro POP, acolhimento
    (por público atendido), centro-dia e família acolhedora."""
    por_codigo6 = {codigo[:6]: nome for codigo, nome in municipios.items()}
    saida = {}
    for arquivo_id, (arquivo, coluna_telefone) in SUAS_ARQUIVOS.items():
        quantos = 0
        for linha in _suas_linhas(pasta, arquivo):
            municipio = por_codigo6.get(linha["IBGE"][:6])
            if not municipio:
                continue
            nome_bruto = _nome(linha["q0_1"])
            nome = _PREFIXO.sub("", nome_bruto) or nome_bruto
            detalhe = []
            grupo = arquivo_id
            if arquivo_id == "acolhimento":
                publico = linha["q1_1"].strip()
                grupo = next((g for padrao, g in PUBLICO_SUAS if padrao.search(publico)), None)
                if not grupo:
                    continue
                modalidade = linha["q1_2"].strip()
                natureza = linha.get("q3", "").strip()
                natureza = "Não governamental" if natureza.lower().startswith("n") else "Governamental" if natureza else ""
                if _GENERICO.match(nome):  # o Censo traz só "Unidade de Acolhimento": vale o tipo de serviço
                    ilpi = re.search(r"\((Institui[^)]*?)(?: - ILPI)?\)", modalidade)
                    nome = (f"{ilpi.group(1)} (ILPI)" if ilpi
                            else f"{re.sub(r' *[(].*', '', modalidade)} ({publico.lower().replace(' / ', ' e ')})")
                    modalidade = "" if ilpi else modalidade
                detalhe = [modalidade if modalidade and modalidade[:12] not in nome else "",
                           publico if grupo == "idosos" else "", natureza]
            elif arquivo_id == "familia":
                grupo = "acolhimento"
                if _GENERICO.match(nome):
                    nome = "Serviço de Família Acolhedora"
                detalhe = ["Família acolhedora", linha.get("q1", "").strip()]
            else:
                if arquivo_id == "cras":
                    detalhe = [linha.get("q1", "").strip()]  # "3.500 famílias referenciadas"
                if _GENERICO.match(nome):
                    nome = f"{nome.upper() if ' ' not in nome else nome} de {municipio}"
            endereco, telefone = _endereco(linha, coluna_telefone)
            saida.setdefault(municipio, {}).setdefault(grupo, []).append({
                "nome": nome[:1].upper() + nome[1:], "detalhe": " · ".join(d for d in detalhe if d),
                "endereco": endereco, "telefone": telefone, "ordem": 0})
            quantos += 1
        print(f"[instituicoes] Censo SUAS {arquivo_id}: {quantos}")
    return saida


def _municipios():
    """{código IBGE de 7 dígitos: nome} dos municípios de Goiás."""
    resp = requests.get(IBGE_MUNICIPIOS, timeout=60)
    resp.raise_for_status()
    return {str(m["id"]): m["nome"] for m in resp.json()}


def atualizar(zip_censo=None, manter_escolas=False):
    anterior = carregar()
    with tempfile.TemporaryDirectory() as temp:
        pasta = Path(temp)
        municipios = _municipios()
        if manter_escolas:
            escolas = {m: g.get("escolas", []) for m, g in anterior["municipios"].items()}
            fonte_escolas = anterior["fontes"]["escolas"]
        else:
            _, ano_escolar, escolas = _escolas(pasta, zip_censo)
            fonte_escolas = f"Censo Escolar {ano_escolar} (INEP)"
        saude = _cnes(municipios)
        prisionais = _prisionais(pasta, municipios)
        acolhimento = _assistencia(pasta, municipios)

    por_municipio = {}
    for nome in sorted(set(municipios.values())):
        grupos = {"escolas": escolas.get(nome, []), **saude.get(nome, {}),
                  "prisionais": prisionais.get(nome, []), **acolhimento.get(nome, {})}
        limpo = {}
        for grupo, itens in grupos.items():
            if itens:
                if all("ordem" in i for i in itens):  # as escolas reaproveitadas já vêm em ordem
                    itens.sort(key=lambda i: (i["ordem"], i["nome"]))
                limpo[grupo] = [{k: v for k, v in i.items() if k != "ordem" and v} for i in itens]
        por_municipio[nome] = limpo
    dados = {
        "atualizado": date.today().isoformat(),
        "fontes": {
            "escolas": fonte_escolas,
            "saude": "CNES (Ministério da Saúde)",
            "prisionais": "SISDEPEN, 2º semestre de 2025 (Senappen)",
            "assistencia": "Censo SUAS 2024 (MDS)",
        },
        "municipios": por_municipio,
    }
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total = sum(len(i) for m in por_municipio.values() for i in m.values())
    print(f"[instituicoes] {total} instituições em {len(por_municipio)} municípios → {ARQUIVO}")


_cache = None


def carregar():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {"municipios": {}, "fontes": {}}
    return _cache


def das_cidades(cidades):
    """Para o quadro da comarca: tipos, fontes e as instituições de cada município."""
    dados = carregar()
    return {
        "tipos": TIPOS,
        "fontes": dados.get("fontes", {}),
        "municipios": {c: dados["municipios"].get(c, {}) for c in cidades},
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--atualizar" in sys.argv:
        censo = sys.argv[sys.argv.index("--censo") + 1] if "--censo" in sys.argv else None
        atualizar(censo, "--manter-escolas" in sys.argv)
    else:
        for cidade in sys.argv[1:] or ["Ceres"]:
            for grupo, itens in das_cidades([cidade])["municipios"][cidade].items():
                print(f"{cidade} · {grupo}: {len(itens)} — {', '.join(i['nome'] for i in itens[:4])}")
