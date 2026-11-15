"""Leitor mínimo de .xlsx (primeira planilha, só valores), sem dependências: zipfile + XML.

Serve às bases oficiais em Excel (SINESP VDE, IDEB do INEP), que são tabelas simples."""

import re
import zipfile
from xml.etree.ElementTree import iterparse

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _coluna(ref):
    """"C12" → 2 (índice da coluna, a partir de 0)."""
    n = 0
    for letra in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(letra) - 64
    return n - 1


def _textos(z):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    textos = []
    with z.open("xl/sharedStrings.xml") as f:
        for _, el in iterparse(f):
            if el.tag == _NS + "si":
                textos.append("".join(t.text or "" for t in el.iter(_NS + "t")))
                el.clear()
    return textos


def _planilha(z, indice):
    nomes = sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                   key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
    return nomes[indice]


def linhas(caminho, planilha=0):
    """Gera cada linha da planilha como lista de valores (str, float ou None)."""
    with zipfile.ZipFile(caminho) as z:
        textos = _textos(z)
        with z.open(_planilha(z, planilha)) as f:
            for _, el in iterparse(f):
                if el.tag != _NS + "row":
                    continue
                linha = []
                for c in el.iter(_NS + "c"):
                    i = _coluna(c.get("r")) if c.get("r") else len(linha)
                    linha.extend([None] * (i - len(linha) + 1))
                    v = c.find(_NS + "v")
                    tipo = c.get("t")
                    if tipo == "inlineStr":
                        valor = "".join(t.text or "" for t in c.iter(_NS + "t"))
                    elif v is None or v.text is None:
                        valor = None
                    elif tipo == "s":
                        valor = textos[int(v.text)]
                    elif tipo in ("str", "e"):
                        valor = v.text
                    elif tipo == "b":
                        valor = v.text == "1"
                    else:
                        try:
                            valor = float(v.text)
                        except ValueError:
                            valor = v.text
                    linha[i] = valor
                el.clear()
                yield linha
