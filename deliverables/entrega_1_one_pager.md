# Energy Trading Copilot — Entrega 1

## Problema

Não é falta de dado. É excesso de dado processado por um método que carrega viés
e não escala. A tese nasce numa conversa, as premissas ficam na cabeça de quem
teve a ideia, e quando o cenário vira ninguém reconstrói por que a posição existia
nem qual dado deveria ter disparado a reavaliação três semanas antes do prejuízo.

## Usuário

Trader da mesa de comercialização. Time pequeno, ciclo curto, decisão diária.

## Solução

Mesa virtual com três funções: **Registrar** a tese de forma estruturada e
auditável, **Desafiar** com debate adversarial antes de aceitá-la, e **Vigiar**
automaticamente as premissas contra o mercado.

## Arquitetura

Monolito local: Streamlit + SQLite (stdlib) + FTS5 para RAG + motor quantitativo
em Python puro. Cinco agentes como classes Python. O LLM redige e interpreta;
banco, RAG e Python decidem qual é o número.

## Registrar

Tese com premissas mensuráveis, posição dimensionada (MWh calculado das horas do
período), fontes com `evidence_id`, riscos, gatilhos avaliáveis por máquina,
condição de saída e de invalidação. Versionada e imutável após aprovação.

## Desafiar

Quatro etapas, no máximo quatro chamadas ao LLM: tese → contestação → verificação
→ veredito. O Agente de Risco é segunda linha independente e tem veto. Vieses
medidos por critério numérico, não por opinião do modelo. Sete vereditos possíveis,
decididos por função pura.

## Vigiar

Watchdog determinístico via script (`--once` / `--interval`) ou interface, usando
a mesma camada de serviço. Avalia gatilhos, reavalia premissas contra a faixa de
tolerância, recalcula VaR, verifica freshness e emite alerta persistente com o
dado que o disparou e a explicação de por que reavaliar.

## Controles contra alucinação

Nenhum número factual vem do LLM. Todo valor tem `evidence_id`, fonte, unidade e
data-base. O Claim Verifier é *fail-closed* e faz cinco checagens: número órfão,
lastro, existência da evidência, data-base posterior ao corte, e recomputação do
valor. Número correto por acaso, sem `evidence_id`, também é bloqueado.

PLD e CMO não são tratados como curva forward negociada: se usados como
referência, são declarados como proxy e penalizados com add-on de 25% no risco.

## O que ficou de fora

Multiusuário, embeddings, PostgreSQL, integrações públicas ao vivo (as interfaces
estão declaradas e visíveis como indisponíveis, para que a lacuna apareça),
Monte Carlo e otimização de portfólio.

## Com mais duas semanas

Integração real com ONS e CCEE promovida a `LIVE_VALIDATED`; síntese multi-fonte
de cenário com divergência entre rodadas explicitada; post-mortem automatizado
decompondo resultado entre tese, carrego e mercado.
