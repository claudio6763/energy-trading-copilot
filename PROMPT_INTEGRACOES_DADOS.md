# IMPLEMENTAÇÃO DAS CONEXÕES DE DADOS DO SETOR ELÉTRICO E CURVA FORWARD

Você está trabalhando diretamente no repositório existente do projeto **Energy Trading Copilot**, localizado no diretório atual.

O projeto já é um MVP executável em Python 3.12, Streamlit e SQLite. Ele possui interface, banco de dados, agentes, serviços, testes e documentação que devem ser preservados e aproveitados.

Sua tarefa é implementar, nesta mesma execução, as integrações com fontes públicas reais do setor elétrico brasileiro e uma solução funcional de curva pública, sem recriar o projeto e sem quebrar o que já está funcionando.

Data de referência da implementação: **09/08/2026**.

## 1. OBJETIVO

Entregar uma versão executável do Energy Trading Copilot capaz de:

1. Coletar dados públicos reais da CCEE.
2. Coletar dados públicos reais do ONS.
3. Coletar dados públicos reais da EPE.
4. Preparar integração opcional com fontes licenciadas de curva forward.
5. Investigar e, se possível, integrar uma curva forward pública de mercado.
6. Quando não houver curva pública de mercado acessível, gerar uma curva pública de cenário estatístico claramente identificada como estimativa.
7. Armazenar os dados estruturados no banco.
8. Mostrar as séries e curvas na interface.
9. Fornecer esses dados de forma controlada ao agente orquestrador e ao agente de risco.
10. Manter o RAG para normas, regras e documentos.
11. Garantir rastreabilidade, data-base, fonte e qualidade de cada informação.
12. Continuar funcionando em modo demonstração quando a internet ou uma fonte estiver indisponível.

## 2. REGRAS DE EXECUÇÃO E ECONOMIA DE TOKENS

1. Antes de editar, examine somente os arquivos relevantes:

   * `CLAUDE.md`;
   * `README.md`;
   * `app.py`;
   * `requirements.txt`;
   * `.env.example`;
   * `.gitignore`;
   * `src/`;
   * `tests/`;
   * `migrations/`;
   * `scripts/`;
   * documentação existente.

2. Execute `git status` antes de começar.

3. Preserve todas as alterações existentes.

4. Reutilize a arquitetura, os serviços, os componentes, os agentes e o banco já implementados.

5. Não recrie o projeto.

6. Não faça:

   * `git reset --hard`;
   * exclusão do banco atual;
   * exclusão do `.venv`;
   * substituição desnecessária de arquivos inteiros;
   * grandes refatorações sem necessidade;
   * alterações fora do diretório do projeto.

7. Apresente um plano inicial de no máximo cinco itens e, em seguida, implemente sem esperar nova confirmação.

8. Não pare somente no planejamento ou na pesquisa. Entregue código, testes, documentação e aplicação executável.

9. Evite:

   * Docker;
   * Redis;
   * Celery;
   * microsserviços;
   * Kubernetes;
   * novo banco vetorial;
   * nova estrutura multiagente;
   * dependências grandes ou desnecessárias.

10. Adicione somente dependências realmente necessárias.

11. Não imprima arquivos enormes, DataFrames completos ou respostas HTTP extensas no terminal.

12. Inspecione somente amostras pequenas dos dados.

13. Evite usar `/tmp`. Utilize, se necessário, uma pasta local `.tmp/`, adicionada ao `.gitignore`.

14. Execute testes direcionados durante o desenvolvimento e a suíte completa somente uma vez ao final.

15. Evite iniciar repetidamente o Streamlit. Faça apenas um smoke test ao final e encerre o processo depois da verificação.

16. Caso uma fonte não possa ser validada:

* não invente endpoint;
* não invente dados;
* não tente indefinidamente;
* documente a limitação;
* implemente um fallback simples;
* mantenha o restante do MVP funcional.

## 3. AUTENTICAÇÃO, CADASTROS E PROTEÇÃO DE CREDENCIAIS

1. Priorize APIs, arquivos e endpoints públicos sem autenticação.

2. Os portais de Dados Abertos do ONS, CCEE e EPE devem ser acessados publicamente, sem login, sempre que os dados estiverem disponíveis dessa forma.

3. Não tente fazer cadastro ou login no Portal de Dados Abertos do ONS.

4. Não crie contas automaticamente em nenhum site.

