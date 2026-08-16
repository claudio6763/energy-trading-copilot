"""Leitura de CSV e XLSX em stdlib puro.

Por que sem pandas/openpyxl: o arquivo que o trader sobe na defesa e o caminho
critico do RF-11 (registro ao vivo). Ele precisa funcionar num deploy minimo,
sem depender de roda binaria. `csv` e `zipfile` + `ElementTree` dao conta do
formato que interessa — planilha tabular com cabecalho na primeira linha.

Escopo declarado do leitor XLSX: primeira planilha (ou a nomeada), `sharedStrings`,
strings inline, numeros e booleanos. **Nao** interpreta formula (le o valor
cacheado), grafico, tabela dinamica nem formatacao. Data vem como serial
numerico e e convertida na camada de validacao, onde o tipo alvo e conhecido.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Sequence
from xml.etree import ElementTree as ET

from copilot.common.errors import SchemaValidationError, UnsupportedFormatError

CSV_EXTENSIONS = frozenset({".csv", ".txt", ".tsv"})
XLSX_EXTENSIONS = frozenset({".xlsx", ".xlsm"})

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")

#: Excel conta a partir de 1899-12-30 por causa do bug do ano bissexto de 1900
#: herdado do Lotus 1-2-3. Nao e engano: e o unico jeito de bater com o Excel.
_EXCEL_EPOCH = date(1899, 12, 30)


@dataclass(frozen=True, slots=True)
class Table:
    """Tabela lida de arquivo, com cabecalho normalizado."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    source_name: str
    sheet: str | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def require_columns(self, required: Sequence[str]) -> None:
        faltando = [c for c in required if c not in self.columns]
        if faltando:
            raise SchemaValidationError(
                f"{self.source_name}: colunas obrigatorias ausentes: {', '.join(faltando)}. "
                f"Encontradas: {', '.join(self.columns) or '(nenhuma)'}.",
                issues=[f"coluna ausente: {c}" for c in faltando],
            )


def normalize_header(name: str) -> str:
    """`Preço R$/MWh` -> `preco_r_mwh`. Deixa o cabecalho previsivel."""
    texto = (name or "").strip().lower()
    trocas = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e",
        "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ü": "u",
        "ç": "c",
    }
    for origem, destino in trocas.items():
        texto = texto.replace(origem, destino)
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")


def excel_serial_to_date(serial: Decimal | float | int) -> date:
    """Serial do Excel -> data. Sistema 1900, com o bug de 1900 preservado."""
    numero = int(Decimal(str(serial)))
    if numero <= 0:
        raise SchemaValidationError(f"Serial de data invalido: {serial}.")
    return _EXCEL_EPOCH + timedelta(days=numero)


def _column_index(ref: str) -> int:
    match = _CELL_REF.match(ref)
    if not match:  # pragma: no cover - celula sem referencia
        return 0
    letras = match.group(1)
    indice = 0
    for letra in letras:
        indice = indice * 26 + (ord(letra) - ord("A") + 1)
    return indice - 1


def _as_number(text: str) -> object:
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return text


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def read_csv_bytes(payload: bytes, *, source_name: str = "csv", delimiter: str | None = None) -> Table:
    """Le CSV/TSV. Detecta delimitador e BOM; nao adivinha tipo alem de numero."""
    try:
        texto = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = payload.decode("latin-1")

    if not texto.strip():
        raise SchemaValidationError(f"{source_name}: arquivo vazio.")

    if delimiter is None:
        primeira = texto.splitlines()[0]
        delimiter = max([",", ";", "\t", "|"], key=primeira.count)
        if primeira.count(delimiter) == 0:
            delimiter = ","

    leitor = csv.reader(io.StringIO(texto), delimiter=delimiter)
    linhas = [linha for linha in leitor if any((c or "").strip() for c in linha)]
    if not linhas:
        raise SchemaValidationError(f"{source_name}: sem linhas com conteudo.")

    cabecalho = [normalize_header(c) for c in linhas[0]]
    if len(set(cabecalho)) != len(cabecalho):
        duplicadas = sorted({c for c in cabecalho if cabecalho.count(c) > 1})
        raise SchemaValidationError(
            f"{source_name}: cabecalho com colunas duplicadas: {', '.join(duplicadas)}."
        )

    registros: list[dict[str, object]] = []
    for numero, linha in enumerate(linhas[1:], start=2):
        if len(linha) > len(cabecalho):
            raise SchemaValidationError(
                f"{source_name}: linha {numero} tem {len(linha)} campos para "
                f"{len(cabecalho)} colunas."
            )
        registro: dict[str, object] = {}
        for indice, coluna in enumerate(cabecalho):
            bruto = linha[indice].strip() if indice < len(linha) else ""
            registro[coluna] = _as_number(bruto) if bruto else None
        registros.append(registro)

    return Table(tuple(cabecalho), tuple(registros), source_name)


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    raiz = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    textos: list[str] = []
    for si in raiz.findall(f"{_NS}si"):
        partes = [no.text or "" for no in si.iter(f"{_NS}t")]
        textos.append("".join(partes))
    return textos


