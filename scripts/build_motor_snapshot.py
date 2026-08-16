"""Roda o pipeline PESADO do motor vendorizado e grava o snapshot congelado.

Offline, dev-only. NUNCA roda no deploy — o app so le `motor_curva/snapshots/*.json`.
Precisa de `requirements-motor-offline.txt` instalado e de `<repo>/data/raw` +
`<repo>/fixtures` populados com dado real (o import do `motor_curva.config`
vendorizado ja cria essas pastas; a populacao com dado real e manual/local e
NUNCA versionada — ver `.gitignore`).

COMO ISTO NAO REESCREVE O MOTOR
--------------------------------
`motor_curva.cli.cmd_run(args)` roda inteiro, sem nenhuma edicao. Para capturar
os ingredientes que `avaliar()` precisa (ancora, cenarios oficiais, fatores
sazonais, VaR/ES por vertice, meia-vida, manifesto) sem tocar em `cli.py`, este
script usa `sys.settrace` para ler as variaveis LOCAIS do frame de `cmd_run` no
momento em que a funcao retorna — e so isso. Zero linha do motor e alterada.
Como e a mesma execucao que escreve `outputs/resumo_execucao.json`, o snapshot
capturado e por construcao a mesma rodada, nunca uma reimplementacao paralela.

Uso:
    python scripts/build_motor_snapshot.py --submercado SE
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SNAPSHOTS_DIR = REPO_ROOT / "motor_curva" / "snapshots"
GOLDEN_DIR = REPO_ROOT / "tests" / "golden" / "motor"


def _run_cmd_run_and_capture(args: argparse.Namespace) -> dict:
    """Executa `motor_curva.cli.cmd_run(args)` e devolve os locais no retorno."""
    import motor_curva.cli as cli  # importado aqui: precisa do sys.path acima

    capturado: dict = {}

    def local_trace(frame, event, _arg):
        if event == "return" and frame.f_code.co_name == "cmd_run":
            capturado.update(frame.f_locals)
        return local_trace

    def global_trace(frame, event, _arg):
        if event == "call" and frame.f_code.co_name == "cmd_run":
            return local_trace
        return None

    sys.settrace(global_trace)
    try:
        cli.cmd_run(args)
    finally:
        sys.settrace(None)

    if "status" not in capturado:
        raise RuntimeError(
            "sys.settrace nao capturou o frame de cmd_run — verifique se "
            "motor_curva.cli ainda define uma funcao chamada exatamente cmd_run."
        )
    return capturado


def _series_to_dict(serie) -> dict[str, float]:
    import pandas as pd

    return {pd.Timestamp(idx).strftime("%Y-%m-01"): float(val) for idx, val in serie.items()}


def build_snapshot(locais: dict, *, as_of_override: str | None = None):
    import pandas as pd

    from src.motor.snapshot import MotorSnapshot

    alvo = locais["alvo"]
    sub = locais["sub"]
    status = locais["status"]
    hl = locais["hl"]
    s_fun = locais["s_fun"]
    s_saz = locais["s_saz"]
    w = locais["w"]
    ajuste_now = locais["ajuste_now"]
    efeitos = locais["efeitos"]
    var_vert = locais["var_vert"]
    es_vert = locais["es_vert"]
    bol = locais["bol"]
    man = locais["man"]

    if not bol.get("ok"):
        raise RuntimeError(
            "bol['ok'] e False: os boletins InfoPLD/IPDO nao foram lidos. "
            "Confira <repo>/fixtures — precisa dos PDFs InfoPLD e IPDO ate a data de corte."
        )

    cenarios_df = bol["cenarios"].set_index("mes_ref")
    cenarios_oficiais = {
        "Seco": {pd.Timestamp(m).strftime("%Y-%m-01"): float(cenarios_df.loc[m, "Seco"]) for m in alvo},
        "Esperado": {pd.Timestamp(m).strftime("%Y-%m-01"): float(cenarios_df.loc[m, "Esperado"]) for m in alvo},
        "Umido": {pd.Timestamp(m).strftime("%Y-%m-01"): float(cenarios_df.loc[m, "Umido"]) for m in alvo},
    }
    seco_por_estimador = bool(bol.get("diag_cen", {}).get("seco_por_estimador", False))

    manifesto_lista = man.to_dict(orient="records") if hasattr(man, "to_dict") else list(man)

    from motor_curva.config import DATA_CORTE
    from datetime import datetime, timezone

    snap = MotorSnapshot(
        schema_version=1,
        gerado_em=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        as_of=as_of_override or DATA_CORTE.isoformat(),
        submercado=sub,
        status_motor=status,
        alvo=[pd.Timestamp(m).strftime("%Y-%m-01") for m in alvo],
        s_fun=_series_to_dict(s_fun),
        s_saz=_series_to_dict(s_saz),
        w=float(w),
        ajuste_now=_series_to_dict(ajuste_now),
        cenarios_oficiais=cenarios_oficiais,
        seco_por_estimador=seco_por_estimador,
        k_seco=float(efeitos["k_seco"]),
        k_umido=float(efeitos["k_umido"]),
        var_vert=_series_to_dict(var_vert),
        es_vert=_series_to_dict(es_vert),
        hl_dias=int(hl),
        manifesto=manifesto_lista,
        notas={
            "premio_modo_gerado_com": locais.get("cal_prem") is not None,
            "trajetoria_esperado": bol.get("diag_cen", {}).get("trajetoria_esperado"),
            "trajetoria_seco": bol.get("diag_cen", {}).get("trajetoria_seco"),
            "trajetoria_umido": bol.get("diag_cen", {}).get("trajetoria_umido"),
            # "hoje" no momento da geracao — a VPL desconta ate a liquidacao a
            # partir daqui. Nao e recalculado por avaliar(); o golden test
            # precisa deste valor exato para reproduzir a VPL bit a bit.
            "hoje_geracao": locais["hoje"].isoformat(),
            "ref_mercado_geracao": {
                str(pd.Timestamp(k).date()): float(v)
                for k, v in locais["ref_mkt"].items()
            } if "ref_mkt" in locais else None,
        },
    )
    return snap


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submercado", default="SE")
    parser.add_argument("--ignorar-falhas", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    ns = parser.parse_args(argv)

    args = argparse.Namespace(
        submercado=ns.submercado, raw_dir=None, fixtures=False,
        ignorar_falhas=ns.ignorar_falhas, verbose=ns.verbose,
    )

    import os
    os.chdir(REPO_ROOT)  # PREMISSAS.dir_boletins = "fixtures" e relativo ao cwd

    print(f"Rodando motor_curva.cli.cmd_run(submercado={args.submercado!r}) — leva alguns minutos...")
    locais = _run_cmd_run_and_capture(args)
    print(f"status do run: {locais['status']}")

    snap = build_snapshot(locais)
    snapshot_hash = snap.compute_hash()
    dest = SNAPSHOTS_DIR / f"{snap.as_of}_{snapshot_hash[:12]}.json"
    snap.save(dest)
    print(f"snapshot gravado: {dest} (hash {snapshot_hash[:12]})")

    resumo_src = REPO_ROOT / "outputs" / "resumo_execucao.json"
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    resumo_dst = GOLDEN_DIR / f"resumo_execucao_{snap.as_of}.json"
    shutil.copyfile(resumo_src, resumo_dst)
    print(f"golden pinado: {resumo_dst} (copiado de {resumo_src})")

    snapshot_ref = GOLDEN_DIR / "snapshot_ref.txt"
    snapshot_ref.write_text(dest.name, encoding="utf-8")
    print(f"referencia do golden -> snapshot: {snapshot_ref} = {dest.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
