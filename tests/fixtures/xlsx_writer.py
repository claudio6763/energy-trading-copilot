"""Escritor XLSX minimo, so para os testes.

Gera um .xlsx valido com `sharedStrings`, numeros e strings inline, no mesmo
layout que Excel e openpyxl produzem. Serve para exercitar
`copilot.ingest.files.read_xlsx_bytes` sem instalar dependencia.

Limitacao declarada: como escritor e leitor sao nossos, o teste prova o
contrato do formato que implementamos, nao interoperabilidade com o Excel real.
Essa verificacao fica para o primeiro upload de arquivo de verdade.
"""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Sequence

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WB_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

_EXCEL_EPOCH = date(1899, 12, 30)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _column_letter(index: int) -> str:
    letras = ""
    index += 1
    while index > 0:
        index, resto = divmod(index - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


def date_to_serial(value: date) -> int:
    """Data -> serial do Excel (sistema 1900, com o bug de 1900)."""
    return (value - _EXCEL_EPOCH).days


def write_xlsx(rows: Sequence[Sequence[object]], *, sheet_name: str = "Planilha1") -> bytes:
    """Monta um XLSX em memoria. `rows[0]` e o cabecalho."""
    compartilhadas: list[str] = []
    indice: dict[str, int] = {}

    def id_string(texto: str) -> int:
        if texto not in indice:
            indice[texto] = len(compartilhadas)
            compartilhadas.append(texto)
        return indice[texto]

    linhas_xml: list[str] = []
    for numero, linha in enumerate(rows, start=1):
        celulas: list[str] = []
        for coluna, valor in enumerate(linha):
            ref = f"{_column_letter(coluna)}{numero}"
            if valor is None:
                continue
            if isinstance(valor, bool):
                celulas.append(f'<c r="{ref}" t="b"><v>{1 if valor else 0}</v></c>')
            elif isinstance(valor, (int, float, Decimal)):
                celulas.append(f'<c r="{ref}"><v>{valor}</v></c>')
            elif isinstance(valor, date):
                celulas.append(f'<c r="{ref}"><v>{date_to_serial(valor)}</v></c>')
            else:
                celulas.append(f'<c r="{ref}" t="s"><v>{id_string(str(valor))}</v></c>')
        linhas_xml.append(f'<row r="{numero}">{"".join(celulas)}</row>')

    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(linhas_xml)}</sheetData></worksheet>'
    )
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(compartilhadas)}" uniqueCount="{len(compartilhadas)}">'
        + "".join(f"<si><t>{_escape(s)}</t></si>" for s in compartilhadas)
        + "</sst>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", _WB_RELS)
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


__all__ = ["date_to_serial", "write_xlsx"]
