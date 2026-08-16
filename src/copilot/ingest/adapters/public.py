"""Fontes publicas: interfaces declaradas e um adapter funcional.

**Postura honesta sobre cobertura.** Declarar cinco integracoes e entregar cinco
esqueletos quebrados seria pior do que declarar uma que funciona. Entao:

* ONS, CCEE, ANEEL, ANA e clima entram como **interfaces declaradas**
  (`UnavailableAdapter`): aparecem no catalogo, aparecem no relatorio de
  cobertura do Watchdog como indisponiveis, e cada uma diz o que falta para
  virar implementacao. Nenhuma delas inventa dado.
* **ENSO / ONI (NOAA CPC)** e implementado de ponta a ponta: endpoint publico,
  estavel ha decadas, texto de largura fixa, sem chave de API e sem termo de uso
  restritivo. E a fonte publica com melhor relacao entre estabilidade e esforco.

Por que ENSO importa numa mesa de energia brasileira: El Nino / La Nina desloca
o regime de chuva no Sul e no Sudeste, e portanto a afluencia, o despacho
termico e o preco. Nao e previsao de preco — e condicionante de cenario
hidrologico, que e exatamente o que a Entrega 2 pede.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation

from copilot.common.enums import (
    AdapterStatus,
    DataQuality,
    LicenseClass,
    SourceKind,
    Submarket,
    Unit,
)
from copilot.common.errors import AdapterUnavailable, SchemaValidationError
from copilot.common.logging import get_logger
from copilot.ingest.adapters.base import BaseAdapter, UnavailableAdapter
from copilot.ingest.contracts import AdapterResult, ObservationRow, SourceSpec
from copilot.ingest.files import read_csv_bytes

log = get_logger(__name__)

DEFAULT_TIMEOUT = 20
_UA = "energy-trading-copilot/0.1 (uso interno de mesa; +https://github.com)"


# ===========================================================================
# CKAN — descoberta dinamica de dataset/recurso (ONS e CCEE usam a mesma
# plataforma). Nunca fixa URL anual: resolve o recurso do ano corrente (ou do
# ano anterior, se o corrente ainda nao tiver arquivo) a cada execucao.
# ===========================================================================
def _http_get_bytes(url: str, *, timeout: int, accept: str | None = None) -> bytes:
    headers = {"User-Agent": _UA}
    if accept:
        headers["Accept"] = accept
    requisicao = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
            tipo = (resposta.headers.get("Content-Type") or "").lower()
            if "html" in tipo and accept != "text/html":
                raise AdapterUnavailable(
                    f"{url}: resposta HTML inesperada (content-type {tipo!r}); "
                    "provavel bloqueio, redirecionamento ou pagina de erro."
                )
            return resposta.read()
    except urllib.error.HTTPError as exc:
        raise AdapterUnavailable(f"{url}: HTTP {exc.code} ({exc.reason}).") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AdapterUnavailable(f"{url}: falha de rede ({exc}).") from exc


def _ckan_package_show(base_url: str, package: str, *, timeout: int) -> dict:
    endpoint = f"{base_url.rstrip('/')}/api/3/action/package_show?id={package}"
    bruto = _http_get_bytes(endpoint, timeout=timeout, accept="application/json")
    try:
        corpo = json.loads(bruto.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterUnavailable(
            f"{endpoint}: resposta nao e JSON valido do CKAN."
        ) from exc
    if not corpo.get("success"):
        raise AdapterUnavailable(f"{endpoint}: CKAN reportou success=false.")
    return corpo["result"]


_YEAR_IN_NAME = re.compile(r"(20\d{2})")


def _pick_csv_resource(result: dict, *, as_of: date, name_hint: str | None = None) -> tuple[str, int]:
    """Escolhe o recurso CSV do ano-base, com fallback para o ano anterior.

    Nunca depende de posicao na lista: filtra por `format=CSV` e pelo ano no
    nome/URL do recurso, que e como o catalogo do ONS/CCEE versiona arquivo
    anual sem mudar o identificador do dataset.
    """
    recursos = [r for r in result.get("resources", []) if (r.get("format") or "").upper() == "CSV"]
    if name_hint:
        filtrados = [r for r in recursos if name_hint.lower() in (r.get("name") or "").lower()]
        if filtrados:
            recursos = filtrados
    if not recursos:
        raise AdapterUnavailable(
            f"Dataset {result.get('name')!r}: nenhum recurso CSV encontrado no catalogo."
        )

    por_ano: dict[int, str] = {}
    for recurso in recursos:
        alvo = f"{recurso.get('name', '')} {recurso.get('url', '')}"
        achado = _YEAR_IN_NAME.findall(alvo)
        if achado:
            por_ano[int(achado[-1])] = recurso["url"]

    for candidato in (as_of.year, as_of.year - 1):
        if candidato in por_ano:
            return por_ano[candidato], candidato

    if por_ano:
        ano = max(por_ano)
        return por_ano[ano], ano

    # Catalogo sem ano identificavel no nome: usa o recurso mais recente listado.
    return recursos[-1]["url"], as_of.year


# ===========================================================================
# ONS — carga, ENA, EAR e CMO semanal por subsistema
# ===========================================================================
_ONS_SUBMARKET = {
    "N": Submarket.N, "NE": Submarket.NE, "S": Submarket.S, "SE": Submarket.SE_CO,
}


def _normalize_subsystem(raw: str) -> Submarket | None:
    return _ONS_SUBMARKET.get((raw or "").strip().upper())


_SUBMARKET_SLUG = {Submarket.SE_CO: "seco", Submarket.S: "s", Submarket.NE: "ne", Submarket.N: "n"}


def _submarket_slug(submercado: Submarket) -> str:
    """Sufixo ASCII do submercado no `metric_key` (convencao de DATA_CONTRACT.md
    secao 6: `ear_sudeste_pct`, `pld_se_semanal`). Sem isso, series de
    submercados diferentes colidem na UNIQUE (metric, ref_date, as_of,
    model_run) de `market_observations` e uma sobrescreve a outra."""
    return _SUBMARKET_SLUG[submercado]


class _OnsDatasetSpec:
    __slots__ = ("package", "date_col", "subsystem_col", "fields")

    def __init__(
        self, package: str, date_col: str, subsystem_col: str,
        fields: tuple[tuple[str, str, Unit], ...],
    ) -> None:
        self.package = package
        self.date_col = date_col
        self.subsystem_col = subsystem_col
        self.fields = fields


class OnsAdapter(BaseAdapter):
    """Operador Nacional do Sistema — carga, ENA, EAR e CMO semanal, por subsistema.

    Descobre o recurso CSV atual em cada um dos quatro datasets do portal de
    dados abertos (`carga-energia`, `ena-diario-por-subsistema`,
    `ear-diario-por-subsistema`, `cmo-semanal`) via CKAN, baixa so o arquivo do
    ano-base e falha isoladamente por dataset: se um recurso mudar de layout ou
    ficar fora do ar, os outros tres continuam sendo ingeridos (`PARCIAL`).
    """

    name = "ons"
    media_type = "application/json"
    offline = False

    CKAN_BASE = "https://dados.ons.org.br"

    source = SourceSpec(
        name="ONS — Operador Nacional do Sistema",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_ATTRIB,
        publisher="ONS",
        url="https://dados.ons.org.br/",
        authorized=True,
        update_frequency="diaria",
        notes=(
            "Portal de dados abertos (CKAN). Recurso descoberto dinamicamente por "
            "ano-base; nenhuma URL anual fixa no codigo."
        ),
    )

    _DATASETS: dict[str, _OnsDatasetSpec] = {
        "carga": _OnsDatasetSpec(
            "carga-energia", "din_instante", "id_subsistema",
            (("carga_verificada_mwmed", "val_cargaenergiamwmed", Unit.MWMED),),
        ),
        "ena": _OnsDatasetSpec(
            "ena-diario-por-subsistema", "ena_data", "id_subsistema",
            (
                ("ena_bruta_pct_mlt", "ena_bruta_regiao_percentualmlt", Unit.PERCENT),
                ("ena_armazenavel_mwmed", "ena_armazenavel_regiao_mwmed", Unit.MWMED),
            ),
        ),
        "ear": _OnsDatasetSpec(
            "ear-diario-por-subsistema", "ear_data", "id_subsistema",
            (("ear_verificada_pct", "ear_verif_subsistema_percentual", Unit.PERCENT),),
        ),
        "cmo": _OnsDatasetSpec(
            "cmo-semanal", "din_instante", "id_subsistema",
            (("cmo_semanal_brl_mwh", "val_cmomediasemanal", Unit.BRL_PER_MWH),),
        ),
    }

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "payload" in kwargs and kwargs["payload"] is not None:
            valor = kwargs["payload"]
            return valor if isinstance(valor, bytes) else str(valor).encode("utf-8")

        timeout = int(kwargs.get("timeout") or DEFAULT_TIMEOUT)
        apenas = kwargs.get("datasets")
        chaves = tuple(apenas) if apenas else tuple(self._DATASETS)

        blocos: dict[str, dict[str, str]] = {}
        erros: list[str] = []
        for chave in chaves:
            spec = self._DATASETS[chave]
            try:
                catalogo = _ckan_package_show(self.CKAN_BASE, spec.package, timeout=timeout)
                url, ano = _pick_csv_resource(catalogo, as_of=as_of)
                texto = _http_get_bytes(url, timeout=timeout).decode("utf-8-sig", errors="replace")
                blocos[chave] = {"url": url, "year": str(ano), "csv": texto}
            except AdapterUnavailable as exc:
                erros.append(f"{chave} ({spec.package}): {exc}")
                log.warning("ons_dataset_indisponivel", extra={"dataset": chave, "motivo": str(exc)})

        if not blocos:
            raise AdapterUnavailable(
                "ONS indisponivel para todos os datasets consultados: " + "; ".join(erros)
            )
        return json.dumps(
            {"as_of": as_of.isoformat(), "datasets": blocos, "errors": erros},
            ensure_ascii=False,
        ).encode("utf-8")

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        corpo = json.loads(raw.decode("utf-8"))
        issues: list[str] = list(corpo.get("errors") or [])
        observacoes: list[ObservationRow] = []

        for chave, spec in self._DATASETS.items():
            bloco = corpo.get("datasets", {}).get(chave)
            if not bloco:
                continue
            try:
                tabela = read_csv_bytes(
                    bloco["csv"].encode("utf-8"), source_name=f"ons_{chave}", delimiter=";"
                )
                tabela.require_columns([spec.date_col, spec.subsystem_col, *(c for _, c, _ in spec.fields)])
            except SchemaValidationError as exc:
                issues.append(f"{chave}: layout inesperado — {exc}")
                continue

            for linha in tabela.rows:
                try:
                    referencia = date.fromisoformat(str(linha[spec.date_col]).strip()[:10])
                except ValueError:
                    continue
                if referencia > as_of:
                    continue  # protecao contra look-ahead (RF-58)
                submercado = _normalize_subsystem(str(linha.get(spec.subsystem_col, "")))
                if submercado is None:
                    continue
                for metric_key, coluna, unidade in spec.fields:
                    bruto = linha.get(coluna)
                    if bruto is None:
                        continue
                    try:
                        valor = bruto if isinstance(bruto, Decimal) else Decimal(str(bruto))
                    except InvalidOperation:
                        continue
                    chave = f"{metric_key}_{_submarket_slug(submercado)}"
                    observacoes.append(
                        ObservationRow(
                            metric_key=chave,
                            ref_date=referencia,
                            value=valor,
                            unit=unidade,
                            as_of=as_of,
                            quality=DataQuality.OK,
                            submarket=submercado,
                            description=(
                                f"ONS — {metric_key} ({submercado.value}) em "
                                f"{referencia.isoformat()}, recurso {bloco['year']}."
                            ),
                        )
                    )

        if not observacoes:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of, reason="Nenhuma observacao valida extraida dos datasets do ONS.",
                issues=tuple(issues),
            )
        status = AdapterStatus.PARCIAL if issues else AdapterStatus.OK
        return AdapterResult(
            adapter=self.name, source=self.source, status=status, as_of=as_of,
            observations=tuple(observacoes), issues=tuple(issues),
        )


# ===========================================================================
# CCEE — PLD por submercado (horario, diario, semanal, mensal)
# ===========================================================================
class CceeAdapter(BaseAdapter):
    """CCEE — Preco de Liquidacao das Diferencas (PLD) por submercado.

    Mesma estrategia de descoberta dinamica via CKAN do `OnsAdapter`, apontada
    para `dadosabertos.ccee.org.br`. **Verificado nesta sprint:** o portal
    aplica um WAF que bloqueia requisicao programatica com HTTP 403 mesmo na
    pagina raiz, a partir da rede de desenvolvimento usada aqui — nao e
    ausencia de endpoint, e bloqueio de acesso automatizado por IP/rede. O
    adapter fica pronto para redes onde o portal responde; falha declarada
    (`INDISPONIVEL`) enquanto isso, nunca dado inventado.

    PLD ingerido aqui e sempre observacao de spot (`ObservationRow`), nunca
    curva forward — a distincao e feita na camada de upload/curva
    (`CurveOrigin.PROXY_SPOT` exige `proxy_of` declarado).
    """

    name = "ccee"
    media_type = "application/json"
    offline = False

    CKAN_BASE = "https://dadosabertos.ccee.org.br"
    PACKAGE = "preco_liquidacao_diferenca"

    source = SourceSpec(
        name="CCEE — Camara de Comercializacao de Energia Eletrica",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_ATTRIB,
        publisher="CCEE",
        url="https://dadosabertos.ccee.org.br/organization/preco_liquidacao_diferenca",
        authorized=True,
        update_frequency="semanal",
        notes=(
            "Portal de dados abertos (CKAN). PLD horario/diario/semanal/mensal por "
            "submercado. PLD NUNCA e curva forward — e preco de curto prazo de "
            "modelo de despacho."
        ),
    )

    #: Nome de recurso (contido, case-insensitive) por granularidade.
    _RESOURCE_HINTS: dict[str, str] = {
        "horario": "horári",
        "diario": "diári",
        "semanal": "semanal",
        "mensal": "mensal",
    }

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "payload" in kwargs and kwargs["payload"] is not None:
            valor = kwargs["payload"]
            return valor if isinstance(valor, bytes) else str(valor).encode("utf-8")

        timeout = int(kwargs.get("timeout") or DEFAULT_TIMEOUT)
        granularidade = str(kwargs.get("granularity") or "semanal")
        dica = self._RESOURCE_HINTS.get(granularidade, granularidade)

        catalogo = _ckan_package_show(self.CKAN_BASE, self.PACKAGE, timeout=timeout)
        url, ano = _pick_csv_resource(catalogo, as_of=as_of, name_hint=dica)
        texto = _http_get_bytes(url, timeout=timeout).decode("utf-8-sig", errors="replace")
        return json.dumps(
            {"as_of": as_of.isoformat(), "granularity": granularidade, "url": url,
             "year": ano, "csv": texto},
            ensure_ascii=False,
        ).encode("utf-8")

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        corpo = json.loads(raw.decode("utf-8"))
        granularidade = corpo.get("granularity", "semanal")
        metric_key = f"pld_{granularidade}"

        try:
            tabela = read_csv_bytes(
                corpo["csv"].encode("utf-8"), source_name=f"ccee_pld_{granularidade}"
            )
        except SchemaValidationError as exc:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of, reason=f"Layout do CSV de PLD nao reconhecido: {exc}",
            )

        colunas_data = ("din_instante", "data", "data_referencia")
        colunas_submercado = ("nom_submercado", "id_subsistema", "submercado")
        colunas_valor = ("val_pld", "pld", "valor")
        col_data = next((c for c in colunas_data if c in tabela.columns), None)
        col_sub = next((c for c in colunas_submercado if c in tabela.columns), None)
        col_valor = next((c for c in colunas_valor if c in tabela.columns), None)
        if not (col_data and col_sub and col_valor):
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of,
                reason=(
                    f"Colunas esperadas nao encontradas em {corpo['url']}. "
                    f"Disponiveis: {', '.join(tabela.columns)}."
                ),
            )

        observacoes: list[ObservationRow] = []
        issues: list[str] = []
        for linha in tabela.rows:
            try:
                referencia = date.fromisoformat(str(linha[col_data]).strip()[:10])
            except ValueError:
                continue
            if referencia > as_of:
                continue  # RF-58
            submercado = _normalize_subsystem(str(linha.get(col_sub, "")))
            if submercado is None:
                continue
            bruto = linha.get(col_valor)
            if bruto is None:
                continue
            try:
                valor = bruto if isinstance(bruto, Decimal) else Decimal(str(bruto))
            except InvalidOperation:
                issues.append(f"valor de PLD invalido na linha de {referencia.isoformat()}")
                continue
            observacoes.append(
                ObservationRow(
                    metric_key=f"{metric_key}_{_submarket_slug(submercado)}",
                    ref_date=referencia,
                    value=valor,
                    unit=Unit.BRL_PER_MWH,
                    as_of=as_of,
                    quality=DataQuality.OK,
                    submarket=submercado,
                    description=(
                        f"CCEE — PLD {granularidade} ({submercado.value}) em "
                        f"{referencia.isoformat()}. Preco de spot, nao curva forward."
                    ),
                )
            )

        if not observacoes:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of, reason="Nenhuma observacao valida de PLD extraida.",
                issues=tuple(issues),
            )
        status = AdapterStatus.PARCIAL if issues else AdapterStatus.OK
        return AdapterResult(
            adapter=self.name, source=self.source, status=status, as_of=as_of,
            observations=tuple(observacoes), issues=tuple(issues),
        )


# ===========================================================================
# EPE — consumo mensal de energia eletrica
# ===========================================================================
class EpeAdapter(BaseAdapter):
    """EPE — consumo mensal de energia eletrica por regiao, classe e tipo.

    A EPE nao publica API; disponibiliza um XLSX unico, atualizado por cima do
    mesmo link (SharePoint), na pagina de dados abertos. O adapter localiza o
    link `.xlsx` na pagina oficial (regex sobre o HTML publico, sem login), com
    `EPE_CONSUMO_URL` como sobrescrita explicita, e valida que o host resolvido
    pertence a `epe.gov.br` antes de baixar — nunca aceita um link de terceiro
    injetado na pagina.

    Planilha `CONSUMO E NUMCONS SAM` (verificada em 09/08/2026): colunas `Data`
    (AAAAMMDD), `Regiao`, `Sistema`, `Classe`, `TipoConsumidor`, `Consumo` (MWh),
    `Consumidores`, `DataVersao`. Layout mudou -> `INDISPONIVEL` com mensagem
    legivel, nunca ingestao parcial silenciosa de colunas erradas.
    """

    name = "epe"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    offline = False

    PAGE_URL = (
        "https://www.epe.gov.br/pt/publicacoes-dados-abertos/dados-abertos/"
        "dados-do-consumo-mensal-de-energia-eletrica"
    )
    OFFICIAL_DOMAIN = "epe.gov.br"
    SHEET_NAME = "CONSUMO E NUMCONS SAM"
    METRIC_PREFIX = "consumo_mensal_mwh"

    source = SourceSpec(
        name="EPE — Empresa de Pesquisa Energetica (consumo mensal)",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="EPE",
        url=PAGE_URL,
        authorized=True,
        update_frequency="mensal",
        notes=(
            "Arquivo XLSX unico (sem API). Link resolvido dinamicamente na pagina "
            "oficial ou via EPE_CONSUMO_URL; dominio validado antes do download."
        ),
    )

    _REGION_TO_SUBMARKET = {
        "norte": Submarket.N, "nordeste": Submarket.NE, "sul": Submarket.S,
        "sudeste": Submarket.SE_CO, "centro-oeste": Submarket.SE_CO,
    }

    def _resolve_url(self, *, timeout: int, override: str | None) -> str:
        import os
        import urllib.parse

        url = override or os.environ.get("EPE_CONSUMO_URL") or ""
        if not url:
            html = _http_get_bytes(self.PAGE_URL, timeout=timeout, accept="text/html").decode(
                "utf-8", errors="replace"
            )
            achado = re.search(r'href="([^"]+\.xlsx)"', html, re.IGNORECASE)
            if not achado:
                raise AdapterUnavailable(
                    f"Nenhum link .xlsx encontrado em {self.PAGE_URL}. "
                    "Pagina pode ter mudado de layout; configure EPE_CONSUMO_URL "
                    "manualmente enquanto isso."
                )
            caminho = achado.group(1)
            url = caminho if caminho.startswith("http") else urllib.parse.urljoin(
                "https://www.epe.gov.br/", caminho
            )

        host = urllib.parse.urlparse(url).netloc.lower()
        if not (host == self.OFFICIAL_DOMAIN or host.endswith("." + self.OFFICIAL_DOMAIN)):
            raise AdapterUnavailable(
                f"URL resolvida {url!r} nao pertence ao dominio oficial "
                f"{self.OFFICIAL_DOMAIN!r}. Download recusado."
            )
        return url

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "payload" in kwargs and kwargs["payload"] is not None:
            valor = kwargs["payload"]
            return valor if isinstance(valor, bytes) else str(valor).encode("utf-8")

        timeout = int(kwargs.get("timeout") or 60)
        url = self._resolve_url(timeout=timeout, override=kwargs.get("url"))  # type: ignore[arg-type]
        self._resolved_url = url
        return _http_get_bytes(url, timeout=timeout)

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        from copilot.ingest.files import read_xlsx_bytes

        url = getattr(self, "_resolved_url", str(kwargs.get("url") or self.PAGE_URL))
        try:
            tabela = read_xlsx_bytes(raw, source_name="epe_consumo.xlsx", sheet=self.SHEET_NAME)
            tabela.require_columns(
                ["data", "regiao", "sistema", "classe", "tipoconsumidor", "consumo"]
            )
        except SchemaValidationError as exc:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of,
                reason=(
                    f"Layout do XLSX da EPE nao reconhecido (planilha "
                    f"{self.SHEET_NAME!r} ausente ou colunas mudaram): {exc}"
                ),
            )

        observacoes: list[ObservationRow] = []
        issues: list[str] = []
        for linha in tabela.rows:
            bruto_data = linha.get("data")
            try:
                texto_data = str(int(Decimal(str(bruto_data))))
                referencia = date(int(texto_data[:4]), int(texto_data[4:6]), 1)
            except (InvalidOperation, ValueError, TypeError):
                issues.append(f"data invalida: {bruto_data!r}")
                continue
            if referencia > as_of:
                continue  # RF-58

            regiao = str(linha.get("regiao") or "").strip().lower()
            submercado = self._REGION_TO_SUBMARKET.get(regiao)
            classe = str(linha.get("classe") or "").strip()
            tipo = str(linha.get("tipoconsumidor") or "").strip()
            consumo = linha.get("consumo")
            if consumo is None:
                continue
            try:
                valor = consumo if isinstance(consumo, Decimal) else Decimal(str(consumo))
            except InvalidOperation:
                issues.append(f"consumo invalido na linha de {referencia.isoformat()}/{regiao}")
                continue

            slug = re.sub(r"[^a-z0-9]+", "_", f"{classe}_{tipo}".lower()).strip("_")
            observacoes.append(
                ObservationRow(
                    metric_key=f"{self.METRIC_PREFIX}__{slug}",
                    ref_date=referencia,
                    value=valor,
                    unit=Unit.MWH,
                    as_of=as_of,
                    quality=DataQuality.OK,
                    submarket=submercado,
                    model_run=f"{regiao}:{classe}:{tipo}" if regiao else None,
                    description=(
                        f"EPE — consumo mensal ({regiao or 'regiao?'}, {classe}/{tipo}) "
                        f"em {referencia.isoformat()}."
                    ),
                )
            )

        if not observacoes:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of, reason="Nenhuma observacao valida extraida do XLSX da EPE.",
                issues=tuple(issues),
            )
        status = AdapterStatus.PARCIAL if issues else AdapterStatus.OK
        return AdapterResult(
            adapter=self.name, source=self.source, status=status, as_of=as_of,
            observations=tuple(observacoes), issues=tuple(issues[:50]),
        )


class AneelAdapter(UnavailableAdapter):
    """ANEEL — resolucoes, tarifas e dados de geracao."""

    name = "aneel"
    source = SourceSpec(
        name="ANEEL — Agencia Nacional de Energia Eletrica",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="ANEEL",
        url="https://dadosabertos.aneel.gov.br/",
        authorized=True,
        update_frequency="mensal",
        notes="Alimenta principalmente o acervo regulatorio do Sprint 4.",
    )
    reason = "Interface declarada. Prioridade do Sprint 4 (RAG regulatorio)."


class AnaAdapter(UnavailableAdapter):
    """ANA — vazoes e niveis de reservatorio."""

    name = "ana"
    source = SourceSpec(
        name="ANA — Agencia Nacional de Aguas",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_ATTRIB,
        publisher="ANA",
        url="https://www.snirh.gov.br/hidroweb/",
        authorized=True,
        update_frequency="diaria",
        notes="Vazao observada por estacao; complementa a ENA publicada pelo ONS.",
    )
    reason = (
        "Interface declarada. HidroWeb exige selecao por estacao e o inventario de "
        "estacoes relevantes ainda nao foi fechado."
    )


class ClimateAdapter(UnavailableAdapter):
    """Clima — precipitacao observada e prevista, por rodada e por membro.

    A divergencia entre rodadas e preservada por construcao: cada rodada vira uma
    `market_series` propria (`model_run` / `ensemble_member`). Nunca se calcula
    media antes de armazenar (DATA_CONTRACT secao 6).
    """

    name = "climate"
    source = SourceSpec(
        name="Clima — INMET / NOAA GFS",
        source_kind=SourceKind.MODELO_METEO,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="INMET / NOAA",
        url="https://portal.inmet.gov.br/",
        authorized=True,
        update_frequency="varias vezes ao dia",
        notes="Uma serie por rodada e por membro de ensemble. Sem media na ingestao.",
    )
    reason = (
        "Interface declarada. GRIB do GFS exige decodificador binario, fora do "
        "escopo de dependencias do projeto; INMET precisa de mapeamento de estacao."
    )


# ===========================================================================
# ENSO / ONI — adapter publico funcional
# ===========================================================================
#: Ordem canonica das estacoes moveis do ONI e o mes central de cada uma.
_ONI_SEASONS: dict[str, int] = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}

#: Limiares do CPC para classificar o regime.
ENSO_EL_NINO_THRESHOLD = Decimal("0.5")
ENSO_LA_NINA_THRESHOLD = Decimal("-0.5")


def classify_enso(anomaly: Decimal) -> str:
    """Classifica a anomalia ONI. Regra do CPC, nao julgamento nosso."""
    if anomaly >= ENSO_EL_NINO_THRESHOLD:
        return "EL_NINO"
    if anomaly <= ENSO_LA_NINA_THRESHOLD:
        return "LA_NINA"
    return "NEUTRO"


class EnsoOniAdapter(BaseAdapter):
    """Oceanic Nino Index (ONI) do NOAA Climate Prediction Center.

    Formato do arquivo (texto, colunas separadas por espaco)::

        SEAS YR TOTAL ANOM
        DJF 1950 24.72 -1.53
        JFM 1950 25.17 -1.34

    `SEAS` e a estacao movel de tres meses; `ANOM` e a anomalia em graus Celsius,
    que e o indice em si. Convertemos a estacao no mes central para ter uma
    `ref_date` utilizavel.

    O adapter aceita `payload` injetado, o que permite testar o parser sem rede e
    reprocessar um snapshot arquivado sem sair para a internet.
    """

    name = "enso_oni"
    media_type = "text/plain"
    offline = False

    URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
    METRIC_KEY = "enso_oni_anomaly"

    source = SourceSpec(
        name="NOAA CPC — Oceanic Nino Index (ONI)",
        source_kind=SourceKind.OFICIAL,
        license_class=LicenseClass.PUBLIC_OPEN,
        publisher="NOAA Climate Prediction Center",
        url=URL,
        authorized=True,
        update_frequency="mensal",
        notes=(
            "Dado publico do governo dos EUA, sem restricao de uso. "
            "Condicionante de cenario hidrologico, nao previsao de preco."
        ),
    )

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "payload" in kwargs and kwargs["payload"] is not None:
            payload = kwargs["payload"]
            return payload if isinstance(payload, bytes) else str(payload).encode("utf-8")

        requisicao = urllib.request.Request(
            self.URL,
            headers={"User-Agent": "energy-trading-copilot/0.1 (uso interno de mesa)"},
        )
        try:
            with urllib.request.urlopen(
                requisicao, timeout=int(kwargs.get("timeout") or DEFAULT_TIMEOUT)
            ) as resposta:
                return resposta.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise AdapterUnavailable(
                f"NOAA CPC inacessivel ({exc}). Sem rede, use `payload=` com um "
                "snapshot arquivado. Ausencia de dado nao vira premissa valida."
            ) from exc

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        texto = raw.decode("utf-8", errors="replace")
        observacoes: list[ObservationRow] = []
        problemas: list[str] = []

        for numero, linha in enumerate(texto.splitlines(), start=1):
            campos = linha.split()
            if len(campos) < 4:
                continue
            estacao, ano_txt, _total, anomalia_txt = campos[0], campos[1], campos[2], campos[3]
            if estacao.upper() not in _ONI_SEASONS:
                continue  # cabecalho e linhas de rodape
            try:
                ano = int(ano_txt)
                anomalia = Decimal(anomalia_txt)
            except (ValueError, InvalidOperation):
                problemas.append(f"linha {numero}: valores nao numericos ({linha.strip()!r})")
                continue

            mes = _ONI_SEASONS[estacao.upper()]
            referencia = date(ano, mes, 1)
            if referencia > as_of:
                continue  # protecao contra look-ahead (RF-58)

            observacoes.append(
                ObservationRow(
                    metric_key=self.METRIC_KEY,
                    ref_date=referencia,
                    value=anomalia,
                    unit=Unit.ADIMENSIONAL,
                    as_of=as_of,
                    quality=DataQuality.OK,
                    description=(
                        f"Anomalia ONI da estacao {estacao.upper()} de {ano} "
                        f"({classify_enso(anomalia)})"
                    ),
                    note=f"regime={classify_enso(anomalia)}",
                )
            )

        if not observacoes:
            return AdapterResult(
                adapter=self.name,
                source=self.source,
                status=AdapterStatus.INDISPONIVEL,
                as_of=as_of,
                reason="Payload sem nenhuma linha de ONI reconhecida.",
                issues=tuple(problemas),
            )

        observacoes.sort(key=lambda o: o.ref_date)
        status = AdapterStatus.PARCIAL if problemas else AdapterStatus.OK
        return AdapterResult(
            adapter=self.name,
            source=self.source,
            status=status,
            as_of=as_of,
            observations=tuple(observacoes),
            issues=tuple(problemas),
        )

    @staticmethod
    def latest_regime(result: AdapterResult) -> tuple[date, Decimal, str] | None:
        """Ultima leitura e o regime correspondente. Base do cenario hidrologico."""
        if not result.observations:
            return None
        ultima = max(result.observations, key=lambda o: o.ref_date)
        return ultima.ref_date, ultima.value, classify_enso(ultima.value)


__all__ = [
    "AnaAdapter",
    "AneelAdapter",
    "CceeAdapter",
    "ClimateAdapter",
    "ENSO_EL_NINO_THRESHOLD",
    "ENSO_LA_NINA_THRESHOLD",
    "EnsoOniAdapter",
    "EpeAdapter",
    "OnsAdapter",
    "classify_enso",
]