5. Não automatize:

   * formulários de cadastro;
   * login com e-mail e senha;
   * captcha;
   * confirmação de e-mail;
   * autenticação multifator;
   * áreas restritas de sites.

6. Não utilize, procure, copie ou grave e-mails, senhas ou credenciais que possam ter sido informados em conversas, histórico do terminal ou outros arquivos.

7. Se uma fonte exigir cadastro, assinatura ou credencial:

   * classifique como `REQUIRES_MANUAL_REGISTRATION` ou `OPTIONAL_LICENSED`;
   * informe a página oficial para cadastro;
   * explique qual credencial ou plano é necessário;
   * mantenha o conector desabilitado;
   * continue a implementação com as demais fontes;
   * não interrompa a conclusão do MVP.

8. O cadastro e o primeiro login serão realizados manualmente pelo usuário no navegador.

9. Depois do cadastro manual, a aplicação poderá utilizar apenas:

   * API keys;
   * tokens;
   * OAuth;
   * credenciais específicas de aplicação;
   * variáveis de ambiente locais.

10. Nunca solicitar senha na interface Streamlit.

11. O `.env.example` deve conter somente placeholders vazios, como:

* `BBCE_API_ENABLED=false`
* `BBCE_API_BASE_URL=`
* `BBCE_API_KEY=`
* `BBCE_AUTH_TOKEN=`
* `HTTP_TIMEOUT_SECONDS=30`
* `MARKET_DATA_USER_AGENT=EnergyTradingCopilot/1.0`

12. Nunca abrir, exibir, alterar ou versionar o `.env` real.

13. Garanta que o `.gitignore` contenha:

* `.env`;
* cookies;
* tokens;
* arquivos de sessão;
* credenciais JSON;
* certificados privados;
* arquivos temporários de autenticação;
* `.tmp/`;
* dados brutos que não devam ser versionados.

14. Nunca armazene credenciais no SQLite.

15. Nunca inclua credenciais em:

* logs;
* mensagens de erro;
* fixtures;
* testes;
* documentação;
* URLs;
* screenshots;
* respostas finais.

16. Mascare nos logs:

* `Authorization`;
* `apiKey`;
* `Cookie`;
* `Set-Cookie`;
* tokens;
* segredos.

17. Antes de usar um conector autenticado, valide as variáveis necessárias.

18. Se as credenciais estiverem ausentes:

* não faça a chamada;
* não gere erro fatal;
* marque como `DISABLED_MISSING_CREDENTIALS`;
* informe quais variáveis devem ser configuradas.

19. Situação esperada:

* ONS: `PUBLIC_NO_AUTH`;
* CCEE: `PUBLIC_NO_AUTH`;
* EPE: `PUBLIC_NO_AUTH`;
* BBCE Curva Forward: `OPTIONAL_LICENSED`;
* B3/N5X: verificar situação pública atual;
* Dcide: consulta pública limitada e importação manual autorizada;
* curvas próprias: importação manual por CSV.

## 4. DECISÃO ARQUITETURAL OBRIGATÓRIA

Utilize cada tecnologia para o tipo correto de dado.

### RAG

Use o RAG para:

* regras de comercialização;
* normas;
* procedimentos;
* documentos da CCEE;
* documentos do ONS;
* documentos da ANEEL;
* materiais da EPE;
* restrições regulatórias;
* metodologia de mercado;
* documentos sobre risco.

### SQLite e serviços determinísticos

Use o banco estruturado para:

* PLD;
* CMO;
* carga;
* ENA;
* EAR;
* consumo;
* séries temporais;
* indicadores;
* curvas forward;
* cenários;
* datas de referência;
* qualidade;
* histórico de ingestões.

### Integração com o agente

O LLM não deve receber milhares de linhas no prompt.

O agente deve consultar funções controladas da aplicação, e não gerar SQL arbitrário para execução.

Toda informação apresentada pelo agente deve diferenciar:

1. fato observado;
2. dado oficial;
3. curva de mercado;
4. curva licenciada;
5. cenário estatístico;
6. inferência do agente;
7. informação insuficiente.

PLD e CMO nunca podem ser apresentados como preço forward de mercado.

## 5. CONECTOR CCEE

Portal oficial:

https://dadosabertos.ccee.org.br/

Página de contexto:

https://dadosabertos.ccee.org.br/organization/preco_liquidacao_diferenca

Implementar inicialmente:

* PLD horário;
* PLD médio diário;
* PLD médio semanal;
* PLD médio mensal.

