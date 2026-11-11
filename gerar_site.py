"""Gera a versão estática do site em public/ (usada no Firebase Hosting).

Rode com: python gerar_site.py
"""

import json
import shutil
import sys
from pathlib import Path

from flask import render_template

import coletor
from app import app

RAIZ = Path(__file__).parent
SAIDA = RAIZ / "public"
MAXIMO_FALHAS = 0.5  # acima disso, não publica (o site anterior continua no ar)


def gravar_json(nome, dados):
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    (SAIDA / nome).write_text(texto, encoding="utf-8")


def main():
    dados = coletor.coletar()
    if len(dados["falhas"]) > MAXIMO_FALHAS * dados["feeds"] or not dados["noticias"]:
        # Sai com erro para o workflow não publicar um site quase vazio
        print(f"[gerar_site] {len(dados['falhas'])} de {dados['feeds']} feeds falharam")
        sys.exit(1)

    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    shutil.copytree(RAIZ / "static", SAIDA / "static")

    # O rewrite do firebase.json mapeia /api/noticias para este arquivo
    gravar_json("noticias.json", dados)

    with app.test_request_context():
        html = render_template("index.html")
    (SAIDA / "index.html").write_text(html, encoding="utf-8")

    print(f"[gerar_site] {len(dados['noticias'])} notícias; site gerado em {SAIDA}")


if __name__ == "__main__":
    main()
