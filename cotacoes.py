"""Coleta cotações diárias (em R$) e grava no SQLite. Copiado do Projeto Site Cotações."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

DB_PATH = Path(__file__).with_name("cotacoes.db")
DATA_INICIAL = date(2021, 1, 1)  # garante o filtro de 5 anos
TIMEOUT = 30

ATIVOS = {
    "USD": "Dólar",
    "EUR": "Euro",
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "TRX": "Tron",
    "USDT": "Tether",
}

# Séries do Banco Central (SGS): cotação de venda PTAX
SERIES_BCB = {"USD": 1, "EUR": 21619}

# Pares da Binance cotados diretamente em reais
PARES_BRL = {"BTC": "BTCBRL", "ETH": "ETHBRL", "USDT": "USDTBRL"}

# Endpoint público de dados de mercado da Binance: sem bloqueio por região
# (api.binance.com recusa IPs dos EUA, como os do GitHub Actions)
BINANCE_API = "https://data-api.binance.vision/api/v3/klines"


def conectar():
    return sqlite3.connect(DB_PATH)


def init_db():
    with conectar() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS cotacoes (
                   ativo TEXT NOT NULL,
                   data  TEXT NOT NULL,
                   valor REAL NOT NULL,
                   PRIMARY KEY (ativo, data)
               )"""
        )


def intervalo_salvo(ativo):
    """Retorna (primeira data, última data) salvas do ativo, ou (None, None)."""
    with conectar() as con:
        row = con.execute(
            "SELECT MIN(data), MAX(data) FROM cotacoes WHERE ativo = ?", (ativo,)
        ).fetchone()
    return tuple(date.fromisoformat(d) if d else None for d in row)


def salvar(ativo, registros):
    with conectar() as con:
        con.executemany(
            "INSERT OR REPLACE INTO cotacoes (ativo, data, valor) VALUES (?, ?, ?)",
            [(ativo, d, v) for d, v in registros],
        )


def buscar_bcb(serie, inicio, fim):
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
    params = {
        "formato": "json",
        "dataInicial": inicio.strftime("%d/%m/%Y"),
        "dataFinal": fim.strftime("%d/%m/%Y"),
    }
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    if resp.status_code == 404:  # sem dados no período (ex.: fim de semana)
        return []
    resp.raise_for_status()
    return [
        (datetime.strptime(item["data"], "%d/%m/%Y").date().isoformat(), float(item["valor"]))
        for item in resp.json()
    ]


def buscar_binance(par, inicio):
    """Fechamento diário (UTC) de um par da Binance a partir de `inicio`."""
    url = BINANCE_API
    inicio_ms = int(datetime(inicio.year, inicio.month, inicio.day, tzinfo=timezone.utc).timestamp() * 1000)
    registros = []
    while True:
        params = {"symbol": par, "interval": "1d", "startTime": inicio_ms, "limit": 1000}
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        velas = resp.json()
        for vela in velas:
            dia = datetime.fromtimestamp(vela[0] / 1000, tz=timezone.utc).date()
            registros.append((dia.isoformat(), float(vela[4])))
        if len(velas) < 1000:
            return registros
        inicio_ms = velas[-1][0] + 1


def buscar_trx(inicio):
    """Tron não tem par em BRL na Binance: TRX/USDT × USDT/BRL do mesmo dia."""
    usdt_brl = dict(buscar_binance("USDTBRL", inicio))
    return [
        (dia, preco * usdt_brl[dia])
        for dia, preco in buscar_binance("TRXUSDT", inicio)
        if dia in usdt_brl
    ]


# --- Cotações de hora em hora (últimas 24h), usadas só no filtro "1 dia" ---

# Yahoo Finance: não é a PTAX oficial, mas tem dados de hora em hora
SIMBOLOS_YAHOO = {"USD": "BRL=X", "EUR": "EURBRL=X"}
UMA_HORA = 60 * 60


def _hora_local(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _ultimas_24h(pontos):
    """Mantém só os pontos (timestamp, valor) das 24h anteriores ao mais recente."""
    if not pontos:
        return []
    limite = pontos[-1][0] - 24 * UMA_HORA
    return [(_hora_local(t), v) for t, v in pontos if t >= limite]


def buscar_yahoo_horario(simbolo):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}"
    params = {"interval": "60m", "range": "5d"}  # 5 dias para cobrir fins de semana
    resp = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    resultado = resp.json()["chart"]["result"][0]
    fechamentos = resultado["indicators"]["quote"][0]["close"]
    return [(t, v) for t, v in zip(resultado["timestamp"], fechamentos) if v is not None]


def buscar_binance_horario(par):
    """Velas de 1h da Binance como {abertura (s): preço de fechamento}."""
    url = BINANCE_API
    resp = requests.get(url, params={"symbol": par, "interval": "1h", "limit": 25}, timeout=TIMEOUT)
    resp.raise_for_status()
    return {v[0] / 1000: float(v[4]) for v in resp.json()}


def _fechamentos(velas):
    """Converte {abertura: preço} em [(momento do fechamento, preço)].
    A última vela ainda está aberta: o "fechamento" dela é o preço atual."""
    agora = datetime.now().timestamp()
    return [(min(abertura + UMA_HORA, agora), preco) for abertura, preco in sorted(velas.items())]


def buscar_intradia():
    """Retorna {ativo: {nome, datas, valores}} com as últimas 24h, de hora em hora."""
    dados = {}
    for ativo, nome in ATIVOS.items():
        try:
            if ativo in SIMBOLOS_YAHOO:
                pontos = buscar_yahoo_horario(SIMBOLOS_YAHOO[ativo])
            elif ativo == "TRX":
                usdt_brl = buscar_binance_horario("USDTBRL")
                pontos = _fechamentos({
                    abertura: preco * usdt_brl[abertura]
                    for abertura, preco in buscar_binance_horario("TRXUSDT").items()
                    if abertura in usdt_brl
                })
            else:
                pontos = _fechamentos(buscar_binance_horario(PARES_BRL[ativo]))
        except (requests.RequestException, KeyError, IndexError, TypeError) as erro:
            print(f"[coletor] Falha nas cotações horárias de {ativo}: {erro}")
            pontos = []
        registros = _ultimas_24h(pontos)
        dados[ativo] = {
            "nome": nome,
            "datas": [d for d, _ in registros],
            "valores": [v for _, v in registros],
        }
    return dados


def atualizar():
    """Busca os dados novos de cada ativo. Pode ser executada várias vezes sem duplicar."""
    init_db()
    hoje = date.today()
    resumo = {}
    for ativo in ATIVOS:
        primeira, ultima = intervalo_salvo(ativo)
        if primeira is None or primeira > DATA_INICIAL + timedelta(days=7):
            # Banco vazio ou começando depois de DATA_INICIAL: baixa o histórico todo
            # (a folga de 7 dias cobre feriados no início do ano, sem cotação do BCB)
            inicio = DATA_INICIAL
        else:
            # Recomeça pela última data salva para corrigir o valor parcial do dia
            inicio = ultima
        try:
            if ativo in SERIES_BCB:
                registros = buscar_bcb(SERIES_BCB[ativo], inicio, hoje)
            elif ativo == "TRX":
                registros = buscar_trx(inicio)
            else:
                registros = buscar_binance(PARES_BRL[ativo], inicio)
            salvar(ativo, registros)
            resumo[ativo] = len(registros)
        except requests.RequestException as erro:
            print(f"[coletor] Falha ao atualizar {ativo}: {erro}")
            resumo[ativo] = None
    return resumo


def carregar():
    """Retorna {ativo: {nome, datas, valores}} com o histórico completo."""
    init_db()
    dados = {a: {"nome": n, "datas": [], "valores": []} for a, n in ATIVOS.items()}
    with conectar() as con:
        for ativo, dia, valor in con.execute(
            "SELECT ativo, data, valor FROM cotacoes ORDER BY ativo, data"
        ):
            dados[ativo]["datas"].append(dia)
            dados[ativo]["valores"].append(valor)
    return dados


if __name__ == "__main__":
    print("Atualizando cotações...")
    atualizar()
    for ativo, info in carregar().items():
        if info["datas"]:
            print(
                f"{info['nome']:<9} {len(info['datas']):>4} registros  "
                f"{info['datas'][0]} a {info['datas'][-1]}  último: R$ {info['valores'][-1]:,.4f}"
            )
        else:
            print(f"{info['nome']:<9} sem dados")