O portal disponibiliza API e recursos CSV.

Implemente descoberta dinâmica pelo catálogo oficial usando, conforme disponível:

* `package_search`;
* `package_show`;
* recursos do CKAN;
* API de datastore;
* download de CSV.

Não fixe no código uma URL anual de arquivo que poderá mudar.

O conector deve:

1. descobrir o dataset;
2. localizar o recurso atual;
3. priorizar formatos CSV ou API documentada;
4. baixar somente o necessário;
5. validar content-type;
6. normalizar datas;
7. normalizar submercados;
8. converter valores numéricos brasileiros;
9. validar colunas obrigatórias;
10. registrar a URL utilizada;
11. registrar data de coleta;
12. registrar data-base;
13. realizar upsert idempotente;
14. evitar duplicação;
15. tratar mudanças de layout;
16. falhar de forma controlada.

Não utilize datasets históricos obsoletos como se fossem os dados atuais.

## 6. CONECTOR ONS

Portal oficial:

https://dados.ons.org.br/

Conectar inicialmente:

* carga de energia diária por subsistema;
* CMO semanal;
* ENA diária por subsistema;
* EAR diária por subsistema.

Datasets de referência:

* `carga-energia`;
* `cmo-semanal`;
* `ena-diario-por-subsistema`;
* `ear-diario-por-subsistema`.

O catálogo pode apontar para arquivos na AWS.

Utilize o catálogo oficial para descobrir a URL atual. Não dependa de uma URL anual fixa.

O conector deve:

1. descobrir recursos pelo catálogo;
2. selecionar CSV, Parquet ou outro formato simples suportado;
3. processar apenas colunas necessárias;
4. normalizar subsistemas;
5. preservar unidades;
6. registrar frequência do dado;
7. registrar data mais recente;
8. registrar procedência;
9. impedir duplicações;
10. tratar indisponibilidade sem derrubar a aplicação.

Prepare pontos de extensão, sem implementar tudo agora, para:

* geração por fonte;
* geração térmica;
* disponibilidade de usinas;
* intercâmbio entre subsistemas;
* restrições hidráulicas;
* constrained-off eólico;
* constrained-off solar;
* dados de reservatórios;
* restrições operativas.

Essas extensões futuras não podem impedir a conclusão do MVP atual.

## 7. CONECTOR EPE

Portal oficial:

https://www.epe.gov.br/pt/publicacoes-dados-abertos/dados-abertos

Implementar pelo menos um conector funcional para consumo mensal de energia elétrica:

https://www.epe.gov.br/pt/publicacoes-dados-abertos/dados-abertos/dados-do-consumo-mensal-de-energia-eletrica

A EPE pode disponibilizar arquivos em vez de uma API uniforme.

O conector deve:

1. localizar o link oficial de download na página;
2. permitir URL configurável por variável de ambiente;
3. validar domínio oficial;
4. baixar o arquivo;
5. calcular hash;
6. registrar data de coleta;
7. validar layout;
8. normalizar datas, classes, regiões e unidades;
9. importar somente os campos úteis;
10. retornar mensagem compreensível quando o layout mudar.

Não afirme que existe uma API quando o acesso for realizado por arquivo.

Prepare a arquitetura para futuramente receber:

* projeções de carga;
* dados do PDE;
* balanço energético;
* expansão de geração;
* cenários de demanda.

## 8. SINAIS CLIMÁTICOS E EXTERNOS

Depois que CCEE, ONS e EPE estiverem funcionando e testados, faça uma verificação curta para identificar uma fonte oficial e pública, preferencialmente NOAA/CPC, para indicador ENSO/El Niño.

Regras:

1. Utilize apenas fonte oficial e máquina-legível.
2. Não faça scraping de sites de notícias.
3. Não transforme notícia em dado quantitativo sem metodologia.
4. Se encontrar fonte estável, implemente um conector pequeno para o indicador.
5. Se não encontrar, registre a fonte como `NOT_VERIFIED` e prepare importação manual por CSV.
6. Essa integração é secundária e não pode atrasar o núcleo do projeto.

## 9. CLASSIFICAÇÃO DAS CURVAS

Implemente e mantenha separadas as seguintes categorias:

1. `MARKET_FORWARD_DELAYED_PUBLIC`
2. `MARKET_FORWARD_LICENSED`
3. `STATISTICAL_SCENARIO_PUBLIC`
4. `MANUAL_AUTHORIZED_CURVE`

