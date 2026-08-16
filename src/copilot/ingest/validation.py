"""Validacao de schema e coercao de tipos na ingestao.

Um arquivo so vira dado depois de passar por aqui. A validacao e **estrita e
posicional**: cada erro carrega numero da linha e nome da coluna, para que o
trader corrija a planilha em vez de adivinhar.

Regra que atravessa o modulo: *dado ausente nunca vira zero*. Campo obrigatorio
vazio e erro; campo opcional vazio e `None`; nenhum dos dois e `0`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Sequence

from copilot.common.enums import DataQuality, Submarket, Unit
from copilot.common.errors import SchemaValidationError
from copilot.ingest.files import Table, excel_serial_to_date

#: Formatos de data aceitos, em ordem de tentativa. ISO primeiro.
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y")


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Especificacao de uma coluna esperada."""

    name: str
    kind: str  # "date" | "decimal" | "text" | "enum" | "int" | "bool"
    required: bool = True
    enum_cls: type | None = None
    aliases: tuple[str, ...] = ()
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    #: Validacao adicional especifica do dominio.
    check: Callable[[object], str | None] | None = None


@dataclass
class ValidationReport:
    """Resultado da validacao. `rows` so e confiavel se `ok` for verdadeiro."""

    rows: list[dict[str, object]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    skipped_rows: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues

    def raise_if_invalid(self, source_name: str) -> list[dict[str, object]]:
        if self.issues:
            raise SchemaValidationError(
                f"{source_name}: {len(self.issues)} problema(s) de validacao. "
                "Nada foi ingerido.",
                issues=self.issues,
            )
        return self.rows


def parse_date(value: object, *, field_name: str, row: int) -> date:
    """Aceita ISO, formatos brasileiros e serial do Excel."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, Decimal) or isinstance(value, (int, float)):
        return excel_serial_to_date(Decimal(str(value)))
    texto = str(value).strip()
    if not texto:
        raise SchemaValidationError(f"linha {row}, {field_name}: data vazia.")
    for formato in DATE_FORMATS:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise SchemaValidationError(
        f"linha {row}, {field_name}: data {texto!r} nao reconhecida. "
        f"Formatos aceitos: {', '.join(DATE_FORMATS)}."
    )


def parse_decimal(value: object, *, field_name: str, row: int) -> Decimal:
    """Aceita `1.234,56` e `1234.56`. Nunca aceita `float` cru sem conversao."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise SchemaValidationError(f"linha {row}, {field_name}: booleano em campo numerico.")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    texto = str(value).strip().replace(" ", "").replace("R$", "")
    if not texto:
        raise SchemaValidationError(f"linha {row}, {field_name}: numero vazio.")
    if "," in texto and "." in texto:
        # 1.234,56 -> 1234.56
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except InvalidOperation as exc:
        raise SchemaValidationError(
            f"linha {row}, {field_name}: {value!r} nao e numero valido."
        ) from exc


def _coerce(spec: ColumnSpec, value: object, row: int) -> object:
    nome = spec.name
    if spec.kind == "date":
        return parse_date(value, field_name=nome, row=row)
    if spec.kind == "decimal":
        numero = parse_decimal(value, field_name=nome, row=row)
        if spec.min_value is not None and numero < spec.min_value:
            raise SchemaValidationError(
                f"linha {row}, {nome}: {numero} abaixo do minimo {spec.min_value}."
            )
        if spec.max_value is not None and numero > spec.max_value:
            raise SchemaValidationError(
                f"linha {row}, {nome}: {numero} acima do maximo {spec.max_value}."
            )
        return numero
    if spec.kind == "int":
        return int(parse_decimal(value, field_name=nome, row=row))
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "sim", "s", "yes", "y", "verdadeiro"}
    if spec.kind == "enum":
        if spec.enum_cls is None:  # pragma: no cover - erro de programacao
            raise SchemaValidationError(f"{nome}: coluna enum sem classe declarada.")
        texto = str(value).strip()
        aceitos = {m.value: m for m in spec.enum_cls}
        aceitos.update({m.value.upper(): m for m in spec.enum_cls})
        aceitos.update({m.name: m for m in spec.enum_cls})
        if texto in aceitos:
            return aceitos[texto]
        if texto.upper() in aceitos:
            return aceitos[texto.upper()]
        raise SchemaValidationError(
            f"linha {row}, {nome}: {texto!r} invalido. "
            f"Aceitos: {', '.join(sorted(m.value for m in spec.enum_cls))}."
        )
    return str(value).strip()


