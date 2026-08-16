"""Adapters: contrato, proxy declarado, snapshots e classificacao de fontes."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from copilot.common.enums import (
    AdapterStatus,
    CurveOrigin,
    CurvePriceType,
    DataQuality,
    DatasetKind,
    LicenseClass,
    ProductClass,
    SourceKind,
    Submarket,
    Unit,
)
from copilot.common.errors import ProxyNotDeclaredError, SchemaValidationError
from copilot.ingest.adapters import (
    AnaAdapter,
    AneelAdapter,
    B3N5xAdapter,
    CceeAdapter,
    ClimateAdapter,
    DemoDataAdapter,
    EnsoOniAdapter,
    ForwardCurveUploadAdapter,
    ManualObservationAdapter,
    OnsAdapter,
    classify_enso,
    looks_like_spot,
)
from copilot.ingest.contracts import AdapterResult, SourceAdapter
from copilot.ingest.registry import (
    ADAPTER_CLASSES,
    build_coverage,
    get_adapter,
    list_adapters,
    run_automatic,
)
from copilot.ingest.snapshots import SnapshotStore, payload_hash
from tests.fixtures.xlsx_writer import write_xlsx

AS_OF = date(2026, 8, 14)

CSV_CURVA = (
    "tenor,delivery_start,delivery_end,price\n"
    "A+2,2028-01-01,2028-12-31,188.50\n"
    "A+1,2027-01-01,2027-12-31,195.00\n"
).encode("utf-8")


def store(tmp: str) -> SnapshotStore:
    return SnapshotStore(Path(tmp) / "snapshots")


# ============================================================ contrato comum
def test_todos_os_adapters_cumprem_o_protocolo() -> None:
    for nome, classe in ADAPTER_CLASSES.items():
        adapter = classe()
        assert isinstance(adapter, SourceAdapter), nome
        assert adapter.name == nome
        assert adapter.source.name


def test_catalogo_declara_licenca_e_implementacao() -> None:
    catalogo = {a["name"]: a for a in list_adapters()}
    assert catalogo["enso_oni"]["implemented"] is True
    # ONS, CCEE e EPE viraram integracoes reais nesta sprint (ver
    # docs/CONEXOES_DADOS_SETOR.md); ANEEL/ANA/clima seguem interface declarada.
    assert catalogo["ons"]["implemented"] is True
    assert catalogo["ccee"]["implemented"] is True
    assert catalogo["epe"]["implemented"] is True
    assert catalogo["aneel"]["implemented"] is False
    assert catalogo["ons"]["license_class"] == LicenseClass.PUBLIC_ATTRIB.value
    assert all(a["source"] for a in catalogo.values())


def test_adapter_desconhecido() -> None:
    with pytest.raises(KeyError, match="desconhecido"):
        get_adapter("bloomberg")


# ====================================================== classificacao de fonte
def test_fontes_publicas_e_internas_estao_classificadas() -> None:
    """Toda fonte declara licenca; nenhuma entra sem classificacao."""
    assert OnsAdapter.source.license_class is LicenseClass.PUBLIC_ATTRIB
    assert AneelAdapter.source.license_class is LicenseClass.PUBLIC_OPEN
    assert EnsoOniAdapter.source.license_class is LicenseClass.PUBLIC_OPEN
    assert ForwardCurveUploadAdapter.source.license_class is LicenseClass.CONFIDENTIAL_INTERNAL
    assert ForwardCurveUploadAdapter.source.authorized is True


def test_fonte_interna_sem_autorizacao_e_rejeitada() -> None:
    """P10: sem autorizacao registrada, nao ingere — e o resultado diz por que."""
    from dataclasses import replace

    adapter = ForwardCurveUploadAdapter()
    adapter.source = replace(adapter.source, authorized=False, authorization_ref=None)
    resultado = adapter.run(as_of=AS_OF, file=CSV_CURVA, curve_name="X")
    assert resultado.status is AdapterStatus.REJEITADO
    assert "autorizacao" in (resultado.reason or "")


def test_fonte_licenciada_bloqueada_nunca_ingere() -> None:
    from dataclasses import replace

    adapter = DemoDataAdapter()
    adapter.source = replace(adapter.source, license_class=LicenseClass.LICENSED_BLOCKED)
    resultado = adapter.run(as_of=AS_OF, dataset_kind=DatasetKind.DEMO, snapshot=False)
    assert resultado.status is AdapterStatus.REJEITADO
    assert resultado.row_count == 0


# ================================================== interfaces indisponiveis
# ONS, CCEE e EPE saíram desta lista: viraram integrações reais (fazem
# requisição de rede) e são testadas offline em test_sector_connectors.py.
@pytest.mark.parametrize(
    "classe", [AneelAdapter, AnaAdapter, ClimateAdapter, B3N5xAdapter]
)
def test_interface_declarada_devolve_indisponivel_com_motivo(classe: type) -> None:
    """Fonte que falta aparece no relatorio; nao some do mapa (RF-36)."""
    resultado = classe().run(as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert resultado.reason
    assert resultado.row_count == 0
    assert not resultado.ok


def test_ccee_avisa_que_pld_nao_e_curva() -> None:
    assert "curva forward" in (CceeAdapter.source.notes or "").lower()


# ================================================== ForwardCurveUploadAdapter
def test_upload_de_curva_csv() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        adapter = ForwardCurveUploadAdapter(snapshot_store=store(tmp))
        resultado = adapter.run(
            as_of=AS_OF,
            file=CSV_CURVA,
            filename="curva.csv",
            curve_name="Curva mesa SE/CO",
            submarket=Submarket.SE_CO,
            product_class=ProductClass.CONVENCIONAL,
            origin=CurveOrigin.NEGOCIADA,
        )
    assert resultado.status is AdapterStatus.OK
    curva = resultado.curves[0]
    assert curva.is_traded
    assert curva.quality is DataQuality.OK
    assert [p.tenor_label for p in curva.points] == ["A+1", "A+2"]  # ordenado
    assert curva.points[0].price == Decimal("195.00")


def test_upload_de_curva_xlsx() -> None:
    payload = write_xlsx(
        [
            ["tenor", "delivery_start", "delivery_end", "price"],
            ["A+1", date(2027, 1, 1), date(2027, 12, 31), Decimal("195.00")],
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF,
            file=payload,
            filename="curva.xlsx",
            curve_name="Curva mesa",
            origin=CurveOrigin.NEGOCIADA,
        )
    assert resultado.curves[0].points[0].price == Decimal("195.00")


def test_tenor_duplicado_e_recusado() -> None:
    payload = (
        "tenor,delivery_start,delivery_end,price\n"
        "A+1,2027-01-01,2027-12-31,195.00\n"
        "A+1,2027-01-01,2027-12-31,196.00\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SchemaValidationError, match="repetido"):
            ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
                as_of=AS_OF, file=payload, filename="c.csv", curve_name="X",
                origin=CurveOrigin.NEGOCIADA,
            )


# ---------------------------------------------------- PLD/CMO nao e forward
@pytest.mark.parametrize(
    "nome",
    ["Curva PLD SE/CO", "pld_se_semanal", "CMO medio", "Projecao de CMO 2027"],
)
def test_pld_ou_cmo_como_curva_negociada_e_recusado(nome: str) -> None:
    """Regra dura do projeto: preco de despacho nao e preco negociado."""
    assert looks_like_spot(nome)
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ProxyNotDeclaredError, match="PROXY_SPOT"):
            ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
                as_of=AS_OF, file=CSV_CURVA, filename="c.csv",
                curve_name=nome, origin=CurveOrigin.NEGOCIADA,
            )


def test_proxy_spot_exige_declarar_o_substituido() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ProxyNotDeclaredError, match="proxy_of"):
            ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
                as_of=AS_OF, file=CSV_CURVA, filename="c.csv",
                curve_name="Curva PLD SE/CO", origin=CurveOrigin.PROXY_SPOT,
            )


def test_proxy_declarado_e_aceito_e_marcado() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, file=CSV_CURVA, filename="c.csv",
            curve_name="Curva PLD SE/CO", origin=CurveOrigin.PROXY_SPOT,
            proxy_of="pld_se_semanal",
        )
    curva = resultado.curves[0]
    assert not curva.is_traded
    assert curva.quality is DataQuality.PROXY
    assert curva.price_type is CurvePriceType.PROXY_PUBLICO
    assert curva.proxy_of == "pld_se_semanal"
    assert "nao e preco negociado" in (curva.notes or "")


def test_curva_de_nome_neutro_passa_como_negociada() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ForwardCurveUploadAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, file=CSV_CURVA, filename="c.csv",
            curve_name="Forward convencional SE/CO", origin=CurveOrigin.NEGOCIADA,
        )
    assert resultado.curves[0].is_traded


# =================================================== ManualObservationAdapter
def test_observacao_manual_por_arquivo() -> None:
    payload = (
        "metric_key,ref_date,value,unit\n"
        "ear_sudeste_pct,2026-08-13,0.47,%\n"
    ).encode("utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ManualObservationAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, file=payload, filename="obs.csv"
        )
    assert resultado.status is AdapterStatus.OK
    observacao = resultado.observations[0]
    assert observacao.metric_key == "ear_sudeste_pct"
    assert observacao.value == Decimal("0.47")
    assert observacao.unit is Unit.PERCENT
    assert observacao.as_of == AS_OF  # herdou a data-base do contexto


def test_observacao_manual_por_linhas_da_ui() -> None:
    """Caminho do dado entregue ao vivo na defesa (RF-11)."""
    linhas = [
        {
            "metric_key": "pld_se_semanal",
            "ref_date": "2026-08-14",
            "value": "231,40",
            "unit": "R$/MWh",
            "quality": "PRELIMINAR",
        }
    ]
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ManualObservationAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, rows=linhas
        )
    observacao = resultado.observations[0]
    assert observacao.value == Decimal("231.40")
    assert observacao.quality is DataQuality.PRELIMINAR


def test_pld_como_observacao_e_legitimo() -> None:
    """A restricao e sobre chamar PLD de curva forward, nao sobre observa-lo."""
    linhas = [
        {"metric_key": "pld_se_semanal", "ref_date": "2026-08-14",
         "value": "200", "unit": "R$/MWh"}
    ]
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ManualObservationAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, rows=linhas
        )
    assert resultado.status is AdapterStatus.OK


def test_observacao_manual_com_campo_faltando() -> None:
    linhas = [{"metric_key": "x", "ref_date": "2026-08-14", "unit": "%"}]
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SchemaValidationError):
            ManualObservationAdapter(snapshot_store=store(tmp)).run(as_of=AS_OF, rows=linhas)


def test_evidence_excerpt_e_gerado() -> None:
    """Geracao automatica do texto de evidencia — nunca escrito a mao."""
    linhas = [
        {"metric_key": "ear_sudeste_pct", "ref_date": "2026-08-13",
         "value": "0.47", "unit": "%"}
    ]
    with tempfile.TemporaryDirectory() as tmp:
        resultado = ManualObservationAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, rows=linhas
        )
    texto = resultado.observations[0].evidence_excerpt(resultado.source.name)
    assert "ear_sudeste_pct" in texto
    assert "0.47" in texto
    assert "2026-08-13" in texto
    assert "2026-08-14" in texto  # data-base


# ============================================================ DemoDataAdapter
def test_demo_gera_series_e_curva_proxy() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = DemoDataAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, dataset_kind=DatasetKind.DEMO, history_days=30
        )
    assert resultado.status is AdapterStatus.OK
    assert len(resultado.observations) == 6 * 30
    assert all(o.quality is DataQuality.ESTIMADO for o in resultado.observations)
    assert all("SINT" in (o.note or "") for o in resultado.observations)
    curva = resultado.curves[0]
    assert curva.origin is CurveOrigin.PROXY_MODELO
    assert not curva.is_traded


def test_demo_preserva_divergencia_entre_rodadas() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = DemoDataAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, dataset_kind=DatasetKind.DEMO, history_days=10
        )
    rodadas = {
        o.model_run for o in resultado.observations if o.metric_key == "precip_prev_7d"
    }
    assert rodadas == {"RODADA_A", "RODADA_B"}


def test_demo_recusa_dataset_real() -> None:
    """P9: dado sintetico nunca entra em REAL."""
    resultado = DemoDataAdapter().run(as_of=AS_OF, dataset_kind=DatasetKind.REAL)
    assert resultado.status is AdapterStatus.REJEITADO
    assert "DEMO" in (resultado.reason or "")


def test_demo_e_deterministico() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        a = DemoDataAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, dataset_kind=DatasetKind.DEMO, history_days=15
        )
        b = DemoDataAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, dataset_kind=DatasetKind.DEMO, history_days=15
        )
    assert [(o.metric_key, o.ref_date, o.value) for o in a.observations] == [
        (o.metric_key, o.ref_date, o.value) for o in b.observations
    ]


# =============================================================== ENSO / ONI
AMOSTRA_ONI = """  SEAS  YR  TOTAL ANOM
   DJF 2024  26.50  1.80
   JFM 2024  26.80  1.50
   FMA 2024  27.10  1.20
   MAM 2024  27.90  0.70
   AMJ 2024  27.70  0.20
   MJJ 2024  27.20 -0.10
   JJA 2024  26.90 -0.30
   JAS 2024  26.60 -0.40
   ASO 2024  26.30 -0.60
   SON 2024  26.10 -0.80
   OND 2024  25.90 -0.90
   NDJ 2024  25.80 -0.90
   DJF 2027  26.00  0.10