Nunca misture essas classificações.

Toda curva deve possuir:

* fonte;
* tipo;
* data de referência;
* data de coleta;
* início e fim de entrega;
* submercado;
* tipo de energia;
* produto;
* preço;
* unidade;
* metodologia;
* defasagem;
* qualidade;
* restrição de uso conhecida.

## 10. CURVA B3/N5X

Página oficial de referência:

https://www.b3.com.br/pt_br/produtos-e-servicos/outros-servicos/servicos-de-natureza-informacional/plataforma-de-energia-da-b3/

Metodologia histórica oficial:

https://www.b3.com.br/lumis/portal/file/fileDownload.jsp?fileId=8AE490CA80DC394C018143B955EB7412

A documentação da B3 informou divulgação gratuita de curva forward com cinco dias úteis de atraso.

Faça uma verificação curta, objetiva e somente em páginas oficiais da B3 ou N5X para determinar se, em 2026, ainda existe endpoint, arquivo ou página pública automatizável.

Se existir e for validado com requisição real:

1. implemente o conector;
2. registre como `MARKET_FORWARD_DELAYED_PUBLIC`;
3. informe a defasagem;
4. registre a URL oficial;
5. preserve a metodologia e os produtos divulgados;
6. não extrapole produtos inexistentes.

Se não existir fonte atual verificável:

1. não invente URL;
2. não faça scraping frágil;
3. deixe o conector desabilitado;
4. marque como `NOT_VERIFIED`;
5. documente o resultado;
6. siga com a curva estatística pública.

Não gaste tempo indefinido procurando esse endpoint.

## 11. CURVA BBCE LICENCIADA

Portal oficial:

https://portaldodesenvolvedor.bbce.com.br/

Endpoint documentado:

`GET v1/curve/bbce-fwd?referenceDate=AAAA-MM-DD`

A API exige plano e credenciais.

Implemente um conector opcional, desabilitado por padrão, com:

* `BBCE_API_ENABLED=false`;
* `BBCE_API_BASE_URL=`;
* `BBCE_API_KEY=`;
* `BBCE_AUTH_TOKEN=`.

Regras:

1. Siga somente a documentação oficial validada.
2. Não faça chamadas sem credenciais.
3. Não invente resposta da API.
4. Não crie dados simulados como se fossem BBCE.
5. Trate 401 e 403 como ausência de autorização.
6. Não registre headers de autenticação nos logs.
7. Classifique como `MARKET_FORWARD_LICENSED`.
8. Mantenha o aplicativo funcional quando o conector estiver desabilitado.

## 12. DCIDE E OUTRAS CURVAS LICENCIADAS

Não faça scraping automático da Dcide.

Não reproduza automaticamente boletins ou séries com restrições de uso.

Implemente uma importação manual genérica por CSV para curvas obtidas legalmente.

Schema mínimo:

* `reference_date`;
* `delivery_start`;
* `delivery_end`;
* `submarket`;
* `energy_type`;
* `product`;
* `price_brl_mwh`;
* `source`;
* `curve_type`.

Valide:

* datas;
* preços positivos;
* unidade;
* fonte;
* duplicação;
* submercado;
* tipo de curva.

Inclua um arquivo de exemplo somente com valores fictícios e claramente identificados como `SAMPLE`.

Nunca apresente o CSV de exemplo como dado real.

## 13. CURVA PÚBLICA DE CENÁRIO ESTATÍSTICO

Para garantir que o MVP funcione sem assinatura, implemente uma curva de cenário com histórico público de PLD mensal da CCEE.

### Metodologia

1. Criar horizontes mensais de M+1 até M+12.

2. Para cada submercado e mês futuro, localizar os valores históricos do mesmo mês-calendário nos anos anteriores.

3. Calcular:

   * P10;
   * P50;
   * P90.

4. Exigir pelo menos três observações anuais válidas por ponto.

5. Se não houver dados suficientes:

   * não interpolar silenciosamente;
   * não preencher com valor inventado;
   * retornar `INSUFFICIENT_DATA`.

6. Registrar:

   * data do cálculo;
   * período histórico;
   * quantidade de observações;
   * percentis;
   * submercado;
   * metodologia;
   * fonte original;
   * data da última observação.

7. Classificar como `STATISTICAL_SCENARIO_PUBLIC`.

8. Chamar P50 de “cenário central”, e não de preço de mercado.

