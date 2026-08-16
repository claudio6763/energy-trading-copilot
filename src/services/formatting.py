"""Formatacao pt-BR e badges de natureza — reutilizados pelas telas novas.

Regra do layout (PROMPT_FINAL_COPILOTO.md): ponto para milhar, virgula para
decimal. `355.296 MWh` ou `355,3 GWh`, nunca `355,296 MWh`. Todo numero
mostra o rotulo de natureza; nunca um MWm unico sem o ladder ao lado.
"""

from __future__ import annotations

from typing import Any

_PLACEHOLDER = "\x00"


def _ptbr(valor: float, casas: int) -> str:
    """`{:,.Nf}` estilo EUA ("1,234,567.89") com separadores trocados para
    pt-BR ("1.234.567,89"). Placeholder intermediario evita colisao na troca."""
    texto = f"{float(valor):,.{casas}f}"
    texto = texto.replace(",", _PLACEHOLDER)
    texto = texto.replace(".", ",")
    texto = texto.replace(_PLACEHOLDER, ".")
    return texto


def fmt_num(valor: Any, casas: int = 2) -> str:
    if valor is None:
        return "—"
    return _ptbr(float(valor), casas)


def fmt_money(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"R$ {_ptbr(float(valor), 2)}"


def fmt_money_mi(valor: Any) -> str:
    """Compacto, para KPI: `R$ 29,89 mi`."""
    if valor is None:
        return "—"
    return f"R$ {_ptbr(float(valor) / 1_000_000, 2)} mi"


def fmt_mwh(valor: Any) -> str:
    """MWh sempre em milhar com ponto, zero casa decimal (energia e inteira aqui)."""
    if valor is None:
        return "—"
    return f"{_ptbr(float(valor), 0)} MWh"


def fmt_gwh(valor_mwh: Any) -> str:
    if valor_mwh is None:
        return "—"
    return f"{_ptbr(float(valor_mwh) / 1000, 1)} GWh"


def fmt_mwm(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"{_ptbr(float(valor), 0)} MWm"


def fmt_pct(valor: Any, casas: int = 2) -> str:
    if valor is None:
        return "—"
    return f"{_ptbr(float(valor) * 100, casas)}%"


def fmt_rs_mwh(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"R$ {_ptbr(float(valor), 2)}/MWh"


#: Taxonomia do case (CLAUDE.md / motor_curva/config.py:Rotulo).
NATURE_BADGES: dict[str, str] = {
    "OBSERVADO": "🟢 OBSERVADO",
    "CALCULADO": "🔵 CALCULADO",
    "PREMISSA": "🟠 PREMISSA",
    "PROXY": "🟡 PROXY",
    "FAIR_VALUE": "🟣 FAIR_VALUE",
}


def nature_badge(natureza: str | None) -> str:
    if not natureza:
        return "—"
    return NATURE_BADGES.get(natureza, natureza)


#: Badge para texto gerado por IA — distinto de numero e de texto do trader.
IA_BADGE = "🤖 gerado por IA — verificar"
TRADER_BADGE = "✍️ escrito pelo trader"


__all__ = [
    "IA_BADGE", "NATURE_BADGES", "TRADER_BADGE", "fmt_gwh", "fmt_money",
    "fmt_money_mi", "fmt_mwh", "fmt_mwm", "fmt_num", "fmt_pct", "fmt_rs_mwh",
    "nature_badge",
]
