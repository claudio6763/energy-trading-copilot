# Prompt para o Claude Code — integrar Entrega 2 dentro da Entrega 1

> Cole o bloco inteiro. Antes, garanta que o Claude Code enxerga os dois
> diretórios. Se abriu só no projeto do copiloto, rode:
>
> ```
> /add-dir C:\Users\claud\OneDrive\Área de Trabalho\projeto_curva_v4
> ```

---

Vamos consertar o copiloto. Ele roda, mas a tela de cadastrar tese está vazia de
conteúdo: é um formulário de texto. Numa mesa de energia uma tese **é uma
posição** — sem book, sem dimensionamento e sem risco, não é tese, é opinião.

Não comece a escrever código. Primeiro me responda o plano.

## Os dois diretórios

| | |
|---|---|
| **Copiloto (Entrega 1)** | este projeto |
| **Motor (Entrega 2)** | `C:\Users\claud\OneDrive\Área de Trabalho\projeto_curva_v4` |

O motor é a **fonte da verdade** e acabou de rodar com dado real: status
`DEFINITIVO`. Leia `outputs/resumo_execucao.json` e os CSV de `outputs/`.

**Não reescreva o motor.** Ele tem 74 testes que são cicatrizes de bugs reais.
Se achar que precisa mudar `risco.py`, `premio.py`, `book.py`, `ancora.py`,
`cenarios.py` ou `sazonalidade.py`, pare e me pergunte.

## O erro central que você precisa corrigir

Hoje a tese é texto. Passa a ser **book + narrativa**, com o book vindo do motor.

O modelo de dados da tese precisa ter uma lista de pernas. Este é o book real
que o motor produziu — cinco produtos **mensais** distintos:

| vértice | lado | MWm | horas | MWh | entrada R$/MWh |
|---|---|---|---|---|---|
| ago/26 | VENDIDO | 43 | 744 | 31.992 | 142,00 |
| set/26 | VENDIDO | 188 | 720 | 135.360 | 178,00 |
| out/26 | VENDIDO | 119 | 744 | 88.536 | 232,50 |
| nov/26 | VENDIDO | 74 | 720 | 53.280 | 290,00 |
| dez/26 | VENDIDO | 62 | 744 | 46.128 | 310,00 |

Agregados: **355,296 GWh**, notional **R$ 78.972.444**, preço médio **222,27
R$/MWh** ponderado por MWh, VaR **R$ 29.892.814,54** = **59,79%** do limite de
R$ 50 milhões.

**Nunca some MWm entre meses.** MWm é potência; 43 de agosto e 188 de setembro
nunca coexistem, e somar conta a mesma potência cinco vezes. O campo de
dimensionamento é o ladder. Agregado de posição só em **MWh** e **R$**. Existem
`mwmed_equivalente_flat` (96,76) e `soma_mwm_pernas` (486) no JSON — nenhum dos
dois é tamanho, e nenhum dos dois vai para a tela como "volume".

## Arquitetura: snapshot, não pipeline

Dois problemas com a mesma solução.

**Deploy.** Vou publicar isto. O servidor não terá a minha Área de Trabalho nem
os gigabytes de PLD horário de `data/raw`. Se o app importar caminho absoluto,
quebra no deploy.

**Velocidade.** O run completo leva minutos. Na defesa eles vão me dar um dado
na hora e esperar o registro em segundos.

Faça assim:

1. **Vendorize** o motor para dentro deste repositório, como `motor_curva/`.
   Cópia fiel, importada como biblioteca. Nenhum caminho absoluto no código.
2. Crie um comando offline que roda o pipeline pesado uma vez e grava um
   **snapshot** versionado — âncora, cenários oficiais, fatores sazonais,
   volatilidade por vértice, manifesto com SHA-256 das fontes, data de corte.
   Formato pequeno o bastante para ir no repositório.
3. O app **nunca** lê `data/raw`. Lê o snapshot.
4. Extraia de `cli.py::cmd_run` um serviço chamável:

   ```python
   avaliar(snapshot, ref_mercado: dict, limite_var: float) -> dict
   ```

   Só a parte barata: prêmio → sinal → dimensionamento por risco → VaR → PnL.
   Milissegundos. Mesma estrutura do `resumo_execucao.json`, mais os DataFrames
   de curva, sinal e pernas.

Prove que `avaliar()` sobre o snapshot reproduz exatamente os números do
`resumo_execucao.json` acima. Se divergir num centavo, a extração está errada.

## As três funções

### Registrar

O trader escolhe submercado, data de corte e a referência de mercado por
vértice. O motor devolve o book proposto. A tela mostra:

- o **ladder** vértice a vértice, com lado, MWm, MWh e preço
- energia, notional, preço médio ponderado por MWh
- VaR e **quanto do limite de R$ 50 mi consome**
- resultado como **intervalo** — Seco, Esperado, Úmido — nunca número único
- horizonte e data de reavaliação
- gatilhos de saída e **o que invalidaria a tese**
- comportamento em **pelo menos dois cenários hidrológicos**: resultado, impacto
  no VaR e o que muda na tese

O trader escreve a narrativa. **Os números chegam preenchidos, rotulados e com
procedência.** Cada campo numérico guarda valor, rótulo de natureza
(OBSERVADO / CALCULADO / PREMISSA / PROXY / FAIR_VALUE), origem e o hash do
snapshot que o gerou.

Campos que o trader digita ficam visualmente distintos dos que o motor calculou.
Isso não é estética: é o que torna o registro auditável seis meses depois.

### Desafiar

Antes de salvar, e o trader não pode pular. Roda sobre os números do motor, não
sobre o texto:

- **premissa mais frágil** — identifique pelo dado, não pelo palpite. A
  referência de mercado é PREMISSA sem fonte pública; o prêmio de 39,01 R$/MWh
  depende inteiramente dela. Comece por aí.
- **cenário que quebra a posição** — use o cenário adverso do próprio motor por
  vértice, e diga a partir de que preço a perna vira prejuízo.
- **contra-argumento** — o caso em que o mercado está certo e o modelo errado.
- **viés de confirmação** — se o trader só mexeu nos vértices que reforçam o
  lado que já tinha, aponte.

A IA escreve o argumento. **Os números do desafio vêm do motor.**

### Vigiar

Automática, não campo de revisão manual. Cada premissa registrada vira uma regra
verificável contra o snapshot mais recente:

- referência de mercado saiu da banda declarada
- prêmio por vértice caiu abaixo do limiar de sinal (15 R$/MWh)
- trajetória oficial da CCEE revisada entre boletins
- consumo do limite de VaR passou do orçamento (60%)
- score hidrológico virou de sinal

Cada alerta diz **qual premissa caiu, qual número mudou, de quanto para quanto**
e qual gatilho de saída isso aciona.

## Camada opcional: escolha esta

O case manda escolher **no máximo uma** e fazer bem feito. Escolha
**otimização de portfólio sob restrição de VaR** — já está pronta no motor
(`book.dimensionar_por_risco`). Exponha na tela: dado o book atual e a folga até
o limite, qual a alocação marginal que melhora a relação risco-retorno.

Não implemente as outras três. Três funções que funcionam valem mais que dez que
abrem, e isso está escrito no critério de avaliação.

## O requisito de verificação

Na defesa eles vão abrir o registro, navegar por ele e **pedir que eu registre
uma tese nova ao vivo, com um dado que darão na hora**. Provavelmente um preço
("suponha dezembro a 350") ou uma leitura hidrológica.

Desenhe esse fluxo como caminho principal, não como exceção:

- campo para alterar a referência de um vértice, ou injetar um dado hidrológico
- `avaliar()` roda na hora sobre o snapshot
- o book novo aparece ao lado do anterior, com o **diff**: o que mudou no
  ladder, no VaR e no consumo do limite
- registra em poucos cliques, com o dado novo rotulado PREMISSA e atribuído a
  "informado na defesa"

**Meta: menos de 10 segundos** entre digitar o dado e ver o book novo. Se
encostar em um minuto, a arquitetura está errada — provavelmente o pipeline
pesado está no caminho.

## Persistência

O registro tem que continuar lá quando eles abrirem na defesa. Banco de verdade,
não estado de sessão. Prove derrubando e subindo a aplicação com a tese salva.

Histórico navegável: lista de teses, abrir uma, ver o book, as premissas, os
alertas de vigilância e o que já foi violado.

## Invariantes

Cada item abaixo é um bug que já aconteceu e custou horas.

1. **Nenhum número sai de um modelo de linguagem.** A IA escreve texto,
   argumento, crítica. Todo número vem de função do motor. Campo numérico sem
   origem rastreável não pode existir.
2. **Todo número carrega rótulo de natureza**, propagado até a tela.
3. **Procedência com hash.** O registro guarda qual snapshot gerou cada número.
4. **Falha explícita.** Fonte obrigatória faltando: o app diz o que faltou e
   para. Nunca valor padrão, nunca interpolação, nunca último valor conhecido em
   silêncio. E nunca crash — mensagem tratada na tela.
5. **Risco é o VaR, e só ele.** O consumo do limite de R$ 50 mi é o VaR de
   marcação de 1 mês somado entre vértices, sem diversificação. A perda no
   cenário adverso é stress e **não** dimensiona. O `risk_service.py` que existe
   hoje neste projeto **não** é chamado para tese vinda do motor — um número, uma
   definição.
6. **Cenários são trajetórias oficiais inteiras** da CCEE, preservadas por
   inteiro. Nunca combine o mês de uma com o mês de outra.
7. **O fator de risco é o preço a termo, não o PLD spot.**
8. **MWm nunca se soma entre meses.** Dimensionamento por vértice; agregado só
   em MWh e R$.
9. **A referência de mercado é PREMISSA, leitura de mesa, sem identificação de
   fonte.** Rotule exatamente assim. Não atribua a nenhum provedor.

## Como quero trabalhar

Fatias verticais, cada uma funcionando ponta a ponta. Porte os testes antes do
código. Uma fatia por vez, testes passando antes de seguir.

Ordem sugerida, me diga se discorda:

1. Vendorizar o motor, gerar o snapshot, extrair `avaliar()`. Provar que
   reproduz o `resumo_execucao.json` exatamente.
2. Modelo de dados da tese com book, rótulos e hash. Registrar a tese da Entrega
   2 e ler de volta depois de reiniciar.
3. Tela de registro puxando do motor, com o ladder visível.
4. Fluxo de registro ao vivo com dado novo, em menos de 10 segundos.
5. Desafiar.
6. Vigiar.
7. Otimização sob VaR.

Se o prazo apertar, quero as fatias 1 a 4 sólidas. Elas cobrem o requisito de
verificação, que é o que eles vão abrir na frente de mim.

## Não faça

- não reescreva o motor
- não crie um segundo cálculo de VaR
- não mexa no que já funciona no copiloto sem me dizer antes
- não invente número para preencher tela
- não implemente mais de uma camada opcional

**Comece me devolvendo o plano das fatias 1 e 2, com os arquivos que você vai
tocar e o que muda no modelo de dados da tese. Sem código ainda.**