9. Exibir obrigatoriamente:

“Cenário estatístico baseado no histórico público de PLD. Não representa cotação negociada, recomendação de compra ou venda, nem curva forward de mercado.”

10. Não ajustar preços arbitrariamente com ENA, EAR, carga ou CMO nesta versão.

11. Mostre ENA, EAR, carga e CMO ao lado da curva como indicadores fundamentais independentes.

## 14. PERSISTÊNCIA

Adapte o banco existente por migrações incrementais.

Não compartilhe conexão SQLite global entre threads do Streamlit.

Abra conexão por operação ou utilize o padrão seguro já existente.

Crie ou adapte estruturas equivalentes a:

### `data_sources`

* id;
* nome;
* URL oficial;
* tipo de acesso;
* autenticação;
* licença ou restrição;
* frequência;
* status;
* última verificação;
* última coleta.

### `ingestion_runs`

* fonte;
* dataset;
* início;
* fim;
* status;
* registros recebidos;
* registros importados;
* registros atualizados;
* erro resumido;
* data de referência;
* hash;
* URL utilizada.

### `market_observations`

* fonte;
* dataset;
* data e hora de referência;
* submercado;
* indicador;
* valor;
* unidade;
* data de coleta;
* URL;
* status de qualidade.

### `forward_curve_points`

* fonte;
* tipo de curva;
* data de referência;
* início de entrega;
* fim de entrega;
* submercado;
* tipo de energia;
* produto;
* cenário;
* preço em R$/MWh;
* quantidade de observações;
* metodologia;
* data de coleta;
* URL;
* defasagem;
* status de qualidade.

### `external_signals`

* fonte;
* indicador;
* data de referência;
* valor;
* unidade;
* classificação;
* data de coleta;
* URL;
* qualidade.

Crie índices e restrições de unicidade para operações idempotentes.

Se já existirem tabelas equivalentes, adapte-as em vez de duplicá-las.

## 15. CAMADA DE CONECTORES

Implemente uma interface simples compatível com a arquitetura existente, contendo operações equivalentes a:

* descobrir recursos;
* coletar;
* normalizar;
* validar;
* persistir;
* verificar saúde.

Todos os conectores HTTP devem possuir:

* timeout;
* número limitado de tentativas;
* backoff simples;
* User-Agent;
* tratamento de HTTP 4xx e 5xx;
* validação de content-type;
* logs sem segredos;
* falha isolada;
* mensagens compreensíveis;
* possibilidade de teste por mock.

Não introduza framework complexo de orquestração.

## 16. ATUALIZAÇÃO DOS DADOS

Crie um comando compatível com Windows, por exemplo:

`.\.venv\Scripts\python.exe scripts\update_sector_data.py --source all`

Suportar, conforme aplicável:

* `--source ccee`;
* `--source ons`;
* `--source epe`;
* `--source climate`;
* `--source forward`;
* `--source all`;
* `--dry-run`.

O comando deve:

1. mostrar resumo conciso;
2. registrar cada execução;
3. permitir sucesso parcial;
4. retornar código diferente de zero em falha total;
5. não expor credenciais;
6. não duplicar dados;
7. permitir nova execução segura.

Não implemente agendador complexo.

Documente como usar futuramente o Agendador de Tarefas do Windows.

## 17. INTERFACE STREAMLIT

Integre as novas funcionalidades à interface existente.

### Área “Dados e fontes”

Mostrar:

* fonte;
* dataset;
* status;
* última coleta;
* data mais recente;
* quantidade de registros;
* defasagem;
* erro mais recente;
* URL oficial;
* tipo de autenticação.

Adicionar atualização manual reutilizando os serviços de ingestão.

Uma fonte indisponível não pode derrubar a página.

### Área de curva

Adicionar:

* seletor de fonte;
* seletor de tipo de curva;
* seletor de submercado;
* seletor de energia;
* data-base;
* tabela;
* gráfico;
* P10/P50/P90;
* classificação;
* fonte;
* data de coleta;
* defasagem;
* aviso metodológico.

Se somente a curva estatística estiver disponível, a aplicação deve continuar utilizável.

## 18. INTEGRAÇÃO COM OS AGENTES

Mantenha o RAG atual para documentos e regras.

Integre os dados estruturados por um serviço controlado que forneça ao orquestrador e ao agente de risco:

