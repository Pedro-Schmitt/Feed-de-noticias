"""Indicadores dos municípios de Goiás para o retrato da comarca: violência (SINESP), saúde
(IBGE e CNES), população (IBGE) e o contorno de cada município (malha do IBGE), para o mapa.

As bases são oficiais e públicas, mas grandes e atualizadas mês a mês (SINESP) ou ano a ano;
por isso ficam numa cópia em dados/indicadores.json. Para atualizar:

    python indicadores.py --atualizar [--vde pasta com os bancovde-AAAA.xlsx]

Fontes:
- Violência: SINESP VDE, Dados Nacionais de Segurança Pública (Ministério da Justiça), um
  arquivo por ano. Por município, o SINESP publica os crimes contra a vida (homicídio doloso,
  feminicídio, latrocínio, lesão corporal seguida de morte e as tentativas), as mortes no
  trânsito, os suicídios e os mandados de prisão cumpridos; estupro, roubo e furto de veículo e
  tráfico de drogas saem só com o total do estado.
- Saúde: mortalidade infantil e internações por diarreia (IBGE Cidades, com dados do
  Ministério da Saúde) e leitos dos hospitais (CNES, API de dados abertos do Ministério da Saúde).
- População: estimativa do IBGE (tabela 6579 do SIDRA).
- Mapa: malha municipal do IBGE, na qualidade mínima.
"""

import json
import re
import sys
import tempfile
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests

import xlsx_simples

ARQUIVO = Path(__file__).parent / "dados" / "indicadores.json"
UF, CODIGO_UF = "GO", "52"
ANOS_VIOLENCIA = 5  # o ano corrente e os quatro anteriores

VDE = ("https://www.gov.br/mj/pt-br/assuntos/sua-seguranca/seguranca-publica/estatistica/download/"
       "dnsp-base-de-dados/bancovde-{ano}.xlsx/@@download/file")
IBGE_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/52/municipios"
IBGE_POPULACAO = ("https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324"
                  "?localidades=N6[N3[52]]|N3[52]")
IBGE_INDICADORES = "https://servicodados.ibge.gov.br/api/v1/pesquisas/indicadores/{ids}/resultados/{locais}"
IBGE_MALHA = ("https://servicodados.ibge.gov.br/api/v3/malhas/estados/52"
              "?intrarregiao=municipio&qualidade=minima&formato=application/vnd.geo%2Bjson")
LEITOS = "https://apidadosabertos.saude.gov.br/assistencia-a-saude/hospitais-e-leitos"
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}

# Eventos do SINESP publicados por município → nome curto na página
EVENTOS_MUNICIPIO = {
    "Homicídio doloso": "Homicídio doloso",
    "Feminicídio": "Feminicídio",
    "Roubo seguido de morte (latrocínio)": "Latrocínio",
    "Lesão corporal seguida de morte": "Lesão corporal seguida de morte",
    "Tentativa de homicídio": "Tentativa de homicídio",
    "Tentativa de feminicídio": "Tentativa de feminicídio",
    "Morte no trânsito ou em decorrência dele (exceto homicídio doloso)": "Mortes no trânsito",
    "Suicídio": "Suicídio",
    "Mandado de prisão cumprido": "Mandados de prisão cumpridos",
}
# Eventos que o SINESP só publica com o total do estado
EVENTOS_ESTADO = {
    "Estupro": "Estupro", "Estupro de vulnerável": "Estupro de vulnerável",
    "Roubo de veículo": "Roubo de veículo", "Furto de veículo": "Furto de veículo",
    "Tráfico de drogas": "Tráfico de drogas",
}
# Indicadores do IBGE Cidades
SAUDE_IBGE = {
    30279: ("mortalidade_infantil", "Mortalidade infantil", "óbitos por mil nascidos vivos"),
    60032: ("internacoes_diarreia", "Internações por diarreia", "por 100 mil habitantes"),
}


def _chave(nome):
    """"SÃO LUÍS DE MONTES BELOS" e "São Luís de Montes Belos" → "SAO LUIS DE MONTES BELOS"."""
    nome = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z ]+", " ", nome.upper().replace("'", "")).split())


def _get(url, **kw):
    resp = requests.get(url, timeout=kw.pop("timeout", 90), **kw)
    resp.raise_for_status()
    return resp


def _municipios():
    """{código IBGE de 7 dígitos: nome} dos municípios de Goiás."""
    return {str(m["id"]): m["nome"] for m in _get(IBGE_MUNICIPIOS).json()}


def _mes(serial):
    """Data do Excel (dias desde 30/12/1899) → "AAAA-MM"."""
    return (date(1899, 12, 30) + timedelta(days=int(serial))).strftime("%Y-%m")