"""


def test_parser_do_oni() -> None:
    resultado = EnsoOniAdapter().parse(AMOSTRA_ONI.encode("utf-8"), as_of=AS_OF)
    assert resultado.status is AdapterStatus.OK
    assert len(resultado.observations) == 12  # DJF/2027 e futuro, foi cortado
    primeira = resultado.observations[0]
    assert primeira.metric_key == "enso_oni_anomaly"
    assert primeira.ref_date == date(2024, 1, 1)  # DJF -> mes central janeiro
    assert primeira.value == Decimal("1.80")
    assert primeira.unit is Unit.ADIMENSIONAL


def test_oni_nao_traz_dado_posterior_a_data_base() -> None:
    """RF-58: protecao contra look-ahead ja na ingestao."""
    resultado = EnsoOniAdapter().parse(AMOSTRA_ONI.encode("utf-8"), as_of=AS_OF)
    assert all(o.ref_date <= AS_OF for o in resultado.observations)


@pytest.mark.parametrize(
    ("anomalia", "regime"),
    [("1.80", "EL_NINO"), ("0.50", "EL_NINO"), ("0.10", "NEUTRO"),
     ("-0.50", "LA_NINA"), ("-1.20", "LA_NINA")],
)
def test_classificacao_enso(anomalia: str, regime: str) -> None:
    assert classify_enso(Decimal(anomalia)) == regime


def test_oni_ultimo_regime() -> None:
    resultado = EnsoOniAdapter().parse(AMOSTRA_ONI.encode("utf-8"), as_of=AS_OF)
    ultima = EnsoOniAdapter.latest_regime(resultado)
    assert ultima is not None
    referencia, valor, regime = ultima
    assert referencia == date(2024, 12, 1)
    assert regime == "LA_NINA"


def test_oni_linha_corrompida_vira_parcial() -> None:
    payload = (AMOSTRA_ONI + "   DJF 2025  ABC  XYZ\n").encode("utf-8")
    resultado = EnsoOniAdapter().parse(payload, as_of=AS_OF)
    assert resultado.status is AdapterStatus.PARCIAL
    assert resultado.issues


def test_oni_payload_sem_dado_e_indisponivel() -> None:
    resultado = EnsoOniAdapter().parse(b"cabecalho qualquer\n", as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert not resultado.ok


def test_oni_offline_usa_payload_injetado() -> None:
    """Sem rede, um snapshot arquivado reprocessa sem sair para a internet."""
    with tempfile.TemporaryDirectory() as tmp:
        resultado = EnsoOniAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, payload=AMOSTRA_ONI.encode("utf-8")
        )
    assert resultado.status is AdapterStatus.OK
    assert resultado.snapshot is not None


# ================================================================= snapshots
def test_snapshot_grava_payload_hash_e_metadados() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        loja = store(tmp)
        ref = loja.save(
            b"conteudo bruto",
            adapter="teste",
            as_of=AS_OF,
            dataset_kind=DatasetKind.DEMO,
            media_type="text/csv",
        )
        assert ref.payload_hash == payload_hash(b"conteudo bruto")
        assert ref.byte_size == 14
        caminho = Path(ref.storage_uri)
        assert caminho.exists()
        meta = json.loads(caminho.with_suffix(caminho.suffix + ".meta.json").read_text())
        assert meta["payload_sha256"] == ref.payload_hash
        assert meta["as_of"] == AS_OF.isoformat()
        assert loja.load(ref) == b"conteudo bruto"
        assert loja.verify(ref)


def test_snapshot_detecta_adulteracao() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        loja = store(tmp)
        ref = loja.save(
            b"original", adapter="teste", as_of=AS_OF, dataset_kind=DatasetKind.DEMO
        )
        Path(ref.storage_uri).write_bytes(b"adulterado")
        assert not loja.verify(ref)
        with pytest.raises(ValueError, match="hash divergente"):
            loja.load(ref)


def test_snapshot_ausente() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        loja = store(tmp)
        ref = loja.save(b"x", adapter="t", as_of=AS_OF, dataset_kind=DatasetKind.DEMO)
        Path(ref.storage_uri).unlink()
        assert not loja.verify(ref)


def test_todo_adapter_que_roda_produz_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = DemoDataAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, dataset_kind=DatasetKind.DEMO, history_days=5
        )
    assert resultado.snapshot is not None
    assert resultado.snapshot.payload_hash


# ================================================================= cobertura
def test_relatorio_de_cobertura_expoe_a_lacuna(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem rede (ambiente de teste), todo adapter automatico vira INDISPONIVEL
    de forma deterministica — o relatorio de cobertura precisa mostrar a
    lacuna inteira, nunca silenciar uma fonte que nao respondeu (RF-36)."""
    import urllib.error

    def sem_rede(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("rede desligada no teste")

    monkeypatch.setattr("copilot.ingest.adapters.public.urllib.request.urlopen", sem_rede)
    monkeypatch.setattr("copilot.ingest.adapters.licensed.urllib.request.urlopen", sem_rede)

    with tempfile.TemporaryDirectory() as tmp:
        resultados, cobertura = run_automatic(
            as_of=AS_OF,
            dataset_kind=DatasetKind.DEMO,
            factory=lambda n: get_adapter(n, snapshot_store=store(tmp)),
        )
    assert "enso_oni" in (cobertura.ok + cobertura.unavailable)
    assert set(cobertura.unavailable) >= {"ons", "ccee", "epe", "aneel", "ana", "climate", "b3_n5x"}
    assert cobertura.has_gap
    assert 0.0 <= cobertura.coverage_ratio <= 1.0
    assert "cobertura" in cobertura.summary()


def test_cobertura_classifica_por_status() -> None:
    resultados = [
        AdapterResult("a", DemoDataAdapter.source, AdapterStatus.OK, AS_OF),
        AdapterResult("b", DemoDataAdapter.source, AdapterStatus.PARCIAL, AS_OF),
        AdapterResult("c", DemoDataAdapter.source, AdapterStatus.INDISPONIVEL, AS_OF),
        AdapterResult("d", DemoDataAdapter.source, AdapterStatus.REJEITADO, AS_OF),
    ]
    cobertura = build_coverage(resultados, as_of=AS_OF)
    assert cobertura.ok == ("a",)
    assert cobertura.partial == ("b",)
    assert cobertura.unavailable == ("c",)
    assert cobertura.rejected == ("d",)
    assert cobertura.coverage_ratio == 0.5