def validate_table(
    table: Table,
    specs: Sequence[ColumnSpec],
    *,
    stop_at: int = 50,
) -> ValidationReport:
    """Valida e coage a tabela inteira. Acumula erros ate `stop_at`."""
    mapa: dict[str, str] = {}
    for spec in specs:
        candidatos = (spec.name, *spec.aliases)
        encontrada = next((c for c in candidatos if c in table.columns), None)
        if encontrada is None:
            if spec.required:
                mapa[spec.name] = ""
        else:
            mapa[spec.name] = encontrada

    faltando = [s.name for s in specs if s.required and not mapa.get(s.name)]
    if faltando:
        raise SchemaValidationError(
            f"{table.source_name}: colunas obrigatorias ausentes: {', '.join(faltando)}. "
            f"Encontradas: {', '.join(table.columns) or '(nenhuma)'}.",
            issues=[f"coluna ausente: {c}" for c in faltando],
        )

    relatorio = ValidationReport()
    for numero, bruta in enumerate(table.rows, start=2):
        registro: dict[str, object] = {}
        erro_na_linha = False
        for spec in specs:
            coluna = mapa.get(spec.name)
            valor = bruta.get(coluna) if coluna else None
            vazio = valor is None or (isinstance(valor, str) and not valor.strip())
            if vazio:
                if spec.required:
                    relatorio.issues.append(
                        f"linha {numero}, {spec.name}: obrigatorio e veio vazio "
                        "(ausencia nao vira zero)."
                    )
                    erro_na_linha = True
                else:
                    registro[spec.name] = None
                continue
            try:
                convertido = _coerce(spec, valor, numero)
            except SchemaValidationError as exc:
                relatorio.issues.append(str(exc))
                erro_na_linha = True
                continue
            if spec.check is not None:
                problema = spec.check(convertido)
                if problema:
                    relatorio.issues.append(f"linha {numero}, {spec.name}: {problema}")
                    erro_na_linha = True
                    continue
            registro[spec.name] = convertido

        if erro_na_linha:
            relatorio.skipped_rows += 1
        else:
            relatorio.rows.append(registro)
        if len(relatorio.issues) >= stop_at:
            relatorio.issues.append(
                f"... interrompido em {stop_at} problemas. Corrija e reenvie."
            )
            break

    if not relatorio.rows and not relatorio.issues:
        relatorio.issues.append(f"{table.source_name}: nenhuma linha de dados.")
    return relatorio


# ---------------------------------------------------------------------------
# Schemas dos uploads suportados
# ---------------------------------------------------------------------------

#: Curva forward: um ponto (tenor) por linha.
FORWARD_CURVE_SCHEMA: tuple[ColumnSpec, ...] = (
    ColumnSpec("tenor", "text", aliases=("tenor_label", "produto", "vencimento")),
    ColumnSpec("delivery_start", "date", aliases=("inicio", "inicio_entrega", "data_inicio")),
    ColumnSpec("delivery_end", "date", aliases=("fim", "fim_entrega", "data_fim")),
    ColumnSpec(
        "price",
        "decimal",
        aliases=("preco", "preco_r_mwh", "preco_rs_mwh", "valor"),
        min_value=Decimal("0"),
        max_value=Decimal("100000"),
    ),
    ColumnSpec("submarket", "enum", required=False, enum_cls=Submarket, aliases=("submercado",)),
    ColumnSpec("quality", "enum", required=False, enum_cls=DataQuality, aliases=("qualidade",)),
)

#: Curva licenciada importada manualmente (Dcide e afins) — schema fixo do
#: prompt de integracoes secao 12. Uma linha por ponto de curva.
LICENSED_CURVE_SCHEMA: tuple[ColumnSpec, ...] = (
    ColumnSpec("reference_date", "date", aliases=("data_referencia", "as_of")),
    ColumnSpec("delivery_start", "date", aliases=("inicio_entrega",)),
    ColumnSpec("delivery_end", "date", aliases=("fim_entrega",)),
    ColumnSpec("submarket", "enum", enum_cls=Submarket, aliases=("submercado",)),
    ColumnSpec("energy_type", "text", aliases=("tipo_energia", "energy_source")),
    ColumnSpec("product", "text", aliases=("produto",)),
    ColumnSpec(
        "price_brl_mwh", "decimal", aliases=("preco", "price"),
        min_value=Decimal("0"), max_value=Decimal("100000"),
    ),
    ColumnSpec("source", "text", aliases=("fonte",)),
    ColumnSpec("curve_type", "text", aliases=("tipo_curva",)),
)

#: Observacao manual de metrica: uma leitura por linha.
MANUAL_OBSERVATION_SCHEMA: tuple[ColumnSpec, ...] = (
    ColumnSpec("metric_key", "text", aliases=("metrica", "serie", "chave")),
    ColumnSpec("ref_date", "date", aliases=("data", "data_referencia", "competencia")),
    ColumnSpec("value", "decimal", aliases=("valor", "leitura")),
    ColumnSpec("unit", "enum", enum_cls=Unit, aliases=("unidade",)),
    ColumnSpec("as_of", "date", required=False, aliases=("data_base", "publicado_em")),
    ColumnSpec("quality", "enum", required=False, enum_cls=DataQuality, aliases=("qualidade",)),
    ColumnSpec("note", "text", required=False, aliases=("observacao", "nota")),
)


def validate_period_columns(rows: Sequence[dict[str, object]]) -> list[str]:
    """Checa coerencia de periodo: fim nunca antes do inicio."""
    problemas: list[str] = []
    for numero, linha in enumerate(rows, start=2):
        inicio = linha.get("delivery_start")
        fim = linha.get("delivery_end")
        if isinstance(inicio, date) and isinstance(fim, date) and fim < inicio:
            problemas.append(
                f"linha {numero}: fim de entrega ({fim.isoformat()}) anterior ao "
                f"inicio ({inicio.isoformat()})."
            )
    return problemas


__all__ = [
    "DATE_FORMATS",
    "FORWARD_CURVE_SCHEMA",
    "LICENSED_CURVE_SCHEMA",
    "MANUAL_OBSERVATION_SCHEMA",
    "ColumnSpec",
    "ValidationReport",
    "parse_date",
    "parse_decimal",
    "validate_period_columns",
    "validate_table",
]
