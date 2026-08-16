# Manual do usuário

## 1. Iniciar a aplicação

```bash
streamlit run app.py
```

Abre em <http://localhost:8501>. Se a barra lateral mostrar **MODO
DEMONSTRAÇÃO**, os textos dos agentes são roteiros determinísticos — não são IA.
Os números continuam reais (vêm do banco e do motor quantitativo).

## 2. Dashboard

Mostra teses, alertas abertos, consumo do limite de VaR, fontes atrasadas, curva
forward e observações recentes. Curva com origem diferente de `NEGOCIADA` aparece
com aviso: não é preço negociado.

## 3. Cadastrar uma tese

**Teses → Cadastrar.** Campos obrigatórios: título, resumo (até 5 linhas),
direção, produto, submercado, fonte de energia, responsável.

Preencha também: período de entrega, volume em MWmed, preço de referência e a
data do preço, horizonte, data de reavaliação, intervalo de resultado esperado
(baixo/central/alto), condição de saída e condição de invalidação.

O sistema recusa: resumo com mais de 5 linhas, resultado esperado como número
único, e intervalo fora de ordem.

## 4. Premissas

**Teses → Consultar → Adicionar premissa.** Toda premissa exige `evidence_id` —
sem lastro, nada é gravado. Informe a **métrica vigiável** (ex.: `ear_sudeste_pct`)
e a faixa de tolerância: é isso que permite ao Watchdog avaliá-la. Premissa sem
métrica é aceita, mas fica marcada `NAO_MONITORAVEL`.

## 5. Posição

O MWh é **calculado**, nunca informado: `MWh = MWmed × horas do período`. O
sistema mostra as horas usadas (8.760 em ano comum, 8.784 em bissexto).

## 6. Saída e invalidação

Registre as duas como texto e **também** como gatilhos (métrica, operador,
limiar). Sem gatilho avaliável por máquina, o Watchdog não consegue vigiar.

## 7. Calcular risco e cenários

**Teses → Consultar → Calcular risco e cenários.** Devolve VaR paramétrico,
EWMA e histórico, add-ons, VaR total, consumo do limite e os quatro cenários
(seco, base, úmido, extremo).

## 8. Debate

**Debate → Executar debate.** Quatro etapas, no máximo quatro chamadas ao LLM.

## 9. Ler a contestação do Risco

O Agente de Risco entrega: contra-argumento, premissa mais frágil, cenário de
perda, risco de cauda, VaR, consumo do limite, sizing recomendado e dados
ausentes. Ele é a segunda linha — se concordar com tudo, algo está errado.

## 10. Interpretar o veredito

| Veredito | Significa |
|---|---|
| `COMPRAR` / `VENDER` | Risco dentro do limite, cenários calculados, gatilhos registrados |
| `MANTER` | Falta condição de saída ou de invalidação; complete antes de executar |
| `REDUZIR` | Consumo ≥ 80% do limite: reduzir sizing |
| `REESTRUTURAR` | Todos os cenários não-estresse dão perda |
| `NAO_OPERAR_DADOS_INSUFICIENTES` | Claim Verifier bloqueou, ou risco não pôde ser calculado |
| `BLOQUEADA_POR_RISCO` | VaR acima de R$ 50 milhões — veto do Agente de Risco |

## 11. Réplica e nova rodada

Escreva a réplica e clique em **Registrar réplica**. Execute o debate de novo:
a rodada é incrementada e **o histórico anterior é preservado**.

## 12. Gatilhos

Cada gatilho tem métrica, operador (`>`, `>=`, `<`, `<=`, `delta_pct`), limiar,
unidade, janela e severidade. Severidade `CRITICO` move a tese para `EM_REVISAO`
automaticamente.

## 13. Watchdog

Pela interface: **Monitor → Executar Watchdog agora**.
Pelo terminal, sem a interface aberta:

```bash
python scripts/run_watchdog.py --once
python scripts/run_watchdog.py --interval 300
```

Os dois usam a mesma camada de serviço.

## 14. Simular atualização de mercado

**Monitor → Simular atualização de mercado.** Insere uma observação
demonstrativa, dispara o gatilho, recalcula o risco, cria o alerta e registra na
auditoria. O dado entra classificado como `demonstracao` — nunca se confunde com
dado real.

## 15. Reconhecer alertas

Todo alerta traz o dado que o disparou, o `evidence_id` e a explicação de por que
a tese precisa ser reavaliada. Reconhecer exige **decisão** (MANTER, AJUSTAR,
ENCERRAR) e **justificativa** — sem justificativa o sistema recusa.

## 16. Histórico e auditoria

**Debate → Histórico de rodadas** e **Dados e fontes → Auditoria**. A trilha é
append-only: não pode ser editada nem apagada, nem pela aplicação.

## 17. Dados e fontes

**Dados e fontes** permite: importar CSV/XLSX, importar PDF para o acervo,
consultar freshness, pesquisar no RAG e ver o status das integrações.

## 18. Entrega 2

A Entrega 2 só pode ser gerada **depois** que o agente for aprovado:

```bash
python scripts/verify_agent.py          # precisa retornar 0
python scripts/freeze_case_snapshot.py --as-of 2026-08-14
python scripts/build_deliverables.py
python scripts/verify_entrega_2.py
```

Enquanto os dados reais de 14/08/2026 não existirem, o repositório traz
`READY_FOR_ENTREGA_2.md` com o comando exato e a lista do que precisa ser
carregado. **Nenhum dado demonstrativo é apresentado como posição oficial.**
