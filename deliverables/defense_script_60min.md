# Roteiro da defesa — 60 minutos

## 0. Antes de começar (5 min, sozinho)

```bash
python scripts/init_db.py && python scripts/seed_demo.py
python scripts/verify_agent.py     # precisa retornar 0
streamlit run app.py
```

Deixe aberto: a aplicação, um terminal e o `case_compliance_matrix.md`.

## 1. Demonstração do protótipo (15 min)

| Tempo | O que mostrar | Onde |
|---|---|---|
| 2 min | O problema em uma frase e as três funções | Dashboard |
| 4 min | **Registrar** uma tese ao vivo, com o dado que a banca der | Teses → Cadastrar |
| 1 min | Premissa sem `evidence_id` é recusada | Teses → Adicionar premissa |
| 4 min | **Desafiar**: rodar o debate, ler a contestação do Risco | Debate |
| 1 min | Veredito e por que ele é determinístico | Debate |
| 3 min | **Vigiar**: simular atualização, ver alerta e explicação | Monitor |

**Momento mais forte:** clique em qualquer número e mostre o `evidence_id`, a
fonte e a data-base. Depois abra a auditoria e mostre que ela não pode ser
editada.

## 2. Posição e produto estruturado (20 min)

| Tempo | Conteúdo |
|---|---|
| 8 min | Tese em 5 linhas, dimensionamento, consumo do limite de R$ 50 mi |
| 5 min | Cenários seco/base/úmido/extremo e o que muda na tese em cada um |
| 3 min | Margem/NPV até 31/12 |
| 4 min | Produto estruturado: payoff, cliente, proteção da mesa, risco residual |

Abra a planilha com fórmulas visíveis. Não há valor colado.

## 3. Discussão aberta (25 min)

Perguntas prováveis e onde está a resposta:

| Pergunta | Resposta |
|---|---|
| "Como sei que esse número não foi inventado?" | Clique nele. `evidence_id`, fonte, data-base. Mostre o Claim Verifier bloqueando um número órfão |
| "Qual a definição do seu VaR?" | 95%, 21 dias úteis, consolidado. É premissa PR-03 — a dúvida D-01 foi enviada à banca |
| "Você usou PLD como curva forward?" | Não. O sistema recusa. Se usado como proxy, paga add-on de 25% |
| "E se a fonte cair?" | Alerta de cobertura. Ausência de dado não é premissa válida |
| "Onde a IA erra?" | `ai_error_log.md` — quatro erros reais, com teste que pegou cada um |
| "Por que não usou embeddings?" | Norma tem jargão fixo e numeração; busca densa erra referência. ADR-012 |
| "Isso escala?" | Não como está. É SQLite local. A camada SQLAlchemy existe para migrar a PostgreSQL |

**Postura:** o case avalia capacidade de revisar diante de evidência nova. Se um
número for contestado com razão, abra o cálculo e recalcule ao vivo — o motor
quant é determinístico e roda em segundos.
