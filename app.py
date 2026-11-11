"""Site com as principais notícias do Brasil. Rode com: python app.py"""

import threading
import time

from flask import Flask, jsonify, render_template

import coletor

app = Flask(__name__)
app.json.sort_keys = False  # mantém a ordem das categorias

CACHE_SEGUNDOS = 10 * 60
_cache = {"momento": 0.0, "dados": None}
_lock = threading.Lock()


def noticias():
    """Busca os feeds no máximo a cada 10 minutos, sem execuções simultâneas."""
    with _lock:
        if time.time() - _cache["momento"] > CACHE_SEGUNDOS:
            _cache["dados"] = coletor.coletar()
            _cache["momento"] = time.time()
        return _cache["dados"]


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


if __name__ == "__main__":
    print("Buscando notícias (leva alguns segundos)...")
    noticias()
    print("Site no ar em http://localhost:5000")
    app.run(host="127.0.0.1", port=5000)
