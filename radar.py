"""Radar de acontecimentos na comarca: o Claude resume cada fato e explica por que ele pode
pedir a atuação do Ministério Público.

As notícias da comarca que as palavras-chave de regional.RADAR ligam a alguma matéria são
mandadas ao Claude junto com a descrição da página da notícia. Ele descarta o que não pede
atuação (festa da prefeitura, inauguração) e, para o resto, devolve um resumo do fato, o
motivo e as matérias. Cada notícia é analisada uma vez só: a análise fica guardada no estado
regional e é reaproveitada nas execuções seguintes.

Precisa da variável ANTHROPIC_API_KEY (no GitHub, um "secret" do repositório). Sem ela, o
radar continua funcionando só com as palavras-chave.
"""

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

import coletor
import informativos

MODELO = "claude-opus-5-5"
_DESCRICAO = re.compile(r"""<meta[^>]+(?:property|name)=["'](?:og:description|description)["'][^>]*>""", re.I)
_CONTEUDO = re.compile(r"""content=["']([^"']*)["']""", re.I)

SISTEMA = """Você ajuda Promotores de Justiça do Ministério Público de Goiás a acompanhar o que acontece \
nas cidades da sua comarca. Recebe notícias locais e, para cada uma, decide se o fato pode exigir \
atuação do Ministério Público estadual (persecução penal, tutela coletiva, fiscalização do patrimônio \
público, infância, meio ambiente, consumidor, saúde, educação etc.).

Para cada notícia:
- pertinente: false quando o fato não pede atuação do MP (eventos, festas, inaugurações, homenagens, \
agenda política sem irregularidade, acidentes sem indício de crime ou omissão do poder público).
- resumo: o fato em uma ou duas frases, com suas palavras (não copie o título): o que aconteceu, onde e \
quem está envolvido, sem adjetivos.
- motivo: uma ou duas frases dizendo por que o fato pode exigir atuação do Promotor e qual (por exemplo: \
acompanhar o inquérito e oferecer denúncia; instaurar procedimento para apurar a omissão do município; \
verificar a situação da criança junto ao Conselho Tutelar). Não invente fatos que não estão na notícia.
- materias: as matérias das atribuições do MP a que o fato diz respeito, só da lista dada.
Se a notícia não for pertinente, deixe resumo e motivo vazios e materias como lista vazia."""


def _esquema():
    return {
        "type": "object",
        "properties": {
            "noticias": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "indice": {"type": "integer"},
                        "pertinente": {"type": "boolean"},
                        "resumo": {"type": "string"},
                        "motivo": {"type": "string"},
                        "materias": {"type": "array", "items": {"type": "string", "enum": informativos.TODAS_AS_MATERIAS}},
                    },
                    "required": ["indice", "pertinente", "resumo", "motivo", "materias"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["noticias"],
        "additionalProperties": False,
    }


def ativo():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _descricao(noticia):
    """A descrição da página da notícia (og:description), que conta mais que o título."""
    try:
        pagina = requests.get(coletor._link_real(noticia["link"]), headers=coletor.NAVEGADOR, timeout=10).text
        meta = _DESCRICAO.search(pagina)
        texto = meta and _CONTEUDO.search(meta.group(0))
        return html.unescape(texto.group(1)).strip()[:600] if texto else ""
    except Exception:
        return ""


def analisar(noticias, cidades):
    """{link: {"resumo", "motivo", "materias"}} ou {link: {"descartada": True}} para cada notícia."""
    if not noticias:
        return {}
    import anthropic

    with ThreadPoolExecutor(max_workers=8) as executor:
        descricoes = list(executor.map(_descricao, noticias))
    lista = "\n\n".join(
        f"[{i}] {n['titulo']}\nVeículo: {n['fonte']} · {n['data'][:10]}" + (f"\nDescrição: {d}" if d else "")
        for i, (n, d) in enumerate(zip(noticias, descricoes))
    )
    pedido = (f"Comarca: {', '.join(cidades)} (Goiás).\n"
              f"Matérias possíveis: {'; '.join(informativos.TODAS_AS_MATERIAS)}.\n\n"
              f"Notícias:\n\n{lista}")

    cliente = anthropic.Anthropic()
    resposta = cliente.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _esquema()}},
        system=SISTEMA,
        messages=[{"role": "user", "content": pedido}],
    )
    if resposta.stop_reason != "end_turn":
        raise RuntimeError(f"resposta incompleta do Claude ({resposta.stop_reason})")
    texto = next(b.text for b in resposta.content if b.type == "text")

    resultado = {}
    for item in json.loads(texto)["noticias"]:
        if not 0 <= item["indice"] < len(noticias):
            continue
        link = noticias[item["indice"]]["link"]
        if item["pertinente"] and item["resumo"] and item["materias"]:
            resultado[link] = {"resumo": item["resumo"], "motivo": item["motivo"], "materias": item["materias"]}
        else:
            resultado[link] = {"descartada": True}
    return resultado
