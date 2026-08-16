# Catálogo de fontes

> **09/08/2026 — ver `docs/CONEXOES_DADOS_SETOR.md` para o estado atual e
> completo.** Este documento descrevia o estado do Sprint 2 (nenhuma fonte
> `LIVE_VALIDATED`); ONS e EPE já foram validados com chamada real desde
> então. Mantido por histórico; a matriz de fontes canônica é a do documento
> novo.

## Status das integrações

| Status | Significa |
|---|---|
| `LIVE_VALIDATED` | Chamada real feita, schema validado, observação persistida, fonte e horário registrados |
| `MANUAL_IMPORT` | Adapter existe; entra por upload ou execução manual |
| `LOCAL_SNAPSHOT` | Servido de arquivo local congelado |
| `DEMO` | Dado sintético do seed |
| `NOT_CONFIGURED` | Interface declarada, implementação pendente |
| `ERROR` | Última tentativa falhou |

Uma fonte **só** é promovida a `LIVE_VALIDATED` depois dos cinco passos acima.
Nenhuma está assim nesta versão: não houve chamada real validada.

## Catálogo

| Fonte | Instituição | Status | Uso | Observação |
|---|---|---|---|---|
| ONS | ONS | `NOT_CONFIGURED` | EAR, ENA, carga, geração, restrições | Portal de dados abertos; falta fixar o dataset e o layout |
| CCEE | CCEE | `NOT_CONFIGURED` | PLD, regras de comercialização | Mistura área pública e de agente; PLD é spot, **nunca** curva forward |
| ANEEL | ANEEL | `NOT_CONFIGURED` | Resoluções, dados de geração | Alimenta o acervo do RAG |
| ANA | ANA | `NOT_CONFIGURED` | Vazões, níveis de reservatório | HidroWeb exige seleção por estação |
| EPE | EPE | `NOT_CONFIGURED` | Planejamento, balanço | Publicações abertas |
| INMET | INMET | `NOT_CONFIGURED` | Precipitação, temperatura | Requer mapeamento de estação |
| CPTEC/INPE | INPE | `NOT_CONFIGURED` | Previsão por rodada | Divergência entre rodadas preservada |
| **NOAA CPC** | NOAA | `MANUAL_IMPORT` | ONI / ENSO | **Adapter implementado e testado**; vira `LIVE_VALIDATED` com rede |
| ECMWF | ECMWF | `NOT_CONFIGURED` | Ensembles | Parte licenciada |
| BBCE | BBCE | `NOT_CONFIGURED` | Curva negociada | **LICENCIADO** — bloqueado sem autorização escrita |
| DCIDE | DCIDE | `NOT_CONFIGURED` | Curva indicativa | **LICENCIADO** — bloqueado sem autorização escrita |
| Simulação da mesa | Interna | `DEMO` | Seed e botão de simulação | Sintético, rotulado |

## ENSO / ONI — a integração funcional

`src/copilot/ingest/adapters/public.py` implementa o adapter do Oceanic Niño
Index do NOAA CPC: endpoint público, estável há décadas, texto de largura fixa,
sem chave de API.

Por que importa numa mesa brasileira: El Niño e La Niña deslocam o regime de
chuva no Sul e no Sudeste, e portanto a afluência, o despacho térmico e o preço.
Não é previsão de preço — é condicionante de cenário hidrológico.

Sem rede, o adapter aceita `payload=` com um snapshot arquivado e reprocessa sem
sair para a internet.

## Preservação de divergência entre modelos

Cada rodada meteorológica vira uma série própria (`model_run`). **Nunca** se
calcula média antes de armazenar: divergência entre modelos é informação, não
ruído a ser suavizado.

## Dados licenciados

BBCE e DCIDE ficam bloqueados na ingestão, não filtrados na saída. Não use dados
confidenciais ou licenciados de empregadores.
