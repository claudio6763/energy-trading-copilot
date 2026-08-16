# RAG regulatório

Busca **lexical** sobre SQLite FTS5. Sem vector database, sem embeddings.

## Por que lexical

Norma do setor elétrico tem jargão fixo (lastro, GSF, MRE, curtailment) e
numeração de artigo. Busca densa erra referência com mais frequência do que
acerta sinônimo. FTS5 vem na stdlib e não adiciona dependência.

## Importar um PDF

Pela interface: **Dados e fontes → Documentos e RAG**.

Por código:

```python
from src.rag import pdf_reader, store
paginas = pdf_reader.load_pages("docs/fontes/regras_ccee.pdf")
store.add_document(conn, title="Regras de Comercialização", institution="CCEE",
                   doc_type="REGRA", version="2026.1",
                   effective_from="2026-01-01", pages=paginas)
```

Cadastre sempre: título, instituição, tipo, versão, publicação e vigência.

## Como funciona

1. **Extração por página** — PyMuPDF; se ausente, `pypdf`; se nenhum, erro claro.
2. **Sanitização** — instruções embutidas no PDF são neutralizadas. Documento é
   dado, não comando.
3. **Chunking** — ~1.100 caracteres, 150 de sobreposição, quebrando em fim de frase.
4. **Indexação** — FTS5 com tokenizador `unicode61`.
5. **Recuperação** — 3 a 5 trechos, ordenados por BM25.

## Filtros

- **Vigência:** `effective_from ≤ as_of` e (`effective_to` nulo ou `≥ as_of`).
  Regra revogada não volta como se valesse.
- **Instituição:** CCEE, ONS, ANEEL, ANA, EPE.
- **Tipo de documento.**

## Interpretar o resultado

Cada trecho devolve `instituição — título — versão — p. N — vigente desde D` e um
`evidence_id`. A página é o que permite conferir a citação no PDF original.

## Documento sem resposta

Se nada for recuperado, o agente responde:

> Regra não confirmada nas fontes disponíveis.

Nunca conhecimento paramétrico do modelo.

## Atualizar documento

Ingira a nova versão com `effective_from` da vigência nova e preencha
`effective_to` da anterior. As duas ficam no acervo; a busca por data-base
escolhe a correta.

## PDF sem texto

PDF digitalizado sem OCR gera erro explícito em vez de documento vazio indexado.
Rode OCR antes (por exemplo `ocrmypdf entrada.pdf saida.pdf`).
