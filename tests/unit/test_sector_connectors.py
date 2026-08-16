"""Conectores do setor eletrico: ONS, CCEE, EPE, curvas licenciadas/B3/BBCE e
a curva publica de cenario estatistico. Nenhum teste aqui depende de rede —
os adapters HTTP sao exercitados via `payload=`/`parse()` direto ou com
`urlopen` substituido por um dublê determinístico.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date
from decimal import Decimal

import pytest

from copilot.common.enums import AdapterStatus, CurveOrigin, DataQuality
from copilot.common.errors import ProxyNotDeclaredError, SchemaValidationError
from copilot.ingest.adapters.licensed import (
    B3N5xAdapter,
    BbceForwardAdapter,
    mask_secret,
)
from copilot.ingest.adapters.public import CceeAdapter, EpeAdapter, OnsAdapter
from copilot.ingest.adapters.uploads import CURVE_CATEGORIES, LicensedCurveCsvAdapter
from copilot.ingest.snapshots import SnapshotStore
from tests.fixtures.xlsx_writer import write_xlsx

AS_OF = date(2026, 8, 14)


def store(tmp: str) -> SnapshotStore:
    return SnapshotStore(tmp)


# =============================================================== ONS
CSV_CARGA = (
    "id_subsistema;nom_subsistema;din_instante;val_cargaenergiamwmed\n"
    "SE;Sudeste;2026-08-01;40000.500\n"
    "N ;Norte;2026-08-01;8000.200\n"
    "SE;Sudeste;2026-08-20;99999.000\n"  # posterior ao as_of: deve ser cortado
)


def _ons_payload(csv_text: str = CSV_CARGA, dataset: str = "carga") -> bytes:
    return json.dumps({
        "as_of": AS_OF.isoformat(),
        "datasets": {dataset: {"url": "https://exemplo/x.csv", "year": "2026", "csv": csv_text}},
        "errors": [],
    }, ensure_ascii=False).encode("utf-8")


def test_ons_normaliza_submercado_e_embute_no_metric_key() -> None:
    resultado = OnsAdapter().parse(_ons_payload(), as_of=AS_OF)
    assert resultado.status is AdapterStatus.OK
    chaves = {o.metric_key for o in resultado.observations}
    assert "carga_verificada_mwmed_seco" in chaves
    assert "carga_verificada_mwmed_n" in chaves


def test_ons_protege_contra_look_ahead() -> None:
    resultado = OnsAdapter().parse(_ons_payload(), as_of=AS_OF)
    assert all(o.ref_date <= AS_OF for o in resultado.observations)
    assert len(resultado.observations) == 2  # a linha de 2026-08-20 foi cortada


def test_ons_layout_invalido_fica_parcial_ou_indisponivel() -> None:
    payload = _ons_payload("coluna_a;coluna_b\n1;2\n")
    resultado = OnsAdapter().parse(payload, as_of=AS_OF)
    assert resultado.status in (AdapterStatus.PARCIAL, AdapterStatus.INDISPONIVEL)
    assert resultado.issues or resultado.reason


def test_ons_dataset_isolado_nao_derruba_os_outros() -> None:
    """Um dataset com erro nao impede os demais de serem ingeridos."""
    payload = json.dumps({
        "as_of": AS_OF.isoformat(),
        "datasets": {
            "carga": {"url": "u", "year": "2026", "csv": CSV_CARGA},
            "ear": {"url": "u", "year": "2026", "csv": "colunas;erradas\n1;2\n"},
        },
        "errors": [],
    }).encode("utf-8")
    resultado = OnsAdapter().parse(payload, as_of=AS_OF)
    assert resultado.status is AdapterStatus.PARCIAL
    assert any(o.metric_key.startswith("carga_verificada") for o in resultado.observations)
    assert resultado.issues


def test_ons_sem_rede_fica_indisponivel(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    def falha(*args: object, **kwargs: object) -> None:
        raise urllib.error.URLError("sem rede")

    monkeypatch.setattr("copilot.ingest.adapters.public.urllib.request.urlopen", falha)
    resultado = OnsAdapter().run(as_of=AS_OF, snapshot=False)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert not resultado.ok


# =============================================================== CCEE
CSV_PLD = (
    "din_instante;nom_submercado;val_pld\n"
    "2026-08-01;SE;350.75\n"
    "2026-08-01;S;280.10\n"
)


def _ccee_payload(csv_text: str = CSV_PLD, granularity: str = "mensal") -> bytes:
    return json.dumps({
        "as_of": AS_OF.isoformat(), "granularity": granularity,
        "url": "https://exemplo/pld.csv", "year": 2026, "csv": csv_text,
    }).encode("utf-8")


def test_ccee_extrai_pld_por_submercado() -> None:
    resultado = CceeAdapter().parse(_ccee_payload(), as_of=AS_OF)
    assert resultado.status is AdapterStatus.OK
    chaves = {o.metric_key for o in resultado.observations}
    assert "pld_mensal_seco" in chaves
    assert "pld_mensal_s" in chaves


def test_ccee_pld_nunca_e_curva_forward() -> None:
    resultado = CceeAdapter().parse(_ccee_payload(), as_of=AS_OF)
    for obs in resultado.observations:
        assert "nao curva forward" in (obs.description or "").lower() or \
               "não" in (obs.description or "").lower()


def test_ccee_layout_desconhecido_fica_indisponivel() -> None:
    resultado = CceeAdapter().parse(_ccee_payload("colunas;sem;sentido\n1;2;3\n"), as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "colunas esperadas" in (resultado.reason or "").lower() \
        or "nao reconhecido" in (resultado.reason or "").lower()


def test_ccee_bloqueio_de_rede_documentado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduz o 403 do WAF verificado nesta sprint, sem depender de rede real."""
    import urllib.error

    def bloqueado(*args: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError("https://dadosabertos.ccee.org.br", 403, "Forbidden", None, None)

    monkeypatch.setattr("copilot.ingest.adapters.public.urllib.request.urlopen", bloqueado)
    resultado = CceeAdapter().run(as_of=AS_OF, snapshot=False)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "403" in (resultado.reason or "")


# =============================================================== EPE
def _epe_payload() -> bytes:
    linhas = [
        ["Data", "Regiao", "Sistema", "Classe", "TipoConsumidor", "Consumo"],
        [Decimal("20260601"), "Sudeste", "SUDESTE", "Comercial", "Cativo", Decimal("1000.5")],
        [Decimal("20260601"), "Sul", "SUL", "Industrial", "Livre", Decimal("2000.0")],
        [Decimal("20260901"), "Sudeste", "SUDESTE", "Comercial", "Cativo", Decimal("999.0")],  # futuro
    ]
    return write_xlsx(linhas, sheet_name=EpeAdapter.SHEET_NAME)


def test_epe_normaliza_consumo_mensal() -> None:
    resultado = EpeAdapter().parse(_epe_payload(), as_of=AS_OF)
    assert resultado.status is AdapterStatus.OK
    assert len(resultado.observations) == 2  # a linha de setembro foi cortada (RF-58)
    chaves = {o.metric_key for o in resultado.observations}
    assert any("comercial_cativo" in c for c in chaves)


def test_epe_planilha_sem_a_aba_esperada_fica_indisponivel() -> None:
    payload = write_xlsx([["a", "b"], [1, 2]], sheet_name="Outra aba")
    resultado = EpeAdapter().parse(payload, as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "layout" in (resultado.reason or "").lower()


def test_epe_recusa_dominio_nao_oficial() -> None:
    from copilot.common.errors import AdapterUnavailable

    adapter = EpeAdapter()
    with pytest.raises(AdapterUnavailable, match="dominio oficial|domínio oficial"):
        adapter._resolve_url(timeout=5, override="https://nao-e-epe.com/arquivo.xlsx")


def test_epe_aceita_url_override_do_dominio_oficial() -> None:
    adapter = EpeAdapter()
    url = adapter._resolve_url(timeout=5, override="https://www.epe.gov.br/x/y.xlsx")
    assert url == "https://www.epe.gov.br/x/y.xlsx"


# =============================================================== B3 / BBCE
def test_b3_nao_verificado_e_declarado() -> None:
    resultado = B3N5xAdapter().run(as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "NOT_VERIFIED" in (resultado.reason or "")


def test_bbce_desligado_por_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BBCE_API_ENABLED", raising=False)
    resultado = BbceForwardAdapter().run(as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "desligado" in (resultado.reason or "").lower()


def test_bbce_credenciais_ausentes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BBCE_API_ENABLED", "true")
    monkeypatch.delenv("BBCE_API_BASE_URL", raising=False)
    monkeypatch.delenv("BBCE_API_KEY", raising=False)
    monkeypatch.delenv("BBCE_AUTH_TOKEN", raising=False)
    resultado = BbceForwardAdapter().run(as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert "DISABLED_MISSING_CREDENTIALS" in (resultado.reason or "")


def test_bbce_nunca_chama_rede_sem_credenciais(monkeypatch: pytest.MonkeyPatch) -> None:
    chamou = {"sim": False}

    def espiao(*args: object, **kwargs: object) -> None:
        chamou["sim"] = True
        raise AssertionError("nao deveria chamar a rede sem credenciais")

    monkeypatch.setattr("copilot.ingest.adapters.licensed.urllib.request.urlopen", espiao)
    monkeypatch.delenv("BBCE_API_ENABLED", raising=False)
    BbceForwardAdapter().run(as_of=AS_OF)
    assert chamou["sim"] is False


def test_bbce_401_vira_indisponivel_sem_dado_inventado(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    monkeypatch.setenv("BBCE_API_ENABLED", "true")
    monkeypatch.setenv("BBCE_API_BASE_URL", "https://api.bbce.example")
    monkeypatch.setenv("BBCE_API_KEY", "chave-teste")
    monkeypatch.setenv("BBCE_AUTH_TOKEN", "token-teste")

    def nao_autorizado(*args: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError("https://api.bbce.example", 401, "Unauthorized", None, None)

    monkeypatch.setattr("copilot.ingest.adapters.licensed.urllib.request.urlopen", nao_autorizado)
    resultado = BbceForwardAdapter().run(as_of=AS_OF, snapshot=False)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert resultado.row_count == 0


def test_bbce_resposta_valida_e_parseada(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [
        {"deliveryStart": "2027-01-01", "deliveryEnd": "2027-12-31", "price": "199.90", "product": "A+1"},
    ]}
    resultado = BbceForwardAdapter().parse(json.dumps(payload).encode("utf-8"), as_of=AS_OF)
    assert resultado.status is AdapterStatus.OK
    curva = resultado.curves[0]
    assert curva.origin is CurveOrigin.NEGOCIADA
    assert curva.points[0].price == Decimal("199.90")


def test_bbce_resposta_em_formato_desconhecido_nao_inventa_dado() -> None:
    resultado = BbceForwardAdapter().parse(b'{"algo_inesperado": true}', as_of=AS_OF)
    assert resultado.status is AdapterStatus.INDISPONIVEL
    assert resultado.row_count == 0


def test_mask_secret_nunca_expoe_valor_completo() -> None:
    assert mask_secret("abcd1234efgh") == "ab********gh"
    assert mask_secret(None) == "(ausente)"
    assert mask_secret("ab") == "**"
    assert "abcd1234efgh" not in mask_secret("abcd1234efgh")


# =============================================================== curva licenciada manual
CSV_LICENCIADA = (
    "reference_date,delivery_start,delivery_end,submarket,energy_type,product,"
    "price_brl_mwh,source,curve_type\n"
    "2026-08-14,2027-01-01,2027-12-31,SE/CO,CONVENCIONAL,FWD_CONV,195.50,SAMPLE,MANUAL_AUTHORIZED_CURVE\n"
    "2026-08-14,2028-01-01,2028-12-31,SE/CO,CONVENCIONAL,FWD_CONV,188.00,SAMPLE,MANUAL_AUTHORIZED_CURVE\n"
)


def test_importacao_manual_de_curva_licenciada() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        resultado = LicensedCurveCsvAdapter(snapshot_store=store(tmp)).run(
            as_of=AS_OF, file=CSV_LICENCIADA.encode("utf-8"), filename="curva.csv"
        )
    assert resultado.status is AdapterStatus.OK
    curva = resultado.curves[0]
    assert len(curva.points) == 2
    assert "MANUAL_AUTHORIZED_CURVE" in (curva.notes or "")


def test_curve_type_invalido_e_recusado() -> None:
    payload = CSV_LICENCIADA.replace("MANUAL_AUTHORIZED_CURVE", "TIPO_INVENTADO")
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SchemaValidationError, match="curve_type"):
            LicensedCurveCsvAdapter(snapshot_store=store(tmp)).run(
                as_of=AS_OF, file=payload.encode("utf-8"), filename="curva.csv"
            )


def test_curve_type_cobre_as_quatro_categorias_do_prompt() -> None:
    assert set(CURVE_CATEGORIES) == {
        "MARKET_FORWARD_DELAYED_PUBLIC", "MARKET_FORWARD_LICENSED",
        "STATISTICAL_SCENARIO_PUBLIC", "MANUAL_AUTHORIZED_CURVE",
    }


def test_pld_como_curva_licenciada_e_recusado() -> None:
    payload = CSV_LICENCIADA.replace("FWD_CONV", "PLD SE/CO")
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ProxyNotDeclaredError):
            LicensedCurveCsvAdapter(snapshot_store=store(tmp)).run(
                as_of=AS_OF, file=payload.encode("utf-8"), filename="curva.csv"
            )