* último PLD;
* CMO;
* carga;
* ENA;
* EAR;
* consumo;
* sinais climáticos disponíveis;
* curva selecionada;
* fonte;
* data-base;
* defasagem;
* qualidade.

O agente deve:

1. citar fonte e data;
2. diferenciar dado observado de inferência;
3. diferenciar curva de mercado de cenário estatístico;
4. informar quando o dado estiver desatualizado;
5. recusar conclusões quantitativas quando faltarem informações;
6. nunca afirmar possuir cotação em tempo real;
7. nunca apresentar PLD ou CMO como forward;
8. apresentar riscos e contrapontos;
9. deixar explícito quando uma conclusão for apenas uma hipótese;
10. não executar SQL arbitrário produzido pelo LLM.

Reutilize o orquestrador e o agente de risco existentes.

## 19. DOCUMENTAÇÃO

Atualize o `README.md`.

Crie:

`docs/CONEXOES_DADOS_SETOR.md`

A documentação deve explicar:

* fontes implementadas;
* URLs oficiais;
* datasets;
* formatos;
* atualização;
* autenticação;
* fontes públicas;
* fontes licenciadas;
* variáveis de ambiente;
* execução manual;
* importação de CSV;
* interpretação das curvas;
* metodologia estatística;
* limitações;
* tratamento de erros;
* credenciais;
* segurança;
* solução de problemas;
* Agendador de Tarefas do Windows.

Crie uma matriz de fontes com os estados:

* `ACTIVE`;
* `PUBLIC_NO_AUTH`;
* `OPTIONAL_LICENSED`;
* `REQUIRES_MANUAL_REGISTRATION`;
* `DISABLED_MISSING_CREDENTIALS`;
* `NOT_VERIFIED`;
* `MANUAL`.

## 20. TESTES

Implemente testes para:

* descoberta e normalização CCEE;
* descoberta e normalização ONS;
* importação EPE;
* conversão de valores;
* normalização de datas;
* normalização de submercados;
* upsert idempotente;
* falha de rede;
* timeout;
* HTTP 401, 403, 404 e 500;
* layout inválido;
* cálculo P10/P50/P90;
* dados insuficientes;
* importação manual de curva;
* diferenciação dos tipos de curva;
* ausência de credenciais;
* mascaramento de segredos;
* SQLite sem compartilhamento indevido entre threads.

Utilize mocks e fixtures locais pequenas.

Testes unitários não devem depender da internet.

Testes de integração com internet devem ser opcionais e marcados adequadamente.

## 21. CRITÉRIOS DE ACEITE

Ao final, confirme que:

1. o MVP existente continua funcionando;
2. o modo demonstração funciona sem internet;
3. CCEE possui pelo menos um fluxo real de ingestão validado;
4. ONS possui pelo menos um fluxo real de ingestão validado;
5. EPE possui pelo menos um fluxo real de ingestão validado;
6. a curva estatística pública é gerada com dados reais;
7. nenhuma curva estatística é apresentada como mercado;
8. BBCE permanece opcional sem credenciais;
9. B3/N5X possui status real documentado;
10. uma fonte indisponível não derruba a aplicação;
11. não existem segredos no código;
12. os dados possuem fonte e data-base;
13. os agentes conseguem consultar os dados estruturados;
14. os testes passam;
15. o Streamlit inicia sem traceback;
16. qualquer servidor de teste é encerrado;
17. a documentação ensina a instalar, atualizar e utilizar.

## 22. VERIFICAÇÃO FINAL

Execute nesta ordem:

1. testes direcionados;
2. suíte completa uma única vez;
3. smoke test do Streamlit;
4. encerramento do servidor;
5. `git status`;
6. verificação de segredos nos arquivos modificados;
7. resumo final.

Não declare sucesso se os testes ou o smoke test falharem.

Se algo falhar, faça uma correção localizada e teste novamente.

## 23. FORMATO DA RESPOSTA FINAL

Responda de forma objetiva com:

1. funcionalidades implementadas;
2. arquivos modificados;
3. migrações criadas;
4. tabela de fontes e respectivos status;
5. curva pública disponível;
6. situação da B3/N5X;
7. situação da BBCE;
8. limitações;
9. variáveis de ambiente necessárias;
10. comando para instalar dependências;
11. comando para atualizar os dados;
12. comando para executar os testes;
13. comando para abrir o Streamlit;
14. resultado dos testes;
15. resultado do smoke test.

Não repita toda a implementação na resposta. Entregue o projeto funcionando no diretório atual.
