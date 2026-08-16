"""Contexto de execucao: `as_of` e `dataset_kind`.

Os dois principios que mais facilmente se perdem em codigo sao P7 (controle de
data-base) e P9 (separacao DEMO/REAL). Aqui eles viram um contextvar obrigatorio:
nenhum repositorio opera sem contexto, e todo repositorio injeta os dois
predicados sem depender de quem escreveu a consulta.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from datetime import date
from typing import Iterator

from copilot.common.enums import ActorType, DatasetKind
from copilot.common.errors import MissingContextError


@dataclass(frozen=True, slots=True)
class RunContext:
    """Contexto imutavel de uma unidade de trabalho.

    :param as_of: data-base. Nenhuma consulta enxerga dado posterior (RF-58).
    :param dataset_kind: DEMO ou REAL. Nenhuma consulta cruza os dois (RF-57).
    :param actor: quem executa — usuario, agente ou processo.
    :param run_id: correlaciona log, auditoria e execucoes do motor quant.
    """

    as_of: date
    dataset_kind: DatasetKind
    actor: str = "sistema"
    actor_type: ActorType = ActorType.SISTEMA
    run_id: str | None = None
    agent_version: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "as_of": self.as_of.isoformat(),
            "dataset_kind": self.dataset_kind.value,
            "actor": self.actor,
            "actor_type": self.actor_type.value,
            "run_id": self.run_id,
        }


_current: ContextVar[RunContext | None] = ContextVar("copilot_run_context", default=None)


def current_context() -> RunContext | None:
    """Contexto ativo, ou None."""
    return _current.get()


def require_context() -> RunContext:
    """Contexto ativo. Levanta se nao houver — nunca assume um padrao silencioso."""
    ctx = _current.get()
    if ctx is None:
        raise MissingContextError(
            "Operacao de dados sem contexto. Envolva a chamada em "
            "`with run_context(as_of=..., dataset_kind=...):` (P7, P9)."
        )
    return ctx


def set_context(ctx: RunContext) -> Token:
    """Define o contexto e devolve o token para restauracao."""
    return _current.set(ctx)


def reset_context(token: Token) -> None:
    _current.reset(token)


@contextmanager
def run_context(
    as_of: date | None = None,
    dataset_kind: DatasetKind | str | None = None,
    *,
    actor: str | None = None,
    actor_type: ActorType | None = None,
    run_id: str | None = None,
    agent_version: str | None = None,
) -> Iterator[RunContext]:
    """Abre um contexto de execucao.

    Campos omitidos herdam do contexto externo, se houver; caso contrario, das
    configuracoes (`DEFAULT_AS_OF`, `DEFAULT_DATASET_KIND`).
    """
    from copilot.config.settings import get_settings

    outer = _current.get()
    if outer is not None:
        base = outer
    else:
        settings = get_settings()
        base = RunContext(
            as_of=settings.default_as_of,
            dataset_kind=settings.default_dataset_kind,
        )

    if isinstance(dataset_kind, str):
        dataset_kind = DatasetKind(dataset_kind)

    ctx = replace(
        base,
        as_of=as_of if as_of is not None else base.as_of,
        dataset_kind=dataset_kind if dataset_kind is not None else base.dataset_kind,
        actor=actor if actor is not None else base.actor,
        actor_type=actor_type if actor_type is not None else base.actor_type,
        run_id=run_id if run_id is not None else base.run_id,
        agent_version=agent_version if agent_version is not None else base.agent_version,
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


__all__ = [
    "RunContext",
    "current_context",
    "require_context",
    "reset_context",
    "run_context",
    "set_context",
]
