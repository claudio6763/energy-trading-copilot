# READY_FOR_ENTREGA_2

O agente está aprovado (`AGENT_READY.md`) e o pipeline da Entrega 2 está
implementado e testado. **A posição oficial ainda não foi gerada** — e não pode
ser, honestamente, pelo motivo abaixo.

## Por que ainda não

O corte oficial do case é **14/08/2026**. Hoje é **08/08/2026**. Os dados de
mercado dessa data-base ainda não existem. Gerar a posição agora significaria
usar dados demonstrativos e apresentá-los como leitura real do mercado — o
contrário do que este produto existe para impedir.

O banco contém hoje apenas observações classificadas como `demonstracao`, e
`verify_entrega_2.py` recusa a entrega enquanto não houver observação `observado`
ou `negociado`.

## O que já está pronto e testado

- Cadastro da tese com todos os campos exigidos pela Entrega 2
- Motor de risco: VaR paramétrico, EWMA, histórico, add-ons, consumo do limite
- Quatro cenários hidrológicos com P&L, impacto no VaR e o que muda na tese
- Margem/NPV até 31/12
- Debate com veredito e Claim Verifier
- Planilha aberta com 8 abas e 44 fórmulas vivas (`deliverables/entrega_2_modelo.xlsx`)
- Geração e validação de PDF com limite de 2 páginas

## Como gerar a posição oficial em 14/08/2026

```bash
# 1. Carregar os dados reais da data-base (curva negociada, PLD, EAR, ENA, carga)
#    pela interface: Dados e fontes → Importar CSV/XLSX
#    Classificação obrigatória: 'negociado' ou 'observado'. NUNCA 'demonstracao'.

# 2. Congelar o snapshot da data-base
python scripts/freeze_case_snapshot.py --as-of 2026-08-14

# 3. Cadastrar a tese no aplicativo (Teses → Cadastrar) e rodar o debate
streamlit run app.py

# 4. Gerar a posição a partir do que o agente produziu
python scripts/build_entrega_2.py --as-of 2026-08-14 --thesis-id <ID_DA_TESE>

# 5. Gerar os documentos e validar
python scripts/build_deliverables.py
python scripts/verify_entrega_2.py     # precisa retornar 0
```

## Pré-condições que `verify_entrega_2.py` exige

1. `AGENT_READY.md` existe
2. Há observação real no banco (`observado` ou `negociado`), não só demonstrativa
3. `entrega_2_posicao.md`, `.pdf` e `entrega_2_modelo.xlsx` existem
4. O PDF tem no máximo 2 páginas
5. O documento não contém a palavra "DEMONSTRAÇÃO"
6. O documento traz: tese, dimensionamento, VaR, horizonte, data de reavaliação,
   condição de saída, invalidação, premissas, fontes, cenários e NPV
7. A planilha tem as 8 abas, ≥ 30 fórmulas e nenhuma célula `PREENCHER`

## O que a Entrega 2 precisará conter

- Tese em até 5 linhas
- Dimensionamento e quanto do limite de R$ 50 milhões consome
- Resultado esperado como intervalo
- Horizonte e data de reavaliação
- Gatilhos de saída e o que invalidaria a tese
- Premissas com fonte
- Pelo menos dois cenários hidrológicos com P&L, impacto no VaR e o que muda
- Margem/NPV até 31/12
- Documento de até 2 páginas + planilha aberta
