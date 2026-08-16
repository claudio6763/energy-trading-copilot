"""Adapters de upload: curva forward e observacao manual.

Estes dois sao o caminho critico do RF-11 — o registro ao vivo na defesa, com um
dado dado na hora. Precisam aceitar CSV e XLSX, validar de forma legivel e
recusar o que nao entenderem, em vez de ingerir metade.

**Regra dura, implementada aqui e testada:** PLD e CMO nao sao curva forward
negociada. Sao preco de curto prazo formado por modelo de despacho, nao por
transacao entre contrapartes. Se alguem subir uma curva batizada de PLD/CMO
declarando `CurveOrigin.NEGOCIADA`, a ingestao e recusada. Se declarar
`PROXY_SPOT`, e aceita, marcada `DataQuality.PROXY` e penalizada no risco
(`quant.addons.proxy_addon`).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from copilot.common.enums import (
    PROXY_CURVE_ORIGINS,
    SPOT_ONLY_METRICS,
    AdapterStatus,
    CurveOrigin,
    CurvePriceType,
    DataQuality,
    LicenseClass,
    ProductClass,
    SourceKind,
    Submarket,
    Unit,
)
from copilot.common.errors import ProxyNotDeclaredError, SchemaValidationError
from copilot.ingest.adapters.base import BaseAdapter, read_payload
from copilot.ingest.contracts import (
    AdapterResult,
    CurvePointRow,
    CurveRow,
    ObservationRow,
    SourceSpec,
)
from copilot.ingest.files import read_bytes
from copilot.ingest.validation import (
    FORWARD_CURVE_SCHEMA,
    LICENSED_CURVE_SCHEMA,
    MANUAL_OBSERVATION_SCHEMA,
    validate_period_columns,
    validate_table,
)

_SPOT_PATTERN = re.compile(r"\b(pld|cmo)\b", re.IGNORECASE)


def looks_like_spot(text: str) -> bool:
    """Detecta PLD/CMO no nome da curva ou da metrica."""
    if not text:
        return False
    normalizado = text.strip().lower()
    if normalizado in SPOT_ONLY_METRICS:
        return True
    return bool(_SPOT_PATTERN.search(normalizado))


class ForwardCurveUploadAdapter(BaseAdapter):
    """Curva forward enviada pelo trader em CSV ou XLSX.

    Colunas aceitas (com apelidos em portugues): `tenor`, `delivery_start`,
    `delivery_end`, `price` e, opcionalmente, `submarket` e `quality`.
    """

    name = "forward_curve_upload"
    media_type = "text/csv"
    offline = True

    source = SourceSpec(
        name="Upload de curva forward (mesa)",
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.CONFIDENTIAL_INTERNAL,
        publisher="Mesa de comercializacao",
        authorized=True,
        authorization_ref="dado interno da propria mesa",
        update_frequency="sob demanda",
        notes="Curva informada pela mesa. Origem sempre declarada explicitamente.",
    )

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        payload, nome = read_payload(kwargs["file"])  # type: ignore[index]
        self._filename = nome if not kwargs.get("filename") else str(kwargs["filename"])
        return payload

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        nome_arquivo = str(kwargs.get("filename") or getattr(self, "_filename", "upload.csv"))
        curve_name = str(kwargs["curve_name"])
        submarket: Submarket = kwargs.get("submarket") or Submarket.SE_CO  # type: ignore[assignment]
        product_class: ProductClass = kwargs.get("product_class") or ProductClass.CONVENCIONAL  # type: ignore[assignment]
        origin: CurveOrigin = kwargs.get("origin") or CurveOrigin.NEGOCIADA  # type: ignore[assignment]
        proxy_of = kwargs.get("proxy_of")

        self._assert_proxy_declared(curve_name, origin, proxy_of)

        tabela = read_bytes(raw, nome_arquivo, sheet=kwargs.get("sheet"))  # type: ignore[arg-type]
        relatorio = validate_table(tabela, FORWARD_CURVE_SCHEMA)
        problemas_periodo = validate_period_columns(relatorio.rows)
        relatorio.issues.extend(problemas_periodo)
        linhas = relatorio.raise_if_invalid(nome_arquivo)

        if origin in PROXY_CURVE_ORIGINS:
            qualidade_curva = DataQuality.PROXY
            tipo_preco = CurvePriceType.PROXY_PUBLICO
        else:
            qualidade_curva = DataQuality.OK
            tipo_preco = CurvePriceType(kwargs.get("price_type") or CurvePriceType.MID)

        pontos: list[CurvePointRow] = []
        vistos: set[str] = set()
        for linha in linhas:
            rotulo = str(linha["tenor"])
            if rotulo in vistos:
                raise SchemaValidationError(
                    f"{nome_arquivo}: tenor {rotulo!r} repetido. "
                    "Curva com tenor duplicado nao e curva."
                )
            vistos.add(rotulo)
            pontos.append(
                CurvePointRow(
                    tenor_label=rotulo,
                    delivery_start=linha["delivery_start"],  # type: ignore[arg-type]
                    delivery_end=linha["delivery_end"],  # type: ignore[arg-type]
                    price=Decimal(linha["price"]),  # type: ignore[arg-type]
                    quality=linha.get("quality") or qualidade_curva,  # type: ignore[arg-type]
                )
            )

        pontos.sort(key=lambda p: p.delivery_start)
        notas = [f"arquivo: {nome_arquivo}"]
        if origin in PROXY_CURVE_ORIGINS:
            notas.append(
                f"ORIGEM {origin.value}: nao e preco negociado. "
                "Penalizado no calculo de risco (add-on de proxy)."
            )

        curva = CurveRow(
            curve_name=curve_name,
            submarket=submarket,
            product_class=product_class,
            origin=origin,
            as_of=as_of,
            points=tuple(pontos),
            price_type=tipo_preco,
            quality=qualidade_curva,
            proxy_of=str(proxy_of) if proxy_of else None,
            notes=" | ".join(notas),
        )
        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=AdapterStatus.OK,
            as_of=as_of,
            curves=(curva,),
            issues=tuple(problemas_periodo),
        )

    @staticmethod
    def _assert_proxy_declared(
        curve_name: str, origin: CurveOrigin, proxy_of: object
    ) -> None:
        """Impede que PLD/CMO entre como curva negociada."""
        if origin is CurveOrigin.NEGOCIADA and looks_like_spot(curve_name):
            raise ProxyNotDeclaredError(
                f"Curva {curve_name!r} parece derivar de PLD/CMO, mas foi declarada "
                f"como {CurveOrigin.NEGOCIADA.value}. PLD e CMO sao precos de curto "
                "prazo formados por modelo de despacho, nao precos negociados. "
                f"Use origin={CurveOrigin.PROXY_SPOT.value} e informe `proxy_of`."
            )
        if origin is CurveOrigin.PROXY_SPOT and not proxy_of:
            raise ProxyNotDeclaredError(
                "Curva declarada como PROXY_SPOT exige `proxy_of` — qual preco de "
                "curto prazo esta sendo usado como substituto."
            )


class ManualObservationAdapter(BaseAdapter):
    """Leitura avulsa de metrica: arquivo ou linhas informadas na sessao.

    E o caminho do dado que a banca entrega na hora (RF-11). Aceita CSV, XLSX e
    tambem uma lista de dicionarios, para o formulario da UI.

    Nota: PLD e CMO **sao** observacoes legitimas aqui. A restricao do projeto
    nao e sobre observar o spot — e sobre chama-lo de curva forward negociada.
    """

    name = "manual_observation"
    media_type = "text/csv"
    offline = True

    source = SourceSpec(
        name="Entrada manual (mesa)",
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.CONFIDENTIAL_INTERNAL,
        publisher="Mesa de comercializacao",
        authorized=True,
        authorization_ref="dado informado pelo proprio operador",
        update_frequency="sob demanda",
        notes="Leitura informada manualmente; qualidade declarada pelo operador.",
    )

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "rows" in kwargs:
            import json

            return json.dumps(
                kwargs["rows"], ensure_ascii=False, default=str
            ).encode("utf-8")
        payload, nome = read_payload(kwargs["file"])  # type: ignore[index]
        self._filename = nome if not kwargs.get("filename") else str(kwargs["filename"])
        return payload

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        if "rows" in kwargs:
            linhas = self._from_rows(kwargs["rows"], as_of=as_of)  # type: ignore[arg-type]
            problemas: list[str] = []
        else:
            nome = str(kwargs.get("filename") or getattr(self, "_filename", "upload.csv"))
            tabela = read_bytes(raw, nome, sheet=kwargs.get("sheet"))  # type: ignore[arg-type]
            relatorio = validate_table(tabela, MANUAL_OBSERVATION_SCHEMA)
            validadas = relatorio.raise_if_invalid(nome)
            problemas = list(relatorio.issues)
            linhas = [self._to_observation(linha, as_of=as_of) for linha in validadas]

        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=AdapterStatus.OK,
            as_of=as_of,
            observations=tuple(linhas),
            issues=tuple(problemas),
        )

    def _from_rows(
        self, rows: object, *, as_of: date
    ) -> list[ObservationRow]:
        from copilot.ingest.files import Table

        registros = list(rows)  # type: ignore[arg-type]
        if not registros:
            raise SchemaValidationError("Nenhuma linha informada.")
        colunas = tuple(sorted({c for r in registros for c in r}))
        tabela = Table(colunas, tuple(registros), "entrada_manual")
        relatorio = validate_table(tabela, MANUAL_OBSERVATION_SCHEMA)
        validadas = relatorio.raise_if_invalid("entrada_manual")
        return [self._to_observation(linha, as_of=as_of) for linha in validadas]

    @staticmethod
    def _to_observation(linha: dict[str, object], *, as_of: date) -> ObservationRow:
        chave = str(linha["metric_key"]).strip()
        qualidade = linha.get("quality") or DataQuality.OK
        # Observacao informada a mao, sem publicacao oficial, nunca e "OK" puro:
        # o operador pode declarar melhor, mas o padrao e conservador.
        return ObservationRow(
            metric_key=chave,
            ref_date=linha["ref_date"],  # type: ignore[arg-type]
            value=Decimal(linha["value"]),  # type: ignore[arg-type]
            unit=linha["unit"],  # type: ignore[arg-type]
            as_of=linha.get("as_of") or as_of,  # type: ignore[arg-type]
            quality=qualidade,  # type: ignore[arg-type]
            description=f"Entrada manual de {chave}",
            note=str(linha.get("note") or "") or None,
        )


# ===========================================================================
# Curva licenciada — importacao manual (Dcide e afins), CSV/XLSX
# ===========================================================================
#: Classificacoes validas (secao 9 do prompt de integracoes). Nunca se misturam.
CURVE_CATEGORIES: tuple[str, ...] = (
    "MARKET_FORWARD_DELAYED_PUBLIC",
    "MARKET_FORWARD_LICENSED",
    "STATISTICAL_SCENARIO_PUBLIC",
    "MANUAL_AUTHORIZED_CURVE",
)

_CATEGORY_ORIGIN = {
    "MARKET_FORWARD_DELAYED_PUBLIC": CurveOrigin.NEGOCIADA,
    "MARKET_FORWARD_LICENSED": CurveOrigin.NEGOCIADA,
    "STATISTICAL_SCENARIO_PUBLIC": CurveOrigin.PROXY_MODELO,
    "MANUAL_AUTHORIZED_CURVE": CurveOrigin.INTERNA,
}
_CATEGORY_CLASSIFICATION = {
    "MARKET_FORWARD_DELAYED_PUBLIC": "negociado",
    "MARKET_FORWARD_LICENSED": "negociado",
    "STATISTICAL_SCENARIO_PUBLIC": "projetado",
    "MANUAL_AUTHORIZED_CURVE": "manual",
}


class LicensedCurveCsvAdapter(BaseAdapter):
    """Importacao manual de curva obtida legalmente fora do sistema (Dcide etc.).

    Schema fixo (secao 12 do prompt de integracoes): `reference_date`,
    `delivery_start`, `delivery_end`, `submarket`, `energy_type`, `product`,
    `price_brl_mwh`, `source`, `curve_type`. Cada linha e um ponto de curva;
    linhas com o mesmo `source`+`product`+`curve_type`+`reference_date` viram
    tenores da mesma curva.

    Nunca faz scraping automatico da fonte licenciada — o CSV chega pronto,
    obtido por fora (contrato, portal do provedor, planilha do trader).
    """

    name = "licensed_curve_csv"
    media_type = "text/csv"
    offline = True

    source = SourceSpec(
        name="Importacao manual de curva licenciada (Dcide e afins)",
        source_kind=SourceKind.MANUAL,
        license_class=LicenseClass.LICENSED_AUTHORIZED,
        publisher="Mesa de comercializacao",
        authorized=True,
        authorization_ref="importacao manual autorizada pelo operador, fora do sistema",
        update_frequency="sob demanda",
        notes="Curva obtida legalmente e importada por CSV/XLSX. Sem scraping automatico.",
    )

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        payload, nome = read_payload(kwargs["file"])  # type: ignore[index]
        self._filename = nome if not kwargs.get("filename") else str(kwargs["filename"])
        return payload

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        nome_arquivo = str(kwargs.get("filename") or getattr(self, "_filename", "curva_manual.csv"))
        tabela = read_bytes(raw, nome_arquivo, sheet=kwargs.get("sheet"))  # type: ignore[arg-type]
        relatorio = validate_table(tabela, LICENSED_CURVE_SCHEMA)
        problemas_periodo = validate_period_columns(relatorio.rows)
        relatorio.issues.extend(problemas_periodo)
        linhas = relatorio.raise_if_invalid(nome_arquivo)

        grupos: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
        for linha in linhas:
            categoria = str(linha["curve_type"]).strip().upper()
            if categoria not in CURVE_CATEGORIES:
                raise SchemaValidationError(
                    f"{nome_arquivo}: curve_type {categoria!r} invalido. "
                    f"Aceitos: {', '.join(CURVE_CATEGORIES)}."
                )
            produto = str(linha["product"]).strip()
            if categoria != "STATISTICAL_SCENARIO_PUBLIC" and looks_like_spot(produto):
                raise ProxyNotDeclaredError(
                    f"{nome_arquivo}: produto {produto!r} parece PLD/CMO, mas foi "
                    f"declarado como {categoria}. PLD e CMO nao sao preco negociado; "
                    "use curve_type=STATISTICAL_SCENARIO_PUBLIC ou remova a linha."
                )
            chave = (str(linha["source"]), produto, categoria, linha["reference_date"].isoformat())  # type: ignore[union-attr]
            grupos.setdefault(chave, []).append(linha)

        curvas: list[CurveRow] = []
        for (fonte, produto, categoria, data_ref), pontos_linha in grupos.items():
            pontos = []
            vistos: set[str] = set()
            for linha in pontos_linha:
                rotulo = f"{linha['delivery_start']}_{linha['delivery_end']}"
                if rotulo in vistos:
                    raise SchemaValidationError(
                        f"{nome_arquivo}: tenor duplicado para {fonte}/{produto} em {rotulo}."
                    )
                vistos.add(rotulo)
                pontos.append(
                    CurvePointRow(
                        tenor_label=rotulo,
                        delivery_start=linha["delivery_start"],  # type: ignore[arg-type]
                        delivery_end=linha["delivery_end"],  # type: ignore[arg-type]
                        price=Decimal(linha["price_brl_mwh"]),  # type: ignore[arg-type]
                        quality=DataQuality.OK,
                    )
                )
            pontos.sort(key=lambda p: p.delivery_start)
            submercado = pontos_linha[0].get("submarket") or Submarket.SE_CO
            energia = str(pontos_linha[0].get("energy_type") or "CONVENCIONAL").strip().upper()
            product_class = energia if energia in ProductClass.values() else ProductClass.CONVENCIONAL.value
            curvas.append(
                CurveRow(
                    curve_name=f"{produto} ({fonte})",
                    submarket=submercado,  # type: ignore[arg-type]
                    product_class=ProductClass(product_class),
                    origin=_CATEGORY_ORIGIN[categoria],
                    as_of=as_of,
                    points=tuple(pontos),
                    price_type=CurvePriceType.MID,
                    quality=DataQuality.OK,
                    notes=f"{categoria}. Fonte: {fonte}. Importado de {nome_arquivo}.",
                )
            )

        return AdapterResult(
            adapter=self.name, source=self.source, status=AdapterStatus.OK, as_of=as_of,
            curves=tuple(curvas), issues=tuple(problemas_periodo),
        )


__all__ = [
    "CURVE_CATEGORIES",
    "ForwardCurveUploadAdapter",
    "LicensedCurveCsvAdapter",
    "ManualObservationAdapter",
    "looks_like_spot",
]
