"""Leitura e validacao de CSV e XLSX."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from copilot.common.enums import DataQuality, Submarket, Unit
from copilot.common.errors import SchemaValidationError, UnsupportedFormatError
from copilot.ingest.files import (
    excel_serial_to_date,
    normalize_header,
    read_bytes,
    read_csv_bytes,
    read_xlsx_bytes,
)
from copilot.ingest.validation import (
    FORWARD_CURVE_SCHEMA,
    MANUAL_OBSERVATION_SCHEMA,
    ColumnSpec,
    parse_date,
    parse_decimal,
    validate_period_columns,
    validate_table,
)
from tests.fixtures.xlsx_writer import date_to_serial, write_xlsx

CSV_CURVA = (
    "tenor,delivery_start,delivery_end,price\n"
    "A+1,2027-01-01,2027-12-31,195.00\n"
    "A+2,2028-01-01,2028-12-31,188.50\n"
).encode("utf-8")


# ------------------------------------------------------------------ cabecalho
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Preço R$/MWh", "preco_r_mwh"),
        ("  Data Início  ", "data_inicio"),
        ("Submercado", "submercado"),
        ("TENOR", "tenor"),
        ("ação/atenção", "acao_atencao"),
    ],
)
def test_normalizacao_de_cabecalho(entrada: str, esperado: str) -> None:
    assert normalize_header(entrada) == esperado


# ------------------------------------------------------------------------ CSV
def test_csv_basico() -> None:
    tabela = read_csv_bytes(CSV_CURVA, source_name="curva.csv")
    assert tabela.columns == ("tenor", "delivery_start", "delivery_end", "price")
    assert len(tabela) == 2
    assert tabela.rows[0]["price"] == Decimal("195.00")


def test_csv_com_ponto_e_virgula_e_bom() -> None:
    payload = "﻿tenor;price\nA+1;195,00\n".encode("utf-8")
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    assert tabela.columns == ("tenor", "price")
    assert tabela.rows[0]["tenor"] == "A+1"


def test_csv_vazio_e_erro() -> None:
    with pytest.raises(SchemaValidationError, match="vazio"):
        read_csv_bytes(b"   ", source_name="x.csv")


def test_csv_com_coluna_duplicada() -> None:
    with pytest.raises(SchemaValidationError, match="duplicadas"):
        read_csv_bytes(b"tenor,tenor\nA,B\n", source_name="x.csv")


def test_csv_com_linha_maior_que_o_cabecalho() -> None:
    with pytest.raises(SchemaValidationError, match="campos"):
        read_csv_bytes(b"a,b\n1,2,3\n", source_name="x.csv")


def test_celula_vazia_vira_none_e_nao_zero() -> None:
    tabela = read_csv_bytes(b"a,b\n1,\n", source_name="x.csv")
    assert tabela.rows[0]["b"] is None


def test_require_columns() -> None:
    tabela = read_csv_bytes(CSV_CURVA, source_name="curva.csv")
    tabela.require_columns(["tenor", "price"])
    with pytest.raises(SchemaValidationError, match="ausentes"):
        tabela.require_columns(["submarket"])


# ----------------------------------------------------------------------- XLSX
def test_xlsx_com_strings_e_numeros() -> None:
    payload = write_xlsx(
        [
            ["tenor", "delivery_start", "delivery_end", "price"],
            ["A+1", date(2027, 1, 1), date(2027, 12, 31), Decimal("195.00")],
            ["A+2", date(2028, 1, 1), date(2028, 12, 31), Decimal("188.50")],
        ]
    )
    tabela = read_xlsx_bytes(payload, source_name="curva.xlsx")
    assert tabela.columns == ("tenor", "delivery_start", "delivery_end", "price")
    assert len(tabela) == 2
    assert tabela.rows[0]["tenor"] == "A+1"
    assert tabela.rows[1]["price"] == Decimal("188.50")


def test_xlsx_invalido() -> None:
    with pytest.raises(SchemaValidationError, match="XLSX valido"):
        read_xlsx_bytes(b"nao sou um zip", source_name="x.xlsx")


def test_xlsx_com_linhas_em_branco_sao_ignoradas() -> None:
    payload = write_xlsx([["a", "b"], [None, None], ["1", "2"]])
    tabela = read_xlsx_bytes(payload, source_name="x.xlsx")
    assert len(tabela) == 1


def test_serial_do_excel_vira_data() -> None:
    assert excel_serial_to_date(date_to_serial(date(2027, 3, 15))) == date(2027, 3, 15)
    assert excel_serial_to_date(1) == date(1899, 12, 31)


def test_serial_invalido() -> None:
    with pytest.raises(SchemaValidationError):
        excel_serial_to_date(0)


def test_despacho_por_extensao() -> None:
    assert len(read_bytes(CSV_CURVA, "curva.csv")) == 2
    payload = write_xlsx([["a"], ["1"]])
    assert len(read_bytes(payload, "curva.xlsx")) == 1
    with pytest.raises(UnsupportedFormatError, match="nao suportada"):
        read_bytes(b"x", "curva.pdf")


# ------------------------------------------------------------------ parsers
@pytest.mark.parametrize(
    "texto", ["2027-03-15", "15/03/2027", "15-03-2027", "2027/03/15"]
)
def test_formatos_de_data_aceitos(texto: str) -> None:
    assert parse_date(texto, field_name="d", row=2) == date(2027, 3, 15)


def test_data_irreconhecivel() -> None:
    with pytest.raises(SchemaValidationError, match="nao reconhecida"):
        parse_date("15 de marco", field_name="d", row=2)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("195.00", "195.00"),
        ("195,00", "195.00"),
        ("1.234,56", "1234.56"),
        ("1234.56", "1234.56"),
        ("R$ 1.234,56", "1234.56"),
    ],
)
def test_formatos_numericos_aceitos(texto: str, esperado: str) -> None:
    assert parse_decimal(texto, field_name="p", row=2) == Decimal(esperado)


def test_numero_invalido() -> None:
    with pytest.raises(SchemaValidationError, match="nao e numero"):
        parse_decimal("caro", field_name="p", row=2)


def test_booleano_em_campo_numerico() -> None:
    with pytest.raises(SchemaValidationError, match="booleano"):
        parse_decimal(True, field_name="p", row=2)


# --------------------------------------------------------------- validacao
def test_validacao_de_curva_completa() -> None:
    tabela = read_csv_bytes(CSV_CURVA, source_name="curva.csv")
    relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA)
    assert relatorio.ok
    linhas = relatorio.raise_if_invalid("curva.csv")
    assert linhas[0]["delivery_start"] == date(2027, 1, 1)
    assert linhas[0]["price"] == Decimal("195.00")
    assert linhas[0]["submarket"] is None  # opcional ausente vira None


def test_apelidos_em_portugues_funcionam() -> None:
    payload = (
        "produto;inicio;fim;preco;submercado\n"
        "A+1;01/01/2027;31/12/2027;195,00;SE/CO\n"
    ).encode("utf-8")
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    linhas = validate_table(tabela, FORWARD_CURVE_SCHEMA).raise_if_invalid("curva.csv")
    assert linhas[0]["tenor"] == "A+1"
    assert linhas[0]["submarket"] is Submarket.SE_CO


def test_coluna_obrigatoria_ausente_interrompe_tudo() -> None:
    tabela = read_csv_bytes(b"tenor,price\nA+1,195\n", source_name="curva.csv")
    with pytest.raises(SchemaValidationError, match="obrigatorias ausentes"):
        validate_table(tabela, FORWARD_CURVE_SCHEMA)


def test_campo_obrigatorio_vazio_nao_vira_zero() -> None:
    payload = b"tenor,delivery_start,delivery_end,price\nA+1,2027-01-01,2027-12-31,\n"
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA)
    assert not relatorio.ok
    assert any("nao vira zero" in i for i in relatorio.issues)
    assert relatorio.skipped_rows == 1


def test_preco_negativo_e_recusado() -> None:
    payload = b"tenor,delivery_start,delivery_end,price\nA+1,2027-01-01,2027-12-31,-5\n"
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA)
    assert any("abaixo do minimo" in i for i in relatorio.issues)


def test_enum_invalido_lista_os_aceitos() -> None:
    payload = (
        b"tenor,delivery_start,delivery_end,price,submarket\n"
        b"A+1,2027-01-01,2027-12-31,195,XX\n"
    )
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA)
    assert any("Aceitos" in i for i in relatorio.issues)


def test_periodo_invertido_e_detectado() -> None:
    linhas = [{"delivery_start": date(2027, 12, 31), "delivery_end": date(2027, 1, 1)}]
    problemas = validate_period_columns(linhas)
    assert problemas and "anterior" in problemas[0]


def test_validacao_de_observacao_manual() -> None:
    payload = (
        "metric_key,ref_date,value,unit,quality\n"
        "ear_sudeste_pct,2026-08-14,0.52,%,ESTIMADO\n"
    ).encode("utf-8")
    tabela = read_csv_bytes(payload, source_name="obs.csv")
    linhas = validate_table(tabela, MANUAL_OBSERVATION_SCHEMA).raise_if_invalid("obs.csv")
    assert linhas[0]["unit"] is Unit.PERCENT
    assert linhas[0]["quality"] is DataQuality.ESTIMADO


def test_validacao_acumula_ate_o_limite() -> None:
    linhas = "".join(f"A+{i},,,\n" for i in range(1, 40))
    payload = ("tenor,delivery_start,delivery_end,price\n" + linhas).encode("utf-8")
    tabela = read_csv_bytes(payload, source_name="curva.csv")
    relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA, stop_at=10)
    assert len(relatorio.issues) >= 10
    assert any("interrompido" in i for i in relatorio.issues)


def test_check_customizado() -> None:
    spec = (
        ColumnSpec("tenor", "text"),
        ColumnSpec(
            "price",
            "decimal",
            check=lambda v: "preco irrealista" if v > Decimal("5000") else None,
        ),
    )
    tabela = read_csv_bytes(b"tenor,price\nA+1,999999\n", source_name="x.csv")
    relatorio = validate_table(tabela, spec)
    assert any("irrealista" in i for i in relatorio.issues)