def _violencia(pasta, municipios, pasta_local=None):
    """({nome: {evento: {mês: n}}}, {evento: {mês: n}} do estado, [meses com dados])."""
    por_chave = {_chave(n): n for n in municipios.values()}
    municipal, estadual, meses = {}, {}, set()
    hoje = date.today().year
    for ano in range(hoje - ANOS_VIOLENCIA + 1, hoje + 1):
        local = Path(pasta_local) / f"bancovde-{ano}.xlsx" if pasta_local else None
        if local and local.exists():
            caminho = local
        else:
            try:
                caminho = pasta / f"vde-{ano}.xlsx"
                with requests.get(VDE.format(ano=ano), headers=NAVEGADOR, stream=True, timeout=600) as resp:
                    resp.raise_for_status()
                    with open(caminho, "wb") as arquivo:
                        for parte in resp.iter_content(1 << 20):
                            arquivo.write(parte)
            except requests.RequestException as erro:
                print(f"[indicadores] SINESP {ano} indisponível: {type(erro).__name__}")
                continue
        linhas = 0
        for linha in xlsx_simples.linhas(caminho):
            if not linha or linha[0] != UF or not isinstance(linha[3], float):
                continue
            evento, mes = linha[2], _mes(linha[3])
            # total_vitima nos crimes contra a pessoa; total nas ocorrências (mandados, veículos)
            valor = next((linha[i] for i in (10, 11) if i < len(linha) and isinstance(linha[i], float)), 0)
            if evento in EVENTOS_MUNICIPIO:
                nome = por_chave.get(_chave(linha[1]))
                if not nome:
                    continue
                serie = municipal.setdefault(nome, {}).setdefault(EVENTOS_MUNICIPIO[evento], {})
                serie[mes] = serie.get(mes, 0) + valor
                meses.add(mes)
            elif evento in EVENTOS_ESTADO:
                serie = estadual.setdefault(EVENTOS_ESTADO[evento], {})
                serie[mes] = serie.get(mes, 0) + valor
            linhas += 1
        print(f"[indicadores] SINESP {ano}: {linhas} linhas de Goiás")
    return municipal, estadual, sorted(meses)


def _populacao(municipios):
    """({nome: população}, população de Goiás, ano da estimativa)."""
    dados = _get(IBGE_POPULACAO).json()[0]["resultados"][0]["series"]
    saida, estado, ano = {}, None, None
    for s in dados:
        ano, valor = next(iter(s["serie"].items()))
        if s["localidade"]["nivel"]["id"] == "N3":
            estado = int(valor)
        elif s["localidade"]["id"] in municipios:
            saida[municipios[s["localidade"]["id"]]] = int(valor)
    return saida, estado, int(ano)


def _saude_ibge(municipios):
    """{nome: {chave: {ano, valor}}} e o mesmo para Goiás, com o último ano de cada indicador."""
    por_codigo6 = {c[:6]: n for c, n in municipios.items()}
    codigos = list(municipios) + [CODIGO_UF]
    saida, estado = {}, {}
    for i in range(0, len(codigos), 60):
        url = IBGE_INDICADORES.format(ids="|".join(map(str, SAUDE_IBGE)), locais="|".join(codigos[i:i + 60]))
        for indicador in _get(url).json():
            chave = SAUDE_IBGE[indicador["id"]][0]
            for r in indicador["res"]:
                serie = {a: float(v) for a, v in r["res"].items() if v and re.fullmatch(r"-?[\d.]+", v)}
                if not serie:
                    continue
                ano = max(serie)
                valor = {"ano": int(ano), "valor": round(serie[ano], 2)}
                if r["localidade"] == CODIGO_UF:
                    estado[chave] = valor
                elif r["localidade"][:6] in por_codigo6:
                    saida.setdefault(por_codigo6[r["localidade"][:6]], {})[chave] = valor
    return saida, estado


def _leitos(municipios):
    """{nome: [hospitais com leitos]} do CNES (hospitais habilitados)."""
    por_chave = {_chave(n): n for n in municipios.values()}
    saida, vistos, pagina = {}, set(), 0
    while True:
        lista = _get(LEITOS, params={"uf": UF, "limit": 1000, "offset": pagina}).json()["hospitais_leitos"]
        for h in lista:
            nome = por_chave.get(_chave(h.get("nome_do_municipio_onde_fica_o_hospital")))
            chave = (nome, h.get("nome_do_hospital"), h.get("numero_do_cep_do_hospital"))
            if not nome or chave in vistos or h.get("motivo_da_desabilitacao_do_hospital,_caso_esteja_desabilitado"):
                continue
            vistos.add(chave)
            leitos = int(h.get("quantidade_total_de_leitos_do_hosptial") or 0)
            if not leitos:
                continue
            saida.setdefault(nome, []).append({
                "nome": _titulo(h["nome_do_hospital"]),
                "leitos": leitos,
                "sus": int(h.get("quantidade_total_de_leitos_sus_do_hosptial") or 0),
                "uti": int(h.get("quantidade_de_leitos_de_uti_do_hosptial") or 0),
                "uti_sus": int(h.get("quantidade_de_leitos_de_uti_sus_do_hosptial") or 0),
            })
        if len(lista) < 1000:
            break
        pagina += 1
    for lista in saida.values():
        lista.sort(key=lambda h: -h["leitos"])
    print(f"[indicadores] CNES: {len(vistos)} hospitais com leitos")
    return saida


