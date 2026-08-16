"""Configuração central, constantes regulatórias e taxonomia de dados.

TAXONOMIA (exigida pelo case — todo número do projeto carrega um destes rótulos):
  OBSERVADO   dado publicado por fonte oficial, sem transformação de valor
  CALCULADO   derivado deterministicamente de OBSERVADO por código auditável
  PREMISSA    escolha do analista, declarada, com justificativa
  PROXY       preço público de transação usado como aproximação (MVE)
  FAIR_VALUE  estimativa de valor justo produzida pelo modelo
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIR_RAW = RAIZ / "data" / "raw"
DIR_PROC = RAIZ / "data" / "processed"
DIR_OUT = RAIZ / "outputs"
DIR_FIX = RAIZ / "fixtures"
for _d in (DIR_RAW, DIR_PROC, DIR_OUT):
    _d.mkdir(parents=True, exist_ok=True)

DATA_CORTE = date(2026, 8, 14)
FIM_HORIZONTE = date(2026, 12, 31)

NOME_CURVA = "Curva Publica de Referencia Fundamental e Estatistica - Energia Convencional Flat - SE/CO"

class Rotulo:
    OBSERVADO = "OBSERVADO"
    CALCULADO = "CALCULADO"
    PREMISSA = "PREMISSA"
    PROXY = "PROXY"
    FAIR_VALUE = "FAIR_VALUE"

# ---------------------------------------------------------------- regulatorio
# ANEEL - limites do PLD. Fonte primaria: REN/Despacho anual da ANEEL.
LIMITES_PLD = {
    2021: {"min": 49.77, "max_estrutural": 583.88, "max_horario": 1197.42},
    2022: {"min": 55.70, "max_estrutural": 646.58, "max_horario": 1326.35},
    2023: {"min": 69.04, "max_estrutural": 684.73, "max_horario": 1404.14},
    2024: {"min": 61.07, "max_estrutural": 709.89, "max_horario": 1455.74},
    2025: {"min": 62.59, "max_estrutural": 741.16, "max_horario": 1520.86},
    2026: {"min": 57.31, "max_estrutural": 785.27, "max_horario": 1611.04},
}

SUBMERCADOS = {"SE": "SE/CO", "S": "Sul", "NE": "Nordeste", "N": "Norte"}

MAPA_SUB = {
    "se": "SE", "seco": "SE", "se/co": "SE", "sudeste": "SE", "sudeste/centro-oeste": "SE",
    "sudeste/centrooeste": "SE", "sudeste / centro-oeste": "SE", "1": "SE", "sudeste_centrooeste": "SE",
    "s": "S", "sul": "S", "2": "S",
    "ne": "NE", "nordeste": "NE", "3": "NE",
    "n": "N", "norte": "N", "4": "N",
}

# ------------------------------------------------------------------- datasets
@dataclass(frozen=True)
class Fonte:
    chave: str
    instituicao: str
    portal: str
    dataset: str
    descricao: str
    frequencia: str
    obrigatoria: bool = True
    filtro_recurso: str | None = None

CKAN_CCEE = "https://dadosabertos.ccee.org.br"
CKAN_ONS = "https://dados.ons.org.br"

FONTES: list[Fonte] = [
    Fonte("pld_horario", "CCEE", CKAN_CCEE, "pld_horario",
          "PLD horario por submercado (DESSEM, 2021+) e historico semanal 2001-2020",
          "diaria/mensal", True),
    Fonte("mve", "CCEE", CKAN_CCEE, "mve_resultado_compra_venda",
          "Resultado de compra e venda do Mecanismo de Venda de Excedentes (MVE)",
          "por evento", False),
    Fonte("ena_diario", "ONS", CKAN_ONS, "ena-diario-por-subsistema",
          "Energia Natural Afluente diaria por subsistema, incl. %MLT",
          "diaria", True),
    Fonte("ear_diario", "ONS", CKAN_ONS, "ear-diario-por-subsistema",
          "Energia Armazenada diaria por subsistema, incl. %EARmax",
          "diaria", True),
    Fonte("cmo_semanal", "ONS", CKAN_ONS, "custo-marginal-de-operacao-semanal",
          "CMO semanal por subsistema e patamar - saida oficial publicada da cadeia NEWAVE/DECOMP",
          "semanal", False),
    Fonte("carga_diaria", "ONS", CKAN_ONS, "carga-energia-diaria",
          "Carga de energia diaria por subsistema", "diaria", False),
]

# --------------------------------------------------------------- premissas
@dataclass
class Premissas:
    """Toda premissa do projeto vive aqui e e exportada para a aba Premissas."""
    submercado: str = "SE"
    produto: str = "Convencional Flat mensal SE/CO"
    meias_vidas_teste: tuple[int, ...] = (180, 365, 730, 1460)
    # 36 meses, nao 24. A selecao fora da amostra sobre a FORMA da curva (nivel
    # removido) cai 12% ao passar de 24 para 36 meses. Com 24 meses ha so duas
    # observacoes por mes calendario, e o estimador fica dominado por ruido.
    # 36 meses a partir de ago/26 comeca em ago/2023 — inteiramente dentro do
    # regime de PLD horario/DESSEM, entao o argumento estrutural e preservado.
    janela_sazonal_meses: int = 36
    kernel_calendario_dias: int = 21          # vizinhanca circular em torno do mes-alvo
    winsor: tuple[float, float] = (0.01, 0.99)
    var_confianca: float = 0.95
    var_horizonte_du: int = 21              # so para o challenger sobre spot
    var_horizonte_meses: float = 1.0        # horizonte do VaR a termo
    var_lambda_ewma: float = 0.94           # diario (challenger spot)
    # VaR principal: vol do NIVEL dessazonalizado, amortecida ate a entrega.
    # O backcast do proprio modelo passa o nivel por uma EWMA de 6 meses e mede
    # a volatilidade do suavizador, nao a do mercado — vira PISO declarado.
    var_metodo: str = "nivel_amortecido"    # nivel_amortecido | backcast_modelo
    lambda_forward: float = 0.90            # mensal (metodo principal)
    n_origens_forward: int = 60             # datas passadas remarcadas a mercado
    meia_vida_nivel_meses: float = 6.0      # EWMA do nivel dessazonalizado
    # --- boletins (InfoPLD / IPDO)
    dir_boletins: str = "fixtures"          # onde procurar os PDFs
    trajetoria_central: str = "RNA"         # cenario Esperado
    peso_ancora_infopld: float = 0.70       # peso da ancora fundamental na curva
    nowcast_meia_vida_meses: float = 1.5    # decaimento da surpresa do IPDO
    premio_basis_rs_mwh: float = 0.0        # legado; substituido por premio calibrado
    # --- referencia de mercado (leitura de mesa, PREMISSA sem identificacao de fonte)
    # leitura de mesa na DATA DE CORTE (14/08/2026)
    ref_mercado: dict = field(default_factory=lambda: {
        "2026-08": 142.00, "2026-09": 178.00, "2026-10": 232.50,
        "2026-11": 290.00, "2026-12": 310.00})
    premio_modo: str = "visao_propria"      # visao_propria | mercado_consistente | sem_premio
    limiar_sinal_rs: float = 15.0           # abaixo disso e ruido do modelo
    auto_limiar: bool = True                # limiar calibrado pelo residuo do premio
    k_sigma_limiar: float = 1.0             # quantos desvios-padrao viram sinal
    custo_execucao_rs: float = 5.0          # piso do limiar: spread de tela
    executar_como_spread: bool = False       # neutraliza o nivel do book
    dimensionar_pelo_var: bool = True     # o VaR define o MWm de cada vertice
    modo_sinal: str = "direcional_premio"      # valor_relativo | direcional_premio | modelo_vs_mercado
    mwmed_por_perna: float = 30.0           # tamanho padrao de cada perna mensal
    mwm_maximo_operacional: float = 250.0   # teto de liquidez, independente do VaR
    frac_stress: float = 0.80               # do limite, para a perda em cenario adverso
    # RISCO CONSUMIDO = SO O VaR.
    # O case deu o VaR como unica restricao. Antes o dimensionamento usava
    # MAX(perda no cenario adverso, VaR de marcacao), o que e mais conservador
    # mas mistura duas medidas com horizontes diferentes: o VaR e de 1 mes de
    # remarcacao, a perda de cenario e de carregar ate a entrega. Somar ou
    # maximizar entre elas nao tem interpretacao unica de limite.
    # A perda de cenario continua calculada e visivel, como informacao de
    # stress — mas nao dimensiona e nao consome limite.
    risco_so_var: bool = True
    var_orcamento_frac: float = 0.60          # so 60% do teto e utilizavel
    limite_var_brl: float = 50_000_000.0
    taxa_desconto_aa: float = 0.1400          # Selic 14,00% a.a. (BCB, 06/08/2026) - PREMISSA
    edge_minimo_rs_mwh: float = 15.0          # gatilho de conviccao
    prob_cenarios: dict = field(default_factory=lambda: {"base": 0.50, "seco": 0.25, "umido": 0.25})
    quantil_seco: float = 0.25                # ENA %MLT abaixo deste quantil = seco
    quantil_umido: float = 0.75

PREMISSAS = Premissas()
