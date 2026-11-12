"""Gera a versão estática do site em public/ (usada no Firebase Hosting).

Rode com: python gerar_site.py
"""

import json
import shutil
import sys
from pathlib import Path

from flask import render_template

import agendas
import coletor
import cotacoes
import regional
from app import app

RAIZ = Path(__file__).parent
SAIDA = RAIZ / "public"
MAXIMO_FALHAS = 0.5  # acima disso, não publica (o site anterior continua no ar)


def gravar_json(nome, dados):
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    (SAIDA / nome).write_text(texto, encoding="utf-8")


def main():
    dados = coletor.coletar()
    if len(dados["falhas"]) > MAXIMO_FALHAS * dados["feeds"] or not dados["total"]:
        # Sai com erro para o workflow não publicar um site quase vazio
        print(f"[gerar_site] {len(dados['falhas'])} de {dados['feeds']} feeds falharam")
        sys.exit(1)

    # Uma cotação com falha não impede a publicação: o site só não mostra aquele gráfico
    resumo = cotacoes.atualizar()
    falhas = [ativo for ativo, qtd in resumo.items() if qtd is None]
    if falhas:
        print(f"[gerar_site] Sem cotações de: {', '.join(falhas)}")

    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    shutil.copytree(RAIZ / "static", SAIDA / "static")

    # Os rewrites do firebase.json mapeiam /api/noticias, /api/agendas, /api/cotacoes e /api/intradia
    # para estes arquivos. Uma agenda com falha vai como null e o site mostra o aviso no lugar dela
    gravar_json("noticias.json", dados)
    gravar_json("agendas.json", agendas.coletar())
    gravar_json("cotacoes.json", cotacoes.carregar())
    gravar_json("intradia.json", cotacoes.buscar_intradia())

    # Notícias de cada cidade e região (uma parte por execução) e a lista de promotorias.
    # Se falhar, o site sai sem essa parte em vez de não sair
    try:
        regional.gerar(SAIDA)
    except Exception as erro:
        print(f"[gerar_site] Falha nas notícias por região: {erro}")

    with app.test_request_context():
        html = render_template("index.html")
    (SAIDA / "index.html").write_text(html, encoding="utf-8")

    print(f"[gerar_site] {dados['total']} notícias; site gerado em {SAIDA}")


if __name__ == "__main__":
    main()
