# Metodologia de risco

Tudo em `src/copilot/quant/`, sem LLM e sem dependência externa.

## Horas do período

`MWh = MWmed × horas`, período **inclusivo** nas duas pontas, 24 h por dia civil.
O Brasil não adota horário de verão desde 2019, então não há dias de 23 ou 25 h.
Ano bissexto é tratado pelo calendário real: 2027 tem 8.760 h, 2028 tem 8.784 h.
Ignorar isso erra o notional em 0,27%.

## P&L

- **Comprado:** `PnL = MWh × (preço do cenário − preço de entrada)`
- **Vendido:** `PnL = MWh × (preço de entrada − preço do cenário)`

Comprado e vendido no mesmo contrato dão P&L exatamente oposto — testado.

## Volatilidade

- **Amostral:** desvio-padrão de log-retornos diários, `ddof=1`, mínimo de 20 retornos.
- **EWMA:** `σ²ₜ = λ·σ²ₜ₋₁ + (1−λ)·r²ₜ₋₁`, λ = 0,94 (RiskMetrics), semeada com a
  variância da primeira metade da série. Reage mais rápido a mudança de regime.

## VaR

| Método | Fórmula | Amostra mínima |
|---|---|---|
| Paramétrico | `z(α) · σ · √h · \|exposição\|` | 20 retornos |
| EWMA | idem, com σ da EWMA | 20 retornos |
| Histórico | percentil da revalorização `E·(e^(r√h) − 1)` | 60 retornos |
| Portfólio | `√(ΣᵢΣⱼ EᵢEⱼσᵢσⱼρᵢⱼ) · z · √h` | por série |

**Definição adotada** (premissa PR-03, enquanto a dúvida D-01 não é respondida):
95% de confiança, 21 dias úteis, portfólio consolidado. Confiança e horizonte
sempre aparecem no resultado — nunca ficam implícitos.

O **VaR de mercado adotado é o maior** entre paramétrico, EWMA e histórico.

Amostra curta devolve `Dados insuficientes para cálculo confiável.` — nunca um
número fraco.

## Add-ons

Somados ao VaR de mercado antes de medir o consumo do limite:

| Add-on | Conta |
|---|---|
| Liquidez | `(bid-ask/2) × exposição × √(dias para desmontar)` |
| Basis | `z · √h · σ_basis · √(1 − ρ²) × exposição` |
| **Proxy** | penalização por origem da curva: negociada 0%, interna 5%, modelo 15%, **PLD/CMO 25%** |
| Risco de modelo | 10% do VaR de mercado |

Todos os parâmetros são **premissas declaradas da mesa**, calibráveis em
`src/copilot/quant/addons.py`. Nenhum é dado de mercado observado.

## Proxy: PLD e CMO

PLD e CMO são preços de curto prazo formados por modelo de despacho, **não**
preços negociados. O sistema:

1. recusa cadastrar curva de PLD/CMO como `NEGOCIADA`;
2. exige `proxy_of` quando a origem é `PROXY_SPOT`;
3. aplica o add-on de proxy mais caro (25%);
4. mostra o aviso na interface.

Usar volatilidade histórica do PLD como volatilidade da curva forward é
explicitamente marcado como proxy no campo `warnings` do resultado.

## Limite de R$ 50 milhões

Cadastrado na tabela `risk_limits`, não no código. O consumo é medido sobre o
**VaR total** (mercado + add-ons) — medir só o VaR de mercado subestimaria
exatamente nos casos em que a marcação é por proxy ou a posição é ilíquida.

Faixa de atenção em 80%. Acima do limite, o veredito é `BLOQUEADA_POR_RISCO`.

## Margem e NPV até 31/12

`npv_to_year_end()` desconta o P&L pro rata dias até 31/12, taxa anual declarada
(padrão 10% a.a., configurável). É premissa, não observação.

## Limitações

- Raiz do tempo assume retornos i.i.d.; em energia, com sazonalidade forte, ela
  subestima cauda. É por isso que existe o add-on de risco de modelo.
- Correlação não declarada é assumida como 1,0 (caso conservador).
- Sem Monte Carlo nesta versão.