def _titulo(texto):
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    siglas = {"UTI", "SUS", "HMI", "HUGO", "HGG", "CRER", "HC", "UFG", "IMEC", "UPA", "CAIS", "II", "III"}
    return " ".join(p if p in siglas else p.lower() if p.lower() in pequenas and i else p.capitalize()
                    for i, p in enumerate(re.sub(r"\s+", " ", texto or "").strip().split(" ")))


def _malha():
    """{código IBGE: geometria GeoJSON} com as coordenadas arredondadas (3 casas, ~100 m)."""
    def arredondar(c):
        return [round(c[0], 3), round(c[1], 3)] if isinstance(c[0], (int, float)) else [arredondar(x) for x in c]
    saida = {}
    for f in _get(IBGE_MALHA, timeout=180).json()["features"]:
        g = f["geometry"]
        saida[f["properties"]["codarea"]] = {"type": g["type"], "coordinates": arredondar(g["coordinates"])}
    return saida


def atualizar(pasta_vde=None):
    municipios = _municipios()
    with tempfile.TemporaryDirectory() as temp:
        municipal, estadual, meses = _violencia(Path(temp), municipios, pasta_vde)
    populacao, populacao_go, ano_pop = _populacao(municipios)
    saude, saude_go = _saude_ibge(municipios)
    # Para o estado, o IBGE dá as internações por diarreia em número absoluto; nos municípios, por 100 mil
    if "internacoes_diarreia" in saude_go and populacao_go:
        saude_go["internacoes_diarreia"]["valor"] = round(saude_go["internacoes_diarreia"]["valor"] / populacao_go * 100000, 1)
    leitos = _leitos(municipios)
    malha = _malha()

    def serie(eventos):
        return {e: [int(v.get(m, 0)) for m in meses] for e, v in sorted(eventos.items())}

    # Goiás: soma dos municípios nos eventos municipais; o total do estado nos demais
    soma_go = {}
    for eventos in municipal.values():
        for e, v in eventos.items():
            alvo = soma_go.setdefault(e, {})
            for m, n in v.items():
                alvo[m] = alvo.get(m, 0) + n
    leitos_go = [h for lista in leitos.values() for h in lista]
    por_municipio = {}
    for codigo, nome in sorted(municipios.items(), key=lambda x: x[1]):
        por_municipio[nome] = {
            "codigo": codigo,
            "populacao": populacao.get(nome),
            "geometria": malha.get(codigo),
            "violencia": serie(municipal.get(nome, {})),
            "saude": saude.get(nome, {}),
            "hospitais": leitos.get(nome, []),
        }
    dados = {
        "atualizado": date.today().isoformat(),
        "fontes": {
            "violencia": f"SINESP VDE, Dados Nacionais de Segurança Pública (Ministério da Justiça), {meses[0][:4]} a {meses[-1][:4]}"
                         if meses else "SINESP VDE (Ministério da Justiça)",
            "saude": "IBGE Cidades (Ministério da Saúde) e CNES",
            "populacao": f"Estimativa da população {ano_pop} (IBGE)",
        },
        "meses": meses,
        "saude_ibge": {chave: {"nome": nome, "unidade": unidade} for chave, nome, unidade in SAUDE_IBGE.values()},
        "goias": {
            "populacao": populacao_go,
            "violencia": serie(soma_go),
            "violencia_estado": {e: [int(v.get(m, 0)) for m in meses] for e, v in sorted(estadual.items())},
            "saude": saude_go,
            "leitos": sum(h["leitos"] for h in leitos_go),
            "leitos_sus": sum(h["sus"] for h in leitos_go),
            "uti_sus": sum(h["uti_sus"] for h in leitos_go),
        },
        "municipios": por_municipio,
    }
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[indicadores] {len(por_municipio)} municípios, {len(meses)} meses → {ARQUIVO} "
          f"({ARQUIVO.stat().st_size // 1024} KB)")


_cache = None


def carregar():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = None
    return _cache


def das_cidades(cidades):
    """Para o retrato da comarca: os indicadores de cada município e os de Goiás, para comparar."""
    dados = carregar()
    if not dados:
        return None
    return {
        "atualizado": dados["atualizado"],
        "fontes": dados["fontes"],
        "meses": dados["meses"],
        "saude_ibge": dados["saude_ibge"],
        "goias": dados["goias"],
        "municipios": {c: dados["municipios"][c] for c in cidades if c in dados["municipios"]},
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--atualizar" in sys.argv:
        atualizar(sys.argv[sys.argv.index("--vde") + 1] if "--vde" in sys.argv else None)
    else:
        for cidade in sys.argv[1:] or ["Ceres"]:
            m = (das_cidades([cidade]) or {}).get("municipios", {}).get(cidade)
            print(cidade, m and {k: (v if k != "geometria" else "…") for k, v in m.items()})
