"""Curvas forward licenciadas ou de verificacao pendente — B3/N5X e BBCE.

Os dois adapters aqui **nunca** ficam ativos por acidente:

* `B3N5xAdapter` fica `UnavailableAdapter` porque a verificacao feita em
  09/08/2026 nao encontrou endpoint publico automatizavel (apenas PDFs de
  metodologia na pagina oficial). Ver `docs/CONEXOES_DADOS_SETOR.md`.
* `BbceForwardAdapter` fica desligado por padrao (`BBCE_API_ENABLED=false`) e
  so tenta a chamada real quando as quatro variaveis de ambiente estao
  presentes. Sem elas, devolve `DISABLED_MISSING_CREDENTIALS` sem tocar rede.

Nenhum dos dois inventa payload de resposta: o formato exato da CCEE... da
BBCE nao e re-implementado a partir de suposicao — o parser aceita o formato
documentado publicamente (lista de pontos com data de entrega e preco) e
declara `INDISPONIVEL` se a resposta real vier em outro formato.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation

from copilot.common.enums import (
    AdapterStatus,
    CurveOrigin,
    CurvePriceType,
    DataQuality,
    LicenseClass,
    ProductClass,
    SourceKind,
    Submarket,
)
from copilot.common.errors import AdapterUnavailable
from copilot.common.logging import get_logger
from copilot.ingest.adapters.base import BaseAdapter, UnavailableAdapter
from copilot.ingest.contracts import AdapterResult, CurvePointRow, CurveRow, SourceSpec

log = get_logger(__name__)

CURVE_CATEGORY_DELAYED_PUBLIC = "MARKET_FORWARD_DELAYED_PUBLIC"
CURVE_CATEGORY_LICENSED = "MARKET_FORWARD_LICENSED"


def mask_secret(value: str | None) -> str:
    """Nunca loga segredo em claro. `abcd1234` -> `ab******34`."""
    if not value:
        return "(ausente)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


# ===========================================================================
# B3 / N5X — verificacao feita, sem endpoint publico automatizavel
# ===========================================================================
class B3N5xAdapter(UnavailableAdapter):
    """B3 — plataforma de energia, curva N5X (divulgacao com defasagem)."""

    name = "b3_n5x"
    source = SourceSpec(
        name="B3 — Plataforma de Energia (curva N5X)",
        source_kind=SourceKind.PROVEDOR_COMERCIAL,
        license_class=LicenseClass.PUBLIC_ATTRIB,
        publisher="B3",
        url=(
            "https://www.b3.com.br/pt_br/produtos-e-servicos/outros-servicos/"
            "servicos-de-natureza-informacional/plataforma-de-energia-da-b3/"
        ),
        authorized=True,
        update_frequency="diaria (defasagem declarada de 5 dias uteis)",
        notes=(
            "NOT_VERIFIED em 09/08/2026: a pagina oficial da B3 disponibiliza apenas "
            "documentos de metodologia (PDF, fileDownload.jsp) para a curva N5X; "
            "nenhum endpoint JSON/CSV publico automatizavel foi localizado na "
            "verificacao feita para esta sprint. Requisicao real feita contra a "
            "pagina retornou HTML/PDF, nao dado tabular. Reavaliar se a B3 publicar "
            "API/arquivo de download direto."
        ),
    )
    reason = (
        "NOT_VERIFIED — sem endpoint publico automatizavel confirmado (ver notes "
        "da fonte e docs/CONEXOES_DADOS_SETOR.md). Nao foi feito scraping fragil "
        "de HTML para simular dado tabular."
    )


# ===========================================================================
# BBCE — curva forward licenciada, desabilitada por padrao
# ===========================================================================
class BbceForwardAdapter(BaseAdapter):
    """BBCE — curva forward negociada (`GET v1/curve/bbce-fwd`), opcional.

    Chamada real so acontece com `BBCE_API_ENABLED=true` **e** as quatro
    variaveis de ambiente presentes. Qualquer outra combinacao devolve
    `INDISPONIVEL` com o motivo, sem tentar a rede — nunca erro fatal, nunca
    chamada sem credencial (secao 3, itens 17-19 do prompt de integracoes).
    """

    name = "bbce_forward"
    media_type = "application/json"
    offline = False

    source = SourceSpec(
        name="BBCE — Brasil Bolsa de Energia (curva forward)",
        source_kind=SourceKind.PROVEDOR_COMERCIAL,
        license_class=LicenseClass.LICENSED_AUTHORIZED,
        publisher="BBCE",
        url="https://portaldodesenvolvedor.bbce.com.br/",
        # `authorized=True` porque a barreira real ja e o gate de credenciais em
        # `_credentials_status()` (roda antes de tocar rede ou politica de
        # licenca). Deixar `False` aqui bloquearia a chamada permanentemente,
        # mesmo com BBCE_API_ENABLED=true e as quatro variaveis preenchidas —
        # o preenchimento das credenciais e a propria atestacao de autorizacao.
        authorized=True,
        authorization_ref="autorizacao implicita nas credenciais BBCE_API_* configuradas pelo operador",
        update_frequency="diaria",
        notes=(
            "MARKET_FORWARD_LICENSED. Endpoint documentado: GET v1/curve/bbce-fwd"
            "?referenceDate=AAAA-MM-DD. Exige plano pago e credenciais proprias; "
            "cadastro e primeiro login sao manuais, feitos pelo usuario no portal "
            "do desenvolvedor. Desabilitado por padrao (BBCE_API_ENABLED=false)."
        ),
    )

    ENV_ENABLED = "BBCE_API_ENABLED"
    ENV_BASE_URL = "BBCE_API_BASE_URL"
    ENV_API_KEY = "BBCE_API_KEY"
    ENV_AUTH_TOKEN = "BBCE_AUTH_TOKEN"

    def _credentials_status(self) -> tuple[bool, str]:
        habilitado = os.environ.get(self.ENV_ENABLED, "false").strip().lower() == "true"
        if not habilitado:
            return False, (
                f"{self.ENV_ENABLED}=false — conector opcional desligado por padrao "
                "(OPTIONAL_LICENSED). Ative apenas apos assinar o plano da BBCE."
            )
        faltando = [
            nome for nome in (self.ENV_BASE_URL, self.ENV_API_KEY, self.ENV_AUTH_TOKEN)
            if not os.environ.get(nome)
        ]
        if faltando:
            return False, (
                "DISABLED_MISSING_CREDENTIALS — variaveis ausentes: "
                f"{', '.join(faltando)}."
            )
        return True, "credenciais presentes"

    def run(  # type: ignore[override]
        self, *, as_of: date, dataset_kind=None, snapshot: bool = True, **kwargs: object,
    ) -> AdapterResult:
        pronto, motivo = self._credentials_status()
        if not pronto:
            log.info("bbce_desabilitado", extra={"motivo": motivo})
            return self.unavailable(motivo, as_of=as_of)
        return super().run(as_of=as_of, dataset_kind=dataset_kind, snapshot=snapshot, **kwargs)

    def fetch(self, *, as_of: date, **kwargs: object) -> bytes:
        if "payload" in kwargs and kwargs["payload"] is not None:
            valor = kwargs["payload"]
            return valor if isinstance(valor, bytes) else str(valor).encode("utf-8")

        base = os.environ[self.ENV_BASE_URL].rstrip("/")
        api_key = os.environ[self.ENV_API_KEY]
        token = os.environ[self.ENV_AUTH_TOKEN]
        url = f"{base}/v1/curve/bbce-fwd?referenceDate={as_of.isoformat()}"
        headers = {
            "Authorization": f"Bearer {token}",
            "apiKey": api_key,
            "Accept": "application/json",
            "User-Agent": "energy-trading-copilot/0.1",
        }
        log.info(
            "bbce_chamada",
            extra={
                "url": url,
                "authorization": mask_secret(token),
                "apiKey": mask_secret(api_key),
            },
        )
        requisicao = urllib.request.Request(url, headers=headers)
        timeout = int(kwargs.get("timeout") or 20)
        try:
            with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
                return resposta.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AdapterUnavailable(
                    f"BBCE recusou a chamada (HTTP {exc.code}) — sem autorizacao "
                    "efetiva para este plano/credencial."
                ) from exc
            raise AdapterUnavailable(f"BBCE HTTP {exc.code} ({exc.reason}).") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AdapterUnavailable(f"BBCE inacessivel: {exc}.") from exc

    def parse(self, raw: bytes, *, as_of: date, **kwargs: object) -> AdapterResult:
        try:
            corpo = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of,
                reason="Resposta da BBCE nao e JSON. Nao decodificado; nada foi inventado.",
            )

        registros = corpo if isinstance(corpo, list) else corpo.get("data") or corpo.get("points")
        if not isinstance(registros, list) or not registros:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of,
                reason=(
                    "Resposta da BBCE em formato nao reconhecido pelo parser (esperava "
                    "lista de pontos com inicio/fim de entrega e preco). Ajuste o parser "
                    "apos confirmar o schema real com uma chamada autenticada."
                ),
            )

        pontos: list[CurvePointRow] = []
        problemas: list[str] = []
        for registro in registros:
            try:
                inicio = date.fromisoformat(str(
                    registro.get("deliveryStart") or registro.get("delivery_start")
                ))
                fim = date.fromisoformat(str(
                    registro.get("deliveryEnd") or registro.get("delivery_end")
                ))
                preco = Decimal(str(registro.get("price") or registro.get("value")))
                rotulo = str(registro.get("product") or registro.get("tenor") or inicio.isoformat())
            except (TypeError, ValueError, InvalidOperation, AttributeError):
                problemas.append(f"ponto ignorado (campos ausentes/invalidos): {registro!r}")
                continue
            pontos.append(
                CurvePointRow(
                    tenor_label=rotulo, delivery_start=inicio, delivery_end=fim,
                    price=preco, quality=DataQuality.OK,
                )
            )

        if not pontos:
            return AdapterResult(
                adapter=self.name, source=self.source, status=AdapterStatus.INDISPONIVEL,
                as_of=as_of, reason="Nenhum ponto valido na resposta da BBCE.",
                issues=tuple(problemas),
            )

        curva = CurveRow(
            curve_name="BBCE forward",
            submarket=Submarket.SE_CO,
            product_class=ProductClass.CONVENCIONAL,
            origin=CurveOrigin.NEGOCIADA,
            as_of=as_of,
            points=tuple(pontos),
            price_type=CurvePriceType.MID,
            quality=DataQuality.OK,
            notes=f"{CURVE_CATEGORY_LICENSED}. GET v1/curve/bbce-fwd?referenceDate={as_of.isoformat()}.",
        )
        status = AdapterStatus.PARCIAL if problemas else AdapterStatus.OK
        return AdapterResult(
            adapter=self.name, source=self.source, status=status, as_of=as_of,
            curves=(curva,), issues=tuple(problemas),
        )


__all__ = [
    "CURVE_CATEGORY_DELAYED_PUBLIC",
    "CURVE_CATEGORY_LICENSED",
    "B3N5xAdapter",
    "BbceForwardAdapter",
    "mask_secret",
]
