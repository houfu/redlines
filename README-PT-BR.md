**Translation Date:** 2025-10-29
**Original English File:** [README.md](https://github.com/houfu/redlines/blob/master/README.md)
*This is a translation. For the most current version, please refer to the English file.*

---

**Data da Tradução:** 29-10-2025
**Arquivo Original em Inglês:** [README.md](https://github.com/houfu/redlines/blob/master/README.md)
*Esta é uma tradução. Para a versão mais atualizada, por favor, consulte o arquivo em inglês.*

---
# Redlines
![Repository banner image](repository-open-graph.png)
![PyPI - Version](https://img.shields.io/pypi/v/redlines)
![GitHub Release Date - Published_At](https://img.shields.io/github/release-date/houfu/redlines)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/houfu/redlines)
![PyPI - License](https://img.shields.io/pypi/l/redlines)

`Redlines` compara duas strings/textos e produz uma saída estruturada mostrando suas diferenças. As alterações são representadas com tachados e destaques, similar ao controle de alterações do Microsoft Word. A saída inclui informações detalhadas sobre mudanças, posições e estatísticas para uso programático.

Suporta múltiplos formatos de saída: **JSON** (padrão, com dados estruturados de alterações e estatísticas), **Markdown**, **HTML** e **rich** (exibição em terminal).

## Início Rápido

```bash
# Instalar
pip install redlines

# CLI: Comparar dois textos (saída em JSON por padrão)
redlines "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."

# Python: Comparar e obter markdown
from redlines import Redlines
test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
    markdown_style="none"
)
print(test.output_markdown)
# Saída: The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.
```

**Suportado**: Python 3.10 - 3.14 (suporte para Python 3.8 e 3.9 descontinuado)

**Dependências opcionais:**
- `pip install redlines[nupunkt]` para detecção avançada de limites de sentenças (Python 3.11+, manipula abreviações, citações, URLs)
- `pip install redlines[levenshtein]` para estatísticas adicionais

## Uso

### API Python

A biblioteca contém uma classe: `Redlines`, que é usada para comparar texto.

**Comparação básica:**
```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
    markdown_style="none"
)
assert (
    test.output_markdown
    == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)
```

**Múltiplas comparações com uma fonte:**
```python
from redlines import Redlines

test = Redlines("The quick brown fox jumps over the lazy dog.", markdown_style="none")
assert (
    test.compare("The quick brown fox walks past the lazy dog.")
    == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)

assert (
    test.compare("The quick brown fox jumps over the dog.")
    == "The quick brown fox jumps over the <del>lazy </del>dog."
)
```

**Saída JSON com dados estruturados:**
```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog."
)

# Obter JSON com mudanças, posições e estatísticas
print(test.output_json(pretty=True))
```

### CLI

**Uso básico (saída em JSON por padrão):**
```bash
redlines "old text" "new text"
redlines file1.txt file2.txt --pretty
```

**Formatos de saída:**
```bash
redlines text "source" "test"              # Exibição rich em terminal
redlines markdown file1.txt file2.txt      # Saída em Markdown
redlines stats old.txt new.txt             # Apenas estatísticas
```

Execute `redlines --help` ou `redlines guide` para [Guia de Interação para Agentes](AGENT_GUIDE.md). Veja também: [redlines-textual](https://github.com/houfu/redlines-textual).

## Recursos Avançados

### Processadores Personalizados

Use `NupunktProcessor` para tokenização em nível de sentença com detecção inteligente de limites:

```python
from redlines import Redlines
from redlines.processor import NupunktProcessor

processor = NupunktProcessor()
test = Redlines("Dr. Smith said hello.", "Dr. Smith said hi.", processor=processor)
```

**Use NupunktProcessor para:** Documentos legais/técnicos com abreviações, URLs, citações, decimais
**Use WholeDocumentProcessor (padrão) para:** Documentos simples, tarefas críticas em velocidade (5-6x mais rápido), granularidade em nível de parágrafo

Veja [comparação de demonstração](demo/README.md) for benchmarks.

### Para Agentes de IA e Automação

**🤖 Usando com agentes de codificação de IA?** Veja o **[Guia de Interação para Agentes](AGENT_GUIDE.md)** para esquemas JSON, padrões de automação, tratamento de erros e [Exemplos executáveis](examples/).

## Documentação e Recursos

**Documentação Completa:** [https://houfu.github.io/redlines](https://houfu.github.io/redlines)

**Exemplos de Casos de Uso:**
* Visualizar e marcar mudanças em legislação: [PLUS Explorer](https://houfu-plus-explorer.streamlit.app/)
* Visualizar mudanças após o ChatGPT transformar um texto: [ChatGPT Prompt Engineering for Developers](https://www.deeplearning.ai/short-courses/chatgpt-prompt-engineering-for-developers/)Lição 6

## Licença

Licença MIT