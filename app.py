"""Site com as principais notícias do Brasil e as cotações em R$. Rode com: python app.py"""

import threading
import time
from datetime import date

from flask import Flask, jsonify, render_template

import agendas
import coletor
import cotacoes

app = Flask(__name__)
app.json.sort_keys = False  # mantém a ordem: editorias, e dólar, euro, bitcoin...

CACHE_NOTICIAS_SEGUNDOS = 10 * 60
_cache_noticias = {"momento": 0.0, "dados": None}
_lock_noticias = threading.Lock()

CACHE_AGENDAS_SEGUNDOS = 10 * 60
_cache_agendas = {"momento": 0.0, "dados": None}
_lock_agendas = threading.Lock()

CACHE_INTRADIA_SEGUNDOS = 5 * 60
_cache_intradia = {"momento": 0.0, "dados": None}
_lock_intradia = threading.Lock()

_lock_cotacoes = threading.Lock()
_ultima_atualizacao = None


def noticias():
    """Busca os feeds no máximo a cada 10 minutos, sem execuções simultâneas."""
    with _lock_noticias:
        if time.time() - _cache_noticias["momento"] > CACHE_NOTICIAS_SEGUNDOS:
            _cache_noticias["dados"] = coletor.coletar()
            _cache_noticias["momento"] = time.time()
        return _cache_noticias["dados"]


def atualizar_cotacoes_se_preciso():
    """Atualiza o histórico de cotações no máximo uma vez por dia."""
    global _ultima_atualizacao
    if _ultima_atualizacao == date.today():
        return
    with _lock_cotacoes:
        if _ultima_atualizacao == date.today():
            return
        cotacoes.atualizar()
        _ultima_atualizacao = date.today()


def loop_diario():
    while True:
        try:
            atualizar_cotacoes_se_preciso()
        except Exception as erro:  # não deixa a thread morrer
            print(f"[app] Erro na atualização automática: {erro}")
        time.sleep(60 * 60)  # verifica a cada hora se o dia virou


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    """Alguns navegadores e leitores de favoritos pedem /favicon.ico direto."""
    return app.send_static_file("favicon-32.png")


@app.route("/api/noticias")
def api_noticias():
    return jsonify(noticias())


def carregar_agendas():
    """Agendas do STF, CSMP, Presidente, Senado e Câmara, no máximo a cada 10 minutos."""
    with _lock_agendas:
        if time.time() - _cache_agendas["momento"] > CACHE_AGENDAS_SEGUNDOS:
            _cache_agendas["dados"] = agendas.coletar()
            _cache_agendas["momento"] = time.time()
        return _cache_agendas["dados"]


@app.route("/api/agendas")
def api_agendas():
    return jsonify(carregar_agendas())


@app.route("/api/cotacoes")
def api_cotacoes():
    atualizar_cotacoes_se_preciso()
    return jsonify(cotacoes.carregar())


@app.route("/api/intradia")
def api_intradia():
    """Últimas 24h de hora em hora, com cache de 5 minutos."""
    with _lock_intradia:
        if time.time() - _cache_intradia["momento"] > CACHE_INTRADIA_SEGUNDOS:
            _cache_intradia["dados"] = cotacoes.buscar_intradia()
            _cache_intradia["momento"] = time.time()
        return jsonify(_cache_intradia["dados"])


if __name__ == "__main__":
    print("Buscando notícias e cotações (a primeira vez pode levar alguns segundos)...")
    noticias()
    atualizar_cotacoes_se_preciso()
    # As agendas levam alguns segundos (o CSMP lê PDFs): carregam em segundo plano
    threading.Thread(target=carregar_agendas, daemon=True).start()
    threading.Thread(target=loop_diario, daemon=True).start()
    print("Site no ar em http://localhost:5000")
    app.run(host="127.0.0.1", port=5000)