def _sheet_path(archive: zipfile.ZipFile, sheet: str | None) -> str:
    nomes = archive.namelist()
    if "xl/workbook.xml" in nomes:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        planilhas = workbook.findall(f"{_NS}sheets/{_NS}sheet")
        alvo = None
        if sheet is None:
            alvo = planilhas[0] if planilhas else None
        else:
            alvo = next((s for s in planilhas if s.get("name") == sheet), None)
            if alvo is None:
                disponiveis = ", ".join(s.get("name", "?") for s in planilhas)
                raise SchemaValidationError(
                    f"Planilha {sheet!r} nao encontrada. Disponiveis: {disponiveis}."
                )
        if alvo is not None:
            rid = alvo.get(f"{_DOC_REL_NS}id")
            if rid and "xl/_rels/workbook.xml.rels" in nomes:
                rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                for rel in rels.findall(f"{_REL_NS}Relationship"):
                    if rel.get("Id") == rid:
                        destino = rel.get("Target", "")
                        destino = destino[1:] if destino.startswith("/") else destino
                        caminho = destino if destino.startswith("xl/") else f"xl/{destino}"
                        if caminho in nomes:
                            return caminho
    candidatos = sorted(n for n in nomes if n.startswith("xl/worksheets/sheet"))
    if not candidatos:
        raise SchemaValidationError("Arquivo XLSX sem planilha legivel.")
    return candidatos[0]


def read_xlsx_bytes(
    payload: bytes, *, source_name: str = "xlsx", sheet: str | None = None
) -> Table:
    """Le a primeira planilha (ou a nomeada) de um XLSX."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SchemaValidationError(
            f"{source_name}: nao e um XLSX valido (arquivo zip corrompido)."
        ) from exc

    with archive:
        compartilhadas = _shared_strings(archive)
        caminho = _sheet_path(archive, sheet)
        raiz = ET.fromstring(archive.read(caminho))

        linhas_brutas: list[list[object]] = []
        for linha in raiz.iter(f"{_NS}row"):
            celulas: dict[int, object] = {}
            for celula in linha.findall(f"{_NS}c"):
                indice = _column_index(celula.get("r", ""))
                tipo = celula.get("t")
                if tipo == "inlineStr":
                    partes = [no.text or "" for no in celula.iter(f"{_NS}t")]
                    celulas[indice] = "".join(partes)
                    continue
                no_valor = celula.find(f"{_NS}v")
                if no_valor is None or no_valor.text is None:
                    continue
                bruto = no_valor.text
                if tipo == "s":
                    posicao = int(bruto)
                    celulas[indice] = (
                        compartilhadas[posicao] if posicao < len(compartilhadas) else ""
                    )
                elif tipo == "b":
                    celulas[indice] = bruto == "1"
                elif tipo == "e":
                    raise SchemaValidationError(
                        f"{source_name}: celula com erro de formula ({bruto}) em "
                        f"{celula.get('r')}. Corrija a planilha antes de subir."
                    )
                elif tipo == "str":
                    celulas[indice] = bruto
                else:
                    celulas[indice] = _as_number(bruto)
            if celulas:
                largura = max(celulas) + 1
                linhas_brutas.append([celulas.get(i) for i in range(largura)])

    if not linhas_brutas:
        raise SchemaValidationError(f"{source_name}: planilha sem linhas.")

    cabecalho = [normalize_header(str(c)) if c is not None else "" for c in linhas_brutas[0]]
    while cabecalho and not cabecalho[-1]:
        cabecalho.pop()
    if not cabecalho:
        raise SchemaValidationError(f"{source_name}: primeira linha sem cabecalho.")
    if len(set(cabecalho)) != len(cabecalho):
        duplicadas = sorted({c for c in cabecalho if cabecalho.count(c) > 1})
        raise SchemaValidationError(
            f"{source_name}: cabecalho com colunas duplicadas: {', '.join(duplicadas)}."
        )

    registros: list[dict[str, object]] = []
    for linha in linhas_brutas[1:]:
        if not any(v is not None and str(v).strip() != "" for v in linha):
            continue
        registro = {
            coluna: (linha[i] if i < len(linha) else None)
            for i, coluna in enumerate(cabecalho)
        }
        registros.append(registro)

    return Table(tuple(cabecalho), tuple(registros), source_name, sheet=sheet)


# ---------------------------------------------------------------------------
def read_table(
    path: str | Path, *, sheet: str | None = None, delimiter: str | None = None
) -> Table:
    """Le CSV ou XLSX pelo sufixo do arquivo."""
    caminho = Path(path)
    if not caminho.exists():
        raise SchemaValidationError(f"Arquivo nao encontrado: {caminho}")
    sufixo = caminho.suffix.lower()
    payload = caminho.read_bytes()
    if sufixo in CSV_EXTENSIONS:
        return read_csv_bytes(payload, source_name=caminho.name, delimiter=delimiter)
    if sufixo in XLSX_EXTENSIONS:
        return read_xlsx_bytes(payload, source_name=caminho.name, sheet=sheet)
    raise UnsupportedFormatError(
        f"Extensao {sufixo!r} nao suportada. Aceitos: "
        f"{', '.join(sorted(CSV_EXTENSIONS | XLSX_EXTENSIONS))}."
    )


def read_bytes(
    payload: bytes, filename: str, *, sheet: str | None = None
) -> Table:
    """Le a partir de bytes em memoria — o caminho do upload na UI."""
    sufixo = Path(filename).suffix.lower()
    if sufixo in CSV_EXTENSIONS:
        return read_csv_bytes(payload, source_name=filename)
    if sufixo in XLSX_EXTENSIONS:
        return read_xlsx_bytes(payload, source_name=filename, sheet=sheet)
    raise UnsupportedFormatError(f"Extensao {sufixo!r} nao suportada para {filename!r}.")


__all__ = [
    "CSV_EXTENSIONS",
    "Table",
    "XLSX_EXTENSIONS",
    "excel_serial_to_date",
    "normalize_header",
    "read_bytes",
    "read_csv_bytes",
    "read_table",
    "read_xlsx_bytes",
]
