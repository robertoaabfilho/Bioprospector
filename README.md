# Pipeline de prospecção de plantas e compostos bioativos

> Versão 2 · scripts em Python · configuração única em `input.txt`

## Sumário

1. [O que o pipeline faz](#1-o-que-o-pipeline-faz)
2. [Visão geral do fluxo](#2-visão-geral-do-fluxo)
3. [Instalação e preparo](#3-instalação-e-preparo)
4. [Organização da pasta](#4-organização-da-pasta)
5. [O arquivo `input.txt`](#5-o-arquivo-inputtxt)
6. [Como rodar](#6-como-rodar)
7. [As etapas em detalhe](#7-as-etapas-em-detalhe)
8. [Guia dos arquivos de resultado](#8-guia-dos-arquivos-de-resultado)
9. [Mensagens de status nas planilhas](#9-mensagens-de-status-nas-planilhas)
10. [Caches, retomada e atualização](#10-caches-retomada-e-atualização)
11. [Tempo de execução e escala](#11-tempo-de-execução-e-escala)
12. [Solução de problemas](#12-solução-de-problemas)
13. [Limitações e cuidados na interpretação](#13-limitações-e-cuidados-na-interpretação)
14. [Bases de dados e como citá-las](#14-bases-de-dados-e-como-citá-las)
15. [Histórico de mudanças](#15-histórico-de-mudanças)

---

## 1. O que o pipeline faz

O pipeline responde a esta pergunta:

> **Quais plantas de uma região (e da minha lista) têm compostos e
> atividades biológicas documentados e quais são as evidências?**

Você informa três coisas em `input.txt`:

| Entrada | Exemplo | Obrigatória? |
|---|---|---|
| **Região geográfica** (coordenadas + palavras que a identificam em textos) | polígono do estado do Amazonas; `amazon*, Amazonas, Amazônia` | sim |
| **Lista de gêneros e/ou espécies** de interesse | `Euterpe oleracea, Copaifera, Carapa guianensis` | sim (pode ser curta) |
| **Atividades de interesse** | `clareadora = tyrosinase inhibit*, melanin*` | não (vazio = qualquer atividade) |

O pipeline devolve planilhas CSV (abrem no Excel) com:

- a **lista de plantas** da região, da sua lista e das citadas em artigos, com
  **nomes conferidos** em três bases taxonômicas;
- os **compostos** conhecidos de cada planta (COCONUT e NPASS), com InChIKey,
  SMILES e classificação química;
- as **atividades medidas em ensaios** de cada composto (ChEMBL);
- as **atividades relatadas em artigos** (PubMed) para plantas e compostos.
  Um modelo de linguagem local (Llama, via Ollama) lê os resumos e mantém
  **só os que relatam um resultado experimental positivo de causa e
  efeito**, anotando o **tipo de estudo** e a **parte da planta**;
- **arquivos de evidência** com o PMID, o DOI e a justificativa de cada
  resultado, para conferência.

---

## 2. Visão geral do fluxo

```
                        input.txt
                            │
  [0 downloads]  baixar_bases.py ───────────► bases baixadas uma vez (dados_*/)
                            │
  ── FASE A: montar a lista de plantas ─────────────────────────────────────
  [1 gbif]       buscar_especies_gbif.py ───► especies_gbif.csv
                            │                   (plantas com ocorrência na região)
  [2 plantas]    montar_lista_plantas.py ───► plantas.csv
                   GBIF + sua lista              plantas_conferencia_taxonomica.csv
                   + plantas citadas em artigos  plantas_artigos_evidencias.csv
                   → nomes conferidos em Flora e Funga do Brasil, WFO e GBIF
                            │
  ── FASE B: compostos e atividades ────────────────────────────────────────
  [3 bioativos]  cruzar_especies_bioativos.py ► especies_com_compostos_bioativos.csv
                   COCONUT + NPASS
                            │
  [4 chembl]     consultar_chembl.py ────────► compostos_chembl.csv
                   ensaios do ChEMBL (InChIKey)  evidencias_chembl.csv
                            │
  [5 pubmed]     consultar_atividades_pubmed.py ► atividades_plantas.csv
                   PubMed + PubChem + Llama        atividades_compostos.csv
                                                   especies_atividades.csv
                                                   evidencias_pubmed.csv
```

| # | Etapa (`id`) | Pergunta que responde | Principais fontes |
|---|---|---|---|
| 0 | `downloads` | — (prepara as bases locais) | Flora e Funga do Brasil, WFO, COCONUT, NPASS, ChEMBL |
| 1 | `gbif` | Que plantas têm registro de ocorrência na região? | GBIF |
| 2 | `plantas` | Qual é a lista final de plantas, com os nomes corretos? | GBIF, sua lista, PubMed, OpenAlex, Flora e Funga do Brasil, WFO |
| 3 | `bioativos` | Que compostos já foram isolados ou identificados nessas plantas? | COCONUT, NPASS |
| 4 | `chembl` | Que atividades desses compostos foram medidas em ensaios? | ChEMBL |
| 5 | `pubmed` | Que atividades os artigos demonstram para as plantas e os compostos? | PubMed, PubChem, Llama local |

Cada etapa lê a saída da anterior, e todas podem ser retomadas
individualmente.

---

## 3. Instalação e preparo

### 3.1 Python e pacotes

É necessário o Python 3.10 ou mais recente. Instale os pacotes com:

```bash
pip install requests pandas tqdm truststore
```

O `truststore` faz o Python usar os certificados de segurança do sistema
operacional, como o navegador. Sem ele, alguns servidores dão o erro
`CERTIFICATE_VERIFY_FAILED` (ver seção 12).

### 3.2 Conta no GBIF (etapa 1)

O levantamento da região usa o serviço de download do GBIF, que exige uma
conta gratuita: https://www.gbif.org → *Login* → *Register*.

As credenciais são lidas de variáveis de ambiente. Guarde-as num arquivo na
pasta do pipeline e carregue-o antes de rodar.

**Linux / macOS**: arquivo `gbif_credenciais.env`

```bash
export GBIF_USER="seu_usuario"
export GBIF_PWD="sua_senha"
export GBIF_EMAIL="seu@email"
```

Para carregar: `source gbif_credenciais.env`

**Windows, Prompt de Comando (cmd)**: arquivo `gbif_credenciais.bat`

```bat
set GBIF_USER=seu_usuario
set GBIF_PWD=sua_senha
set GBIF_EMAIL=seu@email
```

Para carregar: `gbif_credenciais.bat`, digitado **dentro da pasta do
pipeline** (`cd` até ela antes).

**Windows, PowerShell**: rodar o `.bat` no PowerShell **não** funciona,
porque as variáveis não passam para a sessão. Digite:

```powershell
$env:GBIF_USER = "seu_usuario"
$env:GBIF_PWD = "sua_senha"
$env:GBIF_EMAIL = "seu@email"
```

Se as variáveis não estiverem definidas, a etapa 1 pede usuário e senha no
terminal.

> ⚠️ **Não compartilhe** os arquivos de credenciais: a senha está em texto
> puro. Eles não fazem parte do pacote do pipeline.

### 3.3 Ollama + Llama (etapa 5, obrigatório)

O Llama roda **no seu computador**, sem custo e sem enviar dados para fora.

1. Instale o Ollama: https://ollama.com/download. No Linux:
   `curl -fsSL https://ollama.com/install.sh | sh`.
2. Baixe o modelo (≈5 GB):
   ```bash
   ollama pull llama3.1:8b
   ```
3. Deixe o Ollama rodando. Em geral ele inicia sozinho; se não, use
   `ollama serve`.

| Modelo | Memória | Comentário |
|---|---|---|
| `llama3.1:8b` | ≈5 GB de RAM/VRAM | **recomendado** (padrão) |
| `llama3.2:3b` | ≈2–3 GB | mais rápido em CPU, um pouco menos preciso |
| modelos de 1B | — | não recomendados: erram muito no julgamento de causalidade |

Com placa de vídeo (GPU), cada resumo leva cerca de 1–3 s. Só com CPU, leva
cerca de 5–30 s.

### 3.4 Chaves de API gratuitas (opcionais, mas recomendadas)

| Chave | Para quê | Onde obter | Onde colocar |
|---|---|---|---|
| **NCBI** | etapas 2 e 5 cerca de **3× mais rápidas** (PubMed/PubChem) | https://www.ncbi.nlm.nih.gov/account/ → *Account settings* → *API Key* | `[pubmed] ncbi_api_key` ou variável `NCBI_API_KEY` |
| **OpenAlex** | sem ela a cota diária é mínima e a descoberta em artigos segue só com o PubMed | crie uma conta em https://openalex.org | `[artigos] openalex_api_key` |

### 3.5 Espaço em disco

| Base | Tamanho aproximado |
|---|---|
| Flora e Funga do Brasil | dezenas de MB |
| World Flora Online (WFO) | ≈700 MB |
| COCONUT (CSV completo) + NPASS | ≈1 GB |
| Estruturas do ChEMBL | ≈300 MB |
| Caches e resultados | dezenas a centenas de MB, conforme a região |

Reserve **pelo menos 3 GB** livres.

---

## 4. Organização da pasta

### 4.1 Arquivos do pipeline

| Arquivo | Função |
|---|---|
| `input.txt` | **arquivo de configuração** |
| `lista_de_plantas.txt` | sua lista de plantas (opcional; substitui a seção `[taxons]`) |
| `main.py` | orquestrador: roda as etapas na ordem e permite retomar |
| `config_pipeline.py` | lê e valida o `input.txt` (`python config_pipeline.py` mostra o que foi entendido) |
| `baixar_bases.py` | etapa 0 (`downloads`) |
| `buscar_especies_gbif.py` | etapa 1 (`gbif`) |
| `montar_lista_plantas.py` | etapa 2 (`plantas`) |
| `cruzar_especies_bioativos.py` | etapa 3 (`bioativos`) |
| `consultar_chembl.py` | etapa 4 (`chembl`) |
| `consultar_atividades_pubmed.py` | etapa 5 (`pubmed`) |
| `taxonomia.py` | módulo: conferência de nomes (Flora e Funga do Brasil, WFO, GBIF) |
| `descoberta_artigos.py` | módulo: descoberta de plantas citadas em artigos |
| `literatura.py` | módulo: acesso a PubMed, PubChem e OpenAlex, caches |
| `duke.py` | módulo: Dr. Duke (etapa 3) |
| `diagnostico_pubmed.py` | resumo do andamento da etapa 5 a partir dos caches (`python diagnostico_pubmed.py` gera `diagnostico_pubmed.txt`) |
| `gbif_credenciais.env` / `.bat` | suas credenciais do GBIF (você cria; ver 3.2) |

### 4.2 O que é criado durante a execução

| Item | Conteúdo |
|---|---|
| `dados_flora_brasil/`, `dados_wfo/` | listas taxonômicas baixadas |
| `dados_bioativos/` | COCONUT e NPASS |
| `dados_chembl/` | arquivo de estruturas do ChEMBL |
| `dados_gbif_download/` | downloads do GBIF e registro dos pedidos (`pedidos.json`) |
| `bases_baixadas.txt` | resumo da etapa 0 |
| `cache_*.jsonl` | memória de todas as consultas feitas (ver seção 10) |
| `*.csv` | resultados de cada etapa (ver seção 8) |

---

## 5. O arquivo `input.txt`

O arquivo tem seções entre colchetes. As três primeiras são o conteúdo da
pesquisa; as demais são parâmetros técnicos opcionais.

```ini
[regiao]          # onde procurar        (obrigatória)
[taxons]          # sua lista de plantas (obrigatória)
[termos_pubmed]   # atividades de interesse (opcional)
[artigos]  [taxonomia]  [ollama]  [pubmed]  [bioativos]  [chembl]   # parâmetros
```

Regras gerais:

- linhas que começam com `#` são comentários;
- números com **ponto decimal** (`-3.35`), e **vírgula** entre latitude e
  longitude (`-3.35, -64.71`);
- apagar uma chave ou uma seção técnica faz valer o valor padrão;
- o arquivo é **validado antes de qualquer etapa**. Vírgula decimal,
  latitude e longitude trocadas, ponto incompleto, pontos alinhados, nome de
  chave errado ou valor inválido geram erro indicando a linha;
- para ver como o arquivo foi interpretado, sem rodar nada:
  ```bash
  python config_pipeline.py
  ```

### 5.1 `[regiao]`: onde procurar

A região é usada de duas formas, por isso as duas ficam juntas:

1. **Coordenadas**, para o GBIF (etapa 1). Use um ponto por linha, no formato
   `latitude, longitude`:

   | Nº de pontos | Forma da região |
   |---|---|
   | 1 | círculo com centro no ponto e raio `raio_km` (padrão 10 km) |
   | 2 | retângulo (dois cantos opostos, em qualquer ordem) |
   | 3 ou mais | polígono (vértices na ordem do contorno, sem repetir o primeiro). A orientação exigida pelo GBIF é corrigida automaticamente |

   Latitude negativa indica o hemisfério sul; longitude negativa, o oeste.

2. **`termos_texto`**, para o PubMed e o OpenAlex (descoberta de plantas em
   artigos, etapa 2), que não entendem coordenadas, só palavras no título e
   no resumo. O `*` é truncamento no PubMed: `amazon*` cobre *Amazon*,
   *Amazonas*, *Amazonia*, *Amazonian*. O padrão é `amazon*, Amazonas,
   Amazônia`.

```ini
[regiao]
# polígono simplificado do estado do Amazonas
-2.2, -70.0
 1.2, -69.4
 1.4, -66.8
-0.6, -63.4
-2.4, -58.0
-7.4, -58.4
-9.4, -66.5
-7.1, -73.8
-4.2, -69.9
termos_texto = amazon*, Amazonas, Amazônia
```

> Se mudar a região, ajuste **as coordenadas e os termos**. Para o Pará, por
> exemplo: `termos_texto = Pará, Belém, amazon*`.

O nome antigo da seção, `[coordenadas]`, continua aceito.

### 5.2 `[taxons]` ou `lista_de_plantas.txt`: sua lista de plantas

A lista pode ficar em dois lugares:

| Onde | Quando usar |
|---|---|
| arquivo **`lista_de_plantas.txt`**, na mesma pasta do `input.txt` | listas grandes (milhares de nomes) |
| seção `[taxons]` do `input.txt` | listas curtas |

Se o `lista_de_plantas.txt` existir e tiver nomes, ele **substitui** a seção
`[taxons]`, que é ignorada (a tela avisa). Para voltar a usar a seção,
apague ou renomeie o arquivo. No arquivo, os nomes podem ser separados por
vírgula, ponto e vírgula ou um por linha; linhas começadas com `#` são
ignoradas.

Na seção `[taxons]`, separe os nomes por vírgula. A lista pode ocupar
várias linhas.

```ini
[taxons]
Euterpe oleracea, Carapa guianensis, Copaifera,
Theobroma cacao, Erythroxylum coca var. ipadu, Acmella sp.
```

- **Espécies** e **infraespecíficos** (`var.`, `subsp.`) são aceitos.
- **Gêneros** (`Copaifera` ou `Acmella sp.`): na busca de compostos
  (etapa 3), o gênero traz só as espécies dele que já estão na lista final
  (vindas do GBIF da região ou dos artigos) e os registros feitos só no
  nível de gênero, e **não** espécies de outras regiões. Na busca no PubMed
  (etapa 5), um gênero sozinho não é pesquisado, porque traria artigos de
  qualquer espécie do gênero.
- **Repetições literais** são removidas (a quantidade aparece na tela).
- Todos os nomes passam pela **conferência taxonômica** (etapa 2):
  sinônimos e erros leves de grafia são corrigidos para o nome aceito, e o
  nome que você escreveu fica registrado (`nome_original`) e continua sendo
  usado nas buscas.

### 5.3 `[termos_pubmed]`: atividades de interesse (opcional)

Se a seção estiver **vazia**, o pipeline procura **qualquer** atividade
biológica. Se estiver preenchida, a busca se **restringe** às atividades
listadas, em três lugares:

- na descoberta de plantas em artigos (etapa 2);
- na ligação dos ensaios do ChEMBL (etapa 4);
- na busca e no julgamento dos artigos pelo Llama (etapa 5).

Há dois formatos, que podem ser misturados:

| Linha | Efeito |
|---|---|
| `rótulo = termo1, termo2, ...` | uma atividade com sinônimos; o **rótulo** (pode ser em português) é o que aparece nos resultados |
| `termo1, termo2` | cada termo vira uma atividade separada |

```ini
[termos_pubmed]
clareadora = tyrosinase inhibit*, melanin*, melanogenesis, skin whitening
antirrugas = collagenase, elastase, wrinkle*, "skin aging"
fotoprotetora = UVB, UVA, photoprotect*, "sun protection factor"
antibacteriana = antibacterial, antimicrobial, "Anti-Bacterial Agents"[mh]
```

- Escreva os **termos em inglês**, porque vão para o PubMed.
- Os termos aceitam **truncamento** (`melanin*`) e **tags de campo do
  PubMed** (`"Anti-Bacterial Agents"[mh]` busca o descritor MeSH). No
  OpenAlex, o `*` e a tag são removidos.
- Cada atividade gera **uma busca própria** por planta e por composto, para
  que uma atividade muito estudada não ocupe a vaga das outras.
- O Llama só aceita um artigo se a planta ou o composto demonstrou **uma das
  atividades listadas**; outras atividades do mesmo resumo são ignoradas.
- **Custo**: o número de buscas da etapa 5 é multiplicado pelo número de
  atividades. Dez atividades significam dez buscas por planta.

### 5.4 Parâmetros técnicos

Todos são opcionais; a coluna "Padrão" mostra o valor usado quando a chave
não aparece no arquivo.

**`[artigos]`: descoberta de plantas em artigos (etapa 2)**

| Chave | Padrão | Função |
|---|---|---|
| `ativar` | `true` | liga ou desliga a descoberta |
| `usar_pubmed` | `true` | busca no PubMed |
| `usar_openalex` | `true` | busca no OpenAlex (substituto aberto do Google Scholar, com SciELO e revistas brasileiras) |
| `max_artigos` | `10000` | artigos lidos em cada base (0 = todos) |
| `contexto_vegetal` | `false` | `true` = exige também uma palavra de contexto vegetal no texto |
| `openalex_api_key` | vazio | chave gratuita do OpenAlex |
| `email` | vazio | e-mail de contato para o OpenAlex (se vazio, usa o de `[pubmed]`) |

**`[taxonomia]`: conferência dos nomes (etapa 2)**

| Chave | Padrão | Função |
|---|---|---|
| `usar_flora_brasil` | `true` | consulta a Flora e Funga do Brasil (prioridade 1) |
| `usar_wfo` | `true` | consulta o World Flora Online (prioridade 2) |
| `usar_gbif` | `true` | consulta o GBIF (prioridade 3; também fornece filo, classe e ordem) |
| `corrigir_grafia` | `true` | corrige erros leves de grafia quando há um nome muito parecido no mesmo gênero |
| `flora_brasil_url` / `wfo_url` | vazio | endereço alternativo de download (vazio = automático) |

**`[ollama]`: modelo de linguagem (etapa 5)**

| Chave | Padrão | Função |
|---|---|---|
| `modelo` | `llama3.1:8b` | modelo que julga os resumos |
| `url` | `http://localhost:11434` | endereço do Ollama |
| `timeout_segundos` | `180` | tempo máximo por resumo |

**`[pubmed]`: busca de atividades (etapa 5)**

| Chave | Padrão | Função |
|---|---|---|
| `plantas_pesquisadas` | `todas` | `todas` = todas as espécies de `plantas.csv`; `com_compostos` = só as que têm compostos (mais rápido) |
| `max_plantas` | `0` | teto de plantas pesquisadas (0 = sem teto). Prioriza as que têm compostos e depois as com mais ocorrências na área |
| `incluir_nao_reconhecidos` | `false` | pesquisa também os nomes que nenhuma base taxonômica reconheceu |
| `max_artigos_por_planta` | `20` | resumos mais relevantes por planta (por atividade) |
| `max_artigos_por_composto` | `10` | resumos por composto (por atividade) |
| `max_compostos` | `0` | teto de compostos pesquisados (0 = todos). Prioriza os com atividade no NPASS e os presentes em mais plantas |
| `busca_composto_por_nome` | `complemento` | `complemento`: busca por nome só para compostos sem artigos ligados ao InChIKey; `sempre`; `nunca` |
| `excluir_revisoes` | `true` | ignora artigos de revisão (interessa a evidência experimental primária) |
| `ncbi_api_key` | vazio | chave gratuita do NCBI (≈3× mais rápido) |
| `email` | vazio | e-mail de contato para o NCBI (se vazio, usa `GBIF_EMAIL`) |

**`[bioativos]`: compostos (etapa 3)**

| Chave | Padrão | Função |
|---|---|---|
| `apenas_com_atividade_npass` | `false` | `true` = só compostos com ao menos um registro de atividade no NPASS |
| `incluir_nao_reconhecidos` | `false` | busca também plantas de nome não reconhecido (em geral, organismos que não são plantas citados em artigos) |
| `coconut_url` | vazio | força uma versão específica do COCONUT |
| `usar_duke` | `true` | usa também o Dr. Duke (parte da planta, teor e atividades por composto) |
| `duke_url` | vazio | endereço alternativo do export do Dr. Duke |

**`[chembl]`: ensaios (etapa 4)**

| Chave | Padrão | Função |
|---|---|---|
| `ativar` | `true` | liga ou desliga a etapa 4 |
| `pchembl_minimo` | `5` | potência mínima para contar como ativo (5 = até 10 µM; 6 = até 1 µM) |
| `estereoisomeros` | `true` | se o InChIKey exato não existe no ChEMBL, usa moléculas com a mesma conectividade |
| `prever_por_similaridade` | `false` | para compostos sem dados, mostra atividades de moléculas parecidas (**hipótese**) |
| `similaridade_minima` | `85` | similaridade mínima, em % (70 a 100) |
| `estruturas_url` | vazio | endereço alternativo do arquivo de estruturas |

As chaves de versões anteriores (`max_artigos_por_atividade`, `termos_regiao`, `incluir_plantas_listadas`,
`filtro_ocorrencia`, `estados`, `dominios` em `[artigos]`) são aceitas e
ignoradas, com aviso.

---

## 6. Como rodar

### 6.1 Primeira execução, passo a passo

```bash
# 1. entre na pasta do pipeline
cd caminho/da/pasta

# 2. confira se o input.txt foi entendido
python config_pipeline.py

# 3. carregue as credenciais do GBIF (ver 3.2)
source gbif_credenciais.env        # Windows cmd: gbif_credenciais.bat

# 4. (opcional) baixe as bases antes, por exemplo à noite
python main.py --somente downloads

# 5. rode tudo
python main.py
```

> **Dica para um primeiro teste**: em `[pubmed]`, use `max_plantas = 300` e
> `max_compostos = 200`. Assim você vê os resultados em poucas horas e
> confere se a configuração está como queria. Depois volte para `0` e rode
> `python main.py --a-partir-de pubmed`. O que já foi feito não é refeito.

### 6.2 Todos os comandos

| Comando | Efeito |
|---|---|
| `python main.py` | pipeline completo, com `input.txt` |
| `python main.py --input outro.txt` | usa outro arquivo de entrada |
| `python main.py --a-partir-de ETAPA` | começa na etapa indicada e segue até o fim |
| `python main.py --somente ETAPA` | roda só a etapa indicada |
| `python main.py --retomar` | pula as etapas cujo arquivo de saída já existe |
| `python main.py --pular-downloads` | não roda a etapa 0 |
| `python main.py --atualizar-bases` | baixa de novo as bases para pegar versões novas (ver 7.0) |
| `python main.py --sem-gbif` | ignora a região no GBIF: a lista fica só com a sua lista e os artigos |

Nomes de etapa (`ETAPA`): `downloads`, `gbif`, `plantas`, `bioativos`,
`chembl`, `pubmed`.

As opções podem ser combinadas, por exemplo
`python main.py --a-partir-de bioativos --pular-downloads`.

Cada etapa também pode ser rodada diretamente (`python
consultar_chembl.py`), mas o `main.py` valida o `input.txt` antes e mostra o
tempo de cada etapa.

### 6.3 Quando algo dá errado

Se uma etapa falhar, o pipeline **para** e mostra o comando para retomar
dela. Como todas as consultas ficam em cache (seção 10), retomar não refaz o
que já foi feito: o pipeline continua de onde parou, mesmo no meio de uma
etapa longa. Interromper com `Ctrl+C` também é seguro.

### 6.4 Mudei o `input.txt`. O que rodar de novo?

| O que mudou | Rode a partir de |
|---|---|
| coordenadas da região | `gbif` |
| `termos_texto`, `[taxons]`, `[artigos]`, `[taxonomia]` | `plantas` |
| `[bioativos]` | `bioativos` |
| `[chembl]` | `chembl` |
| `[termos_pubmed]` | `plantas` (a descoberta em artigos usa as atividades) |
| `[pubmed]` ou `[ollama]` | `pubmed` |

> ⚠️ **Não use `--retomar` depois de mudar o `input.txt`.** Ele só verifica
> se o arquivo de saída existe, e pularia etapas que precisam ser refeitas.
> Use `--a-partir-de`.

---

## 7. As etapas em detalhe

### 7.0 Etapa 0: `downloads` (`baixar_bases.py`)

Baixa as bases que o pipeline usa como **arquivos inteiros**:

| Base | Usada na etapa | Onde fica |
|---|---|---|
| Flora e Funga do Brasil (DwC-A do IPT/JBRJ) | 2 | `dados_flora_brasil/flora_brasil_dwca.zip` |
| World Flora Online (*WFO Plant List*, publicada no Zenodo a cada seis meses; versão mais recente encontrada automaticamente) | 2 | `dados_wfo/WFO_Backbone.zip` |
| COCONUT (CSV completo, com organismos de origem) | 3 | `dados_bioativos/coconut_csv.zip`, `coconut_extraido/`, `coconut_versao.txt` |
| NPASS 3.0 (6 arquivos) | 3 | `dados_bioativos/npass_*.txt` |
| Dr. Duke's Phytochemical and Ethnobotanical Databases (export CSV do USDA) | 3 (se `usar_duke = true`) | `dados_bioativos/duke_csv.zip` + `duke_extraido/` |
| ChEMBL: estruturas (`chemreps.txt.gz`) | 4 (se `[chembl] ativar = true`) | `dados_chembl/chembl_chemreps.txt.gz` |

- **Primeira vez**: baixa tudo (de 15 a 40 minutos, conforme a conexão).
- **Nas vezes seguintes**: só confere que os arquivos estão lá e termina em
  segundos. Ao final mostra um resumo `[OK]` / `[FALHOU]` com o tamanho de
  cada arquivo e grava `bases_baixadas.txt`.
- **Se um download falhar**: sem o ChEMBL, a etapa 4 usa a API, que é mais
  lenta. Sem qualquer outra base, a etapa para com erro.
- **`--atualizar-bases`** baixa versões novas com segurança:
  - a versão atual é guardada como `*.anterior` e só é apagada quando o
    download novo termina. Se ele falhar (sem internet, servidor fora), a
    versão antiga volta e o pipeline segue com ela;
  - o COCONUT só é baixado se a versão publicada for diferente da instalada;
  - os caches que dependem das bases atualizadas
    (`cache_taxonomia_flora.jsonl`, `cache_taxonomia_wfo.jsonl`,
    `cache_chembl_*.jsonl`) são apagados, para não misturar versões.
- O **GBIF não entra aqui**: o download dele depende da região e fica na
  etapa 1.
- **Download manual**: se um servidor recusar o programa, baixe o arquivo
  pelo navegador e salve-o com o nome e na pasta da tabela acima (a mensagem
  de erro mostra o endereço e o caminho exatos). Na próxima rodada a etapa o
  encontra e segue.
- As etapas 2, 3 e 4 ainda conseguem baixar um arquivo que esteja faltando
  (caso você use `--pular-downloads` sem ter as bases), mas não procuram
  atualizações.

### 7.1 Etapa 1: `gbif` (`buscar_especies_gbif.py`) → `especies_gbif.csv`

Levanta **todas as plantas com registro de ocorrência dentro da região**.

**Como funciona**

1. Envia ao GBIF um pedido de download (formato `SPECIES_LIST`, sem limite
   de paginação) com estes filtros:
   - ponto dentro da região (círculo, retângulo ou polígono);
   - reino **Plantae**;
   - registro com coordenada e sem problema geoespacial;
   - status de ocorrência **presente** (exclui registros de ausência).
2. Espera o GBIF preparar o arquivo (de 5 minutos a 1 hora, conforme a fila).
3. Agrega sinônimos e infraespecíficos na espécie aceita (`speciesKey`),
   somando as ocorrências.
4. Busca o nome popular em português das espécies com mais ocorrências (até
   1.500 consultas).

**Reaproveitamento**: a chave de cada pedido fica em
`dados_gbif_download/pedidos.json`. Rodar de novo com a **mesma região**
reaproveita o download, sem gastar cota nem esperar a fila. Para usar um
download específico já feito no site do GBIF, defina a variável
`GBIF_DOWNLOAD_KEY` com a chave dele.

**Colunas de `especies_gbif.csv`**: `speciesKey`, `reino`, `filo`,
`classe`, `ordem`, `familia`, `nome_cientifico`, `nome_popular_pt`,
`categoria_taxonomica`, `n_ocorrencias_na_area`. A lista vem ordenada pelo
número de ocorrências.

### 7.2 Etapa 2: `plantas` (`montar_lista_plantas.py`) → `plantas.csv`

Monta a **lista final de plantas**, com nomes conferidos, antes de qualquer
busca de compostos ou atividades.

#### a) Três fontes de plantas

| Fonte | O que entra |
|---|---|
| `gbif` | plantas com ocorrência na região (etapa 1) |
| `lista` | sua lista (`lista_de_plantas.txt` ou a seção `[taxons]`) |
| `artigos` | plantas citadas em artigos que mencionam a região |

**Descoberta em artigos** (`descoberta_artigos.py`). A busca usa **só os
termos da região** (`termos_texto`, em `[regiao]`): entra todo artigo com
resumo que cite a região, seja qual for o tema.

- **As atividades não filtram a busca.** As atividades de `[termos_pubmed]`
  só são **anotadas**: quando um artigo cita um termo de uma atividade, as
  plantas desse artigo recebem a atividade na coluna `atividades_artigos`
  (ex.: `clareadora (3 artigos)`).
- **Bases**: **PubMed** e **OpenAlex**, até `max_artigos` em cada uma
  (padrão 10 mil). O PubMed só entrega 10 mil resultados por busca; acima
  disso, a busca é dividida automaticamente por ano de publicação.
- **Conferência do OpenAlex**: a busca do OpenAlex reduz as palavras ao
  radical e traz trabalhos que não citam a região. Cada trabalho é conferido
  no texto e só fica se o título ou o resumo citar um termo da região, com
  o mesmo sentido do PubMed (palavra inteira, `*` como truncamento, sem
  diferença de acentos).
- **Contexto vegetal** (opcional, `contexto_vegetal = true`): exige também
  uma palavra como *plant*, *extract*, *leaves* ou *bark*. Isso reduz os
  artigos de outros temas (malária, mercúrio, desmatamento…).
- **Extração dos nomes**: os nomes científicos do título e do resumo são
  extraídos, inclusive os abreviados (*E. oleracea*). Expressões que só
  parecem nomes científicos ("The extract", "Tyrosinase inhibition") são
  descartadas por listas de exclusão e por regras de terminação de palavras
  inglesas. Revisões entram, porque costumam listar muitas plantas.
- **Nomes que não são plantas**: como a busca não filtra o tema, aparecem
  também animais, parasitas e microrganismos (*Plasmodium falciparum*,
  *Aedes aegypti*). Um nome vindo **só de artigos** que nem a Flora e Funga
  do Brasil nem o WFO reconhecem **não é consultado no GBIF**, para poupar
  tempo (o WFO cobre as plantas do mundo todo), e fica como `não
  reconhecido`. Esses nomes não são usados nas etapas 3 e 5.
- **Não há filtro de ocorrência**: a ligação com a região vem do texto do
  artigo.

#### b) Conferência dos nomes em três bases (`taxonomia.py`)

**Todos** os nomes, de qualquer fonte, são conferidos:

| Prioridade | Base | Como é consultada | O que fornece |
|---|---|---|---|
| 1 | **Flora e Funga do Brasil** (JBRJ) | lista oficial baixada (etapa 0) | nome aceito ou sinônimo, família |
| 2 | **World Flora Online** (WFO) | lista mundial baixada (etapa 0) | nome aceito ou sinônimo, família |
| 3 | **GBIF** | API, um nome por vez (só para nomes que não vieram da etapa 1) | nome aceito ou sinônimo, filo, classe, ordem, família |

- Cada nome é **corrigido para o nome aceito**. Quando as bases discordam,
  vale a de maior prioridade, e a divergência fica anotada.
- **Erros leves de grafia** (ex.: *Alpinia speciosas*) são corrigidos quando
  há um nome muito parecido **no mesmo gênero** (`corrigir_grafia`).
- Um nome que **nenhuma base reconhece** **continua na lista**, marcado como
  `não reconhecido`, com aviso. Em geral são organismos que não são plantas
  (bactérias, fungos, insetos) citados nos artigos.

#### c) Uma linha por planta

Nomes que levam ao mesmo nome aceito viram **uma única linha**. Por exemplo,
*Pothomorphe umbellata* (sua lista) e *Piper umbellatum* (GBIF) viram uma
linha *Piper umbellatum*, com os dois nomes guardados em `nomes_busca`.

#### d) Informações complementares

Família, ordem, classe e filo vêm do GBIF; sem GBIF, a família vem da Flora
e Funga do Brasil ou do WFO. O número de ocorrências na área e o nome
popular também são consultados no GBIF para as plantas da sua lista e dos
artigos, só como informação, sem filtrar nada.

#### Saídas da etapa 2

**`plantas.csv`**: uma linha por planta.

| Coluna | Conteúdo |
|---|---|
| `speciesKey` | identificador da espécie no GBIF |
| `reino`, `filo`, `classe`, `ordem`, `familia` | taxonomia |
| `nome_cientifico` | **nome aceito** (usado em todas as etapas seguintes) |
| `nome_popular_pt` | nome popular em português (GBIF) |
| `categoria_taxonomica` | `SPECIES`, `GENUS`, `VARIETY`… |
| `n_ocorrencias_na_area` | registros do GBIF dentro da região |
| `nome_original` | nome(s) como apareceram nas fontes |
| `situacao_nome` | `aceito`, `aceito (sem status confirmado)`, `sinônimo corrigido`, `grafia corrigida`, `grafia e sinônimo corrigidos`, `gênero` ou `não reconhecido` |
| `nomes_busca` | **todos** os nomes da planta (original e aceitos de cada base), separados por `;`. As etapas 3 e 5 buscam por todos eles |
| `observacoes_taxonomia` | o que cada base disse, divergências de nome e de família, avisos |
| `fonte` | `gbif`, `lista`, `artigos` ou combinações |
| `atividades_artigos` | atividades do input citadas nos artigos da descoberta, ex.: `clareadora (3 artigos)`. Indica só o tema: quem julga causa e efeito é o Llama, na etapa 5 |

**`plantas_conferencia_taxonomica.csv`**: **um nome científico por linha**,
seja ele o original ou o aceito, para conferir as decisões taxonômicas. Um
sinônimo corrigido gera duas linhas seguidas:

| nome_cientifico | fonte | status | veredito_flora | veredito_wfo | veredito_gbif |
|---|---|---|---|---|---|
| Pothomorphe umbellata | lista | sinônimo corrigido para Piper umbellatum | sinônimo de… | sinônimo de… | sinônimo de… |
| Piper umbellatum | gbif | original (nome aceito); nome aceito de Pothomorphe umbellata | aceito | aceito | aceito |

A coluna `fonte` pode ser `lista`, `gbif`, `artigos` ou `correção (base)`,
quando o nome aceito surgiu só da correção.

**`plantas_artigos_evidencias.csv`**: uma linha por planta × artigo da
descoberta (nome no artigo, nome aceito, atividades do input citadas no
texto, base, PMID ou DOI, ano, título).

### 7.3 Etapa 3: `bioativos` (`cruzar_especies_bioativos.py`) → `especies_com_compostos_bioativos.csv`

Busca os **compostos já registrados** para cada planta em três bases de
produtos naturais:

| Base | O que é usado |
|---|---|
| **COCONUT** | CSV completo: compostos, **organismos de origem**, SMILES, InChIKey, classificação química |
| **NPASS 3.0** | pares composto–espécie, taxonomia das espécies, nomes e estruturas dos compostos, **atividades** e **alvos** medidos |
| **Dr. Duke** (USDA, opcional) | composto × planta × **parte da planta** × **teor (ppm)**, e **atividades biológicas** atribuídas a cada composto na literatura |

**Dr. Duke**: a base não traz InChIKey, só o nome do composto (ex.:
`CAFFEIC-ACID`). O InChIKey é obtido no **PubChem**, pelo nº CAS quando
existe e senão pelo nome (cache em `cache_pubchem_duke.jsonl`). Com o
InChIKey, o composto se une ao mesmo composto vindo do COCONUT ou do NPASS
(ex.: `base = COCONUT; DUKE`). Compostos que o PubChem não reconhece ficam
sem InChIKey, com `base = DUKE`. Na primeira vez são feitas de uma a três
consultas por composto (alguns minutos a poucas horas, conforme o tamanho
da lista); depois, tudo vem do cache. Se o Dr. Duke não puder ser lido, a
etapa segue só com COCONUT e NPASS, com aviso.

**Regras da busca**

- Cada planta é procurada por **todos os nomes** de `nomes_busca`: um
  composto registrado sob um sinônimo vai para a linha do nome aceito.
- Plantas `não reconhecido` **não são buscadas** (`incluir_nao_reconhecidos =
  true` muda isso), para não trazer compostos de bactérias ou fungos.
- **Gêneros** da sua lista trazem os registros feitos só no nível de gênero
  ("*Copaifera* sp.") e as espécies do gênero que **já estão em
  `plantas.csv`**. As demais espécies do gênero encontradas nas bases ficam
  de fora e são listadas na tela.
- O mesmo composto vindo das duas bases, ou de dois nomes da mesma planta,
  vira **uma linha** (unificado pelo InChIKey).

**Colunas**, uma linha por composto × planta, **ordenadas pelo nome do
composto** (o mesmo composto em várias plantas fica junto):

| Coluna | Conteúdo |
|---|---|
| `composto_nome` | nome do composto |
| `composto_id` | identificador no COCONUT (`CNP…`) ou no NPASS (`NPC…`) |
| `composto_inchikey` | InChIKey (identificador da estrutura) |
| `especie_normalizada` | nome da planta como está na base de compostos |
| `base` | `COCONUT`, `NPASS` ou ambas |
| `atividade_ou_alvo` | alvos e tipos de medida do NPASS |
| `nome_cientifico`, `reino`, `familia`, `nome_popular_pt`, `fonte` | dados da planta (de `plantas.csv`) |
| `pubchem_cid` | identificador no PubChem (usado na etapa 5) |
| `composto_smiles` | estrutura em SMILES (usada na previsão da etapa 4) |
| `np_classifier_pathway`, `np_classifier_superclass`, `np_classifier_class` | via biossintética e classe (NP Classifier) |
| `chemical_class` | classe química (ClassyFire) |
| `qed_drug_likeliness` | semelhança com fármacos (QED, de 0 a 1) |
| `np_likeness` | semelhança com produtos naturais |
| `molecular_formula` | fórmula molecular |
| `parte_planta_duke` | partes da planta em que o composto foi registrado no Dr. Duke (ex.: `Seed; Leaf`) |
| `teor_ppm_duke` | teor registrado por parte (ex.: `Seed: 10000-30000 ppm`) |
| `atividades_duke` | atividades atribuídas ao composto no Dr. Duke. Com `[termos_pubmed]`, só as que casam com as suas, por rótulo (ex.: `clareadora (Tyrosinase-Inhibitor)`); sem, todas (até 40) |

### 7.4 Etapa 4: `chembl` (`consultar_chembl.py`) → `compostos_chembl.csv`

Busca no **ChEMBL** as atividades **medidas em ensaios** de cada composto.
É um **complemento** ao PubMed: traz dados quantitativos (IC50, Ki, %
de inibição) de artigos de química medicinal.

**Como funciona**

1. **Localização pelo InChIKey**: os InChIKeys são comparados com o arquivo
   de estruturas do ChEMBL, localmente (se o arquivo faltar, a etapa usa a
   API).
2. **Estereoisômeros** (`estereoisomeros = true`): se o InChIKey completo
   não existe no ChEMBL, procura moléculas com a mesma **conectividade** (os
   14 primeiros caracteres do InChIKey), até 5 por composto. Em geral é o
   mesmo produto natural registrado com outra configuração espacial. O
   resultado é marcado como tal, porque estereoisômeros podem ter atividades
   diferentes.
3. **Registros de atividade**: conta como **ativo** o registro com `pChEMBL ≥
   pchembl_minimo` (padrão 5, isto é, até 10 µM) ou marcado como ativo pelo
   próprio ChEMBL. Registros com alerta de validade são descartados.
4. **Ligação com as suas atividades**: o nome do alvo e a descrição do
   ensaio são comparados ao "núcleo" de cada termo de `[termos_pubmed]`
   (`tyrosinase inhibit*` → *tyrosinase*). Os núcleos usados aparecem na
   tela.
5. **Documento de origem**: para cada registro, o documento do ChEMBL é
   consultado, e o **PMID**, o DOI, o ano e a revista são anotados.
6. **Previsão por similaridade** (opcional, desligada por padrão): para
   compostos sem nenhum dado, mostra as atividades de moléculas
   estruturalmente parecidas (a partir do SMILES), numa coluna própria. É
   uma **hipótese**, não uma evidência.

**Colunas de `compostos_chembl.csv`** (anexadas às saídas da etapa 5):

| Coluna | Exemplo |
|---|---|
| `InChIKey` | `RKWHWFJMBLWYHU-UHFFFAOYSA-N` |
| `chembl_id` | `CHEMBL1234` |
| `correspondencia_chembl` | `exata` ou `estereoisômero (mesma conectividade)` |
| `atividades_chembl` | `clareadora (Tyrosinase, IC50 = 900 nM, 2 registros; PMID 11111, 22222)` |
| `atividades_previstas_chembl` | só com a previsão ligada |

**`evidencias_chembl.csv`**: uma linha por registro de ensaio usado
(composto, atividade, correspondência, molécula ensaiada, alvo, organismo,
ensaio, tipo de medida, valor, pChEMBL, PMID, DOI, ano, revista, documento
do ChEMBL).

### 7.5 Etapa 5: `pubmed` (`consultar_atividades_pubmed.py`)

Procura no **PubMed** artigos sobre as atividades das **plantas** e dos
**compostos**, e usa o **Llama** para manter só os que demonstram
experimentalmente um efeito.

#### a) Quais plantas são pesquisadas

Por padrão, **todas as espécies de `plantas.csv`**, inclusive as que não
têm nenhum composto no COCONUT ou no NPASS: uma planta pouco estudada
quimicamente pode ter atividade relatada para o extrato.

- **Ordem**: primeiro as que têm compostos (das com mais compostos para as
  com menos), depois as com mais ocorrências na área.
- **Ficam de fora**:
  - gêneros sem espécie;
  - nomes `não reconhecido` (salvo `incluir_nao_reconhecidos = true`);
  - as plantas sem compostos, se `plantas_pesquisadas = com_compostos`;
  - as que passam do teto, se `max_plantas` > 0.

#### b) Como os artigos são encontrados

**Plantas**: busca no título e no resumo por **todos os nomes** da planta
(`nomes_busca`, unidos com OR), uma busca por atividade, até
`max_artigos_por_planta` artigos (os mais relevantes).

**Compostos**: duas vias combinadas.

1. **Pelo InChIKey** (identificação pela estrutura, sem depender do nome):
   InChIKey → CID no PubChem (do NPASS ou consultado em lotes de 200) →
   artigos que o PubChem associa ao composto (indexação MeSH da NLM e
   vínculos de depositantes) → filtro pelos artigos que tratam das suas
   atividades, têm resumo e não são revisões.
2. **Pelo nome**, conforme `busca_composto_por_nome`: com `complemento`
   (padrão), só para compostos sem nenhum artigo ligado ao InChIKey. Nomes
   sistemáticos (IUPAC) e códigos de banco não são pesquisados, porque não
   aparecem nos resumos; prefixos como `(-)-` são removidos
   (`(-)-epicatechin` → `epicatechin`).

**Pré-checagem**: com mais de uma atividade em `[termos_pubmed]`, cada
planta ou composto passa antes por **uma** busca com todas as atividades
juntas. Só quem tem algum artigo segue para as buscas por atividade. Como a
grande maioria das plantas não tem artigo nenhum sobre as atividades, isso
troca, por exemplo, 9 buscas por 1.

**Pré-filtro**: artigos achados pelo nome precisam citar a planta (qualquer
um dos nomes, inclusive abreviado) ou o composto no título ou no resumo.

#### c) Julgamento pelo Llama

O Llama lê cada par **entidade × resumo** e responde em JSON:

- **Positivo**: o texto relata um **resultado experimental** (in vitro, ex
  vivo, in vivo ou clínico) em que a planta (extrato, fração, óleo, resina,
  substância isolada dela) ou o composto **produziu** o efeito. Exemplo: "o
  extrato etanólico das folhas inibiu o crescimento de *S. aureus* (CIM 125
  µg/mL)".
- **Negativo**:
  - a entidade é só mencionada, ou o efeito é de outra espécie ou composto;
  - uso tradicional ou etnobotânico, sem teste;
  - resultado nulo, fraco ou não significativo;
  - química analítica ou isolamento sem ensaio biológico;
  - revisão ou especulação ("pode ter", "potencialmente útil");
  - estudo **só in silico** (docking, simulação).
- Se houver `[termos_pubmed]`, só contam as **atividades listadas**.
- Quando a planta tem sinônimos, o Llama é avisado ("mesma planta, também
  citada como…"), para não rejeitar um artigo que use outro nome.

Para cada artigo positivo, o Llama informa também:

| Informação | Valores possíveis |
|---|---|
| **tipo de estudo** | `in vitro` (células, enzimas, microrganismos), `ex vivo` (tecidos ou órgãos isolados), `in vivo` (animais), `clínico` (seres humanos) |
| **parte da planta** (só para plantas) | `folha`, `caule`, `casca`, `raiz`, `rizoma`, `tubérculo/bulbo`, `flor`, `fruto`, `semente`, `parte aérea`, `planta inteira`, `exsudato (látex/resina)`, `broto/calo/cultura` ou `não informado` |

A **melhor evidência** de uma planta ou composto é o tipo de estudo mais
forte entre os artigos positivos: **clínico > in vivo > ex vivo > in
vitro**.

**Ordem de leitura pelo Llama**: primeiro as plantas (na ordem de
prioridade da busca), depois os compostos (os com atividade no NPASS e
presentes em mais plantas primeiro).

**Resultados parciais**: a leitura pelo Llama pode levar dias. Para ver as
planilhas com o que já foi lido, abra **outra janela** do terminal, na
mesma pasta, e rode:

```bash
python consultar_atividades_pubmed.py --parcial
```

Isso não lê nenhum artigo novo nem atrapalha a rodada principal. Plantas e
compostos ainda não lidos aparecem como `artigos encontrados; leitura pelo
Llama pendente`. Ao terminar, a rodada principal sobrescreve as planilhas
com a versão completa.

#### d) Saídas da etapa 5

Há quatro arquivos, descritos em detalhe na seção 8:

| Arquivo | Uma linha por |
|---|---|
| `atividades_plantas.csv` | planta de `plantas.csv` (todas, pesquisadas ou não) |
| `atividades_compostos.csv` | composto |
| `especies_atividades.csv` | par planta × composto (visão combinada) |
| `evidencias_pubmed.csv` | artigo positivo |

---

## 8. Guia dos arquivos de resultado

### 8.1 Qual arquivo abrir para cada pergunta

| Pergunta | Arquivo |
|---|---|
| Que plantas entraram na lista, e de onde vieram? | `plantas.csv` |
| Por que um nome foi corrigido? O que cada base disse? | `plantas_conferencia_taxonomica.csv` |
| Que **plantas** têm atividade demonstrada, com que evidência e em que parte? | `atividades_plantas.csv` |
| Que **compostos** têm atividade demonstrada (PubMed e ChEMBL), e em que plantas ocorrem? | `atividades_compostos.csv` |
| Visão completa planta × composto, com tudo junto | `especies_atividades.csv` |
| Qual artigo sustenta cada resultado? | `evidencias_pubmed.csv`, `evidencias_chembl.csv` |
| Que compostos cada planta tem (sem atividades)? | `especies_com_compostos_bioativos.csv` |

### 8.2 `atividades_plantas.csv`

Uma linha por planta de `plantas.csv`, ordenadas pelo **número de artigos
positivos** (as mais estudadas primeiro) e depois pelo nome.

| Coluna | Conteúdo |
|---|---|
| `nome_cientifico`, `familia`, `nome_popular_pt` | identificação |
| `situacao_nome`, `fonte`, `n_ocorrencias_na_area` | vindas de `plantas.csv` |
| `n_compostos` | compostos conhecidos (etapa 3) |
| `atividades_relatadas_planta` | ex.: `anti-inflamatória (PMID 123, 456); antioxidante (PMID 789)`, ou o motivo de não haver resultado (seção 9) |
| `melhor_evidencia_planta` | `clínico`, `in vivo`, `ex vivo`, `in vitro` ou `não informado` |
| `estudos_planta` | ex.: `in vivo (PMID 456); in vitro (PMID 123, 789)` |
| `partes_planta` | ex.: `folha (PMID 123, 789); casca (PMID 456)` |
| `n_artigos_positivos` | número de artigos positivos distintos |
| `compostos_com_atividade_relatada` | compostos desta planta com atividade positiva no PubMed |

### 8.3 `atividades_compostos.csv`

Uma linha por composto (unificado pelo InChIKey), ordenadas pelo número de
artigos positivos e depois pelo nome.

| Coluna | Conteúdo |
|---|---|
| `composto_nome` | nome nas bases de produtos naturais |
| `nome_pubchem` | nome preferido no PubChem |
| `InChIKey`, `pubchem_cid` | identificadores |
| `composto_ids` | identificadores no COCONUT e no NPASS |
| `plantas`, `n_plantas` | plantas da lista em que o composto ocorre |
| `atividades_relatadas_composto` | ex.: `clareadora (PMID 111, 222)` |
| `melhor_evidencia_composto`, `estudos_composto` | como nas plantas |
| `n_artigos_positivos` | artigos positivos distintos |
| `chembl_id`, `correspondencia_chembl`, `atividades_chembl`, `atividades_previstas_chembl` | da etapa 4 |

### 8.4 `especies_atividades.csv`

A visão combinada: uma linha por **composto × planta** (as mesmas linhas de
`especies_com_compostos_bioativos.csv`), com todas as colunas daquele
arquivo e mais:

- `InChIKey` (validado ou completado pelo PubChem) e `pubchem_cid`;
- `atividades_relatadas_composto`, `melhor_evidencia_composto`,
  `estudos_composto`;
- `atividades_relatadas_planta`, `melhor_evidencia_planta`,
  `estudos_planta`, `partes_planta`;
- as colunas do ChEMBL.

Plantas **sem compostos conhecidos** não aparecem aqui. Elas estão em
`atividades_plantas.csv`.

### 8.5 `evidencias_pubmed.csv`

Uma linha por artigo positivo:

| Coluna | Conteúdo |
|---|---|
| `tipo_entidade` | `planta` ou `composto` |
| `entidade` | nome da planta ou do composto |
| `InChIKey` | só para compostos |
| `PMID`, `ano`, `revista`, `titulo`, `DOI`, `link` | referência |
| `atividades` | atividades demonstradas no artigo |
| `tipo_estudo` | in vitro / ex vivo / in vivo / clínico |
| `parte_planta` | só para plantas |
| `justificativa_llm` | frase curta do Llama citando o resultado |
| `via_busca` | `nome`, `InChIKey` ou `InChIKey + nome` |

### 8.6 Sugestão de leitura dos resultados

1. Em `atividades_plantas.csv`, filtre `n_artigos_positivos > 0` e ordene
   por `melhor_evidencia_planta`. Plantas com estudo **in vivo** ou
   **clínico** e **poucos artigos** podem ser oportunidades pouco
   exploradas.
2. Em `partes_planta`, veja se a atividade vem de uma parte de coleta
   sustentável (folha, fruto, semente, exsudato) ou destrutiva (raiz,
   casca, planta inteira).
3. Em `atividades_compostos.csv`, procure compostos com atividade
   **tanto no PubMed quanto no ChEMBL**: são os mais bem sustentados.
4. Confira os resultados que importam em `evidencias_pubmed.csv`, abrindo
   o `link`: o Llama faz uma triagem, não uma revisão sistemática.

---

## 9. Mensagens de status nas planilhas

Quando não há atividade, a célula explica o motivo:

| Mensagem | Significado | O que fazer |
|---|---|---|
| `nenhuma relação causal positiva encontrada` | houve artigos, mas o Llama não achou resultado positivo (para as atividades de `[termos_pubmed]`, se houver) | — |
| `nenhum artigo encontrado no PubMed` | a busca não retornou artigos | — |
| `busca pendente (rode de novo)` | a busca falhou (rede, limite do NCBI) | `python main.py --a-partir-de pubmed` |
| `não pesquisado: táxon sem nível de espécie` | gênero sozinho | — |
| `não pesquisado: nome não reconhecido em nenhuma base…` | nome não reconhecido | `[pubmed] incluir_nao_reconhecidos = true`, se quiser |
| `não pesquisado: plantas_pesquisadas = com_compostos` | planta sem compostos, excluída pela opção | `plantas_pesquisadas = todas` |
| `não pesquisado: fora do limite max_plantas` | passou do teto | aumente ou zere `max_plantas` |
| `não pesquisado: fora do limite max_compostos` | passou do teto | aumente ou zere `max_compostos` |
| `não pesquisado: sem vínculo no PubChem e sem nome adequado para busca` | composto sem CID ligado a artigos e com nome só sistemático | — |

Na coluna `atividades_chembl`:

| Mensagem | Significado |
|---|---|
| `sem InChIKey válido` | o composto não tem estrutura identificável |
| `composto não encontrado no ChEMBL` | nem o InChIKey nem estereoisômeros estão no ChEMBL |
| `no ChEMBL, sem atividade do input medida como ativa` | está no ChEMBL, mas sem registro ativo para as suas atividades |
| `consulta pendente (rode de novo)` | a consulta falhou; rode a etapa de novo |

---

## 10. Caches, retomada e atualização

Toda consulta externa é gravada em um arquivo `cache_*.jsonl`, uma linha
por consulta, no momento em que termina. Por isso:

- interromper (`Ctrl+C`, queda de luz, falha de rede) **não perde
  trabalho**: ao rodar de novo, o pipeline continua de onde parou;
- mudar parâmetros não exige apagar caches: as chaves incluem a consulta
  exata, o modelo do Llama e as atividades de `[termos_pubmed]`, de modo
  que só o que mudou é refeito.

| Cache | Guarda | Apague para… |
|---|---|---|
| `cache_taxonomia_flora.jsonl`, `cache_taxonomia_wfo.jsonl`, `cache_taxonomia_gbif.jsonl` | veredito de cada base para cada nome | reconferir os nomes (feito automaticamente com `--atualizar-bases`) |
| `cache_gbif_extras.jsonl` | ocorrências e nome popular das plantas da lista e dos artigos | atualizar esses dados |
| `cache_openalex.jsonl` | buscas no OpenAlex | buscar artigos novos |
| `cache_pubmed_buscas.jsonl` | PMIDs de cada busca no PubMed | buscar artigos publicados depois da última rodada |
| `cache_pubmed_artigos.jsonl` | títulos e resumos baixados | (raramente necessário) |
| `cache_pubmed_filtro.jsonl` | filtro de atividade dos artigos ligados ao InChIKey | buscar artigos novos |
| `cache_pubchem.jsonl`, `cache_pubchem_cid.jsonl` | InChIKey, nome e CID de cada composto | atualizar identificadores |
| `cache_pubchem_vinculos.jsonl` | artigos ligados a cada CID | buscar vínculos novos |
| `cache_llm_classificacao.jsonl` | julgamento do Llama para cada par entidade × artigo | **reavaliar** todos os artigos (demorado) |
| `cache_chembl_*.jsonl` | moléculas, atividades, estereoisômeros, documentos, similares | atualizar o ChEMBL (feito automaticamente com `--atualizar-bases`) |

Para refazer uma busca do zero, apague o cache correspondente e rode a
etapa de novo. **Não** apague `cache_llm_classificacao.jsonl` sem
necessidade: ele guarda as horas de trabalho do Llama.

---

## 11. Tempo de execução e escala

| Etapa | Primeira vez | Nas seguintes |
|---|---|---|
| 0, downloads | 15–40 min (conexão) | segundos |
| 1, GBIF | 5 min a ~1 h (fila do GBIF) | segundos (reaproveita o pedido) |
| 2, plantas | minutos a algumas horas: leitura do WFO, descoberta em artigos, cerca de 3 consultas ao GBIF por nome da lista e dos artigos | minutos (cache) |
| 3, bioativos | poucos minutos | poucos minutos |
| 4, ChEMBL | minutos a poucas horas; a previsão por similaridade pode levar muitas horas | minutos (cache) |
| 5, PubMed + Llama | **horas a dias** | só o que falta |

**Listas grandes** (dezenas de milhares de nomes em `lista_de_plantas.txt`):
na etapa 2, cada nome que não veio do levantamento do GBIF da região gera
de 3 a 5 consultas ao GBIF (conferência do nome, ocorrências na área, nome
popular). Com 30 mil nomes, a primeira rodada pode levar de 10 a 20 horas;
tudo fica em cache e pode ser interrompido e retomado.

**O que pesa na etapa 5**

- **Buscas no PubMed** ≈ nº de plantas pesquisadas × nº de atividades, mais
  as buscas de compostos pelo nome. Com a chave do NCBI são cerca de 8 por
  segundo; sem ela, cerca de 3.
- **Leituras do Llama** ≈ nº de artigos encontrados. A 5–30 s por resumo
  em CPU, dez mil resumos levam de 14 a 80 horas.

Uma região grande (como o estado do Amazonas) pode ter milhares de espécies
no GBIF. Para controlar o tempo:

- use `max_plantas` (ex.: `300`) e `max_compostos` (ex.: `200`) num primeiro
  teste;
- restrinja as atividades em `[termos_pubmed]`;
- use `plantas_pesquisadas = com_compostos`;
- reduza `max_artigos_por_planta`;
- use GPU, ou o `llama3.2:3b` em CPU.

---

## 12. Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `'gbif_credenciais.bat' não é reconhecido…` | o terminal não está na pasta do pipeline (`cd` até ela), ou é o PowerShell (use `$env:GBIF_USER = "..."`, ver 3.2) |
| A etapa 1 pede usuário e senha | as variáveis do GBIF não foram carregadas nesta janela do terminal |
| `Problema no arquivo de entrada…` | o erro indica a linha: vírgula decimal, latitude e longitude trocadas, chave com nome errado. Rode `python config_pipeline.py` |
| `ERRO: Ollama não está acessível` | inicie o Ollama (`ollama serve`) e rode `python main.py --a-partir-de pubmed` |
| `modelo '…' não encontrado no Ollama` | `ollama pull llama3.1:8b` (ou o modelo do `[ollama]`) |
| `classificação(ões) falharam (timeout/JSON inválido)` | o Llama demorou demais; rode a etapa de novo ou aumente `timeout_segundos` |
| Buscas lentas ou `busca pendente` em muitas linhas | limite de requisições do NCBI; o pipeline espera e tenta de novo até 5 vezes. Use a chave do NCBI e rode a etapa de novo para completar |
| OpenAlex pulado (sem cota) | coloque `openalex_api_key`; a descoberta segue só com o PubMed |
| `[FALHOU]` na etapa 0 | sem internet ou servidor fora; rode `python main.py --somente downloads` mais tarde. Se persistir, faça o download manual (ver 7.0) |
| `403 Client Error: Forbidden` ao baixar a Flora e Funga do Brasil | o servidor do JBRJ recusa programas que não se identificam como navegador; o pipeline já se identifica como navegador. Se ainda assim falhar, baixe pelo navegador em https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil e salve como `dados_flora_brasil/flora_brasil_dwca.zip` |
| `CERTIFICATE_VERIFY_FAILED` / `unable to get local issuer certificate` | o Python não confia no certificado do servidor (o navegador completa a cadeia de certificados, o Python não). Rode `pip install truststore`: o pipeline passa a usar os certificados do sistema. Para o WFO, o pipeline também tenta o Zenodo antes do servidor antigo |
| A lista tem "plantas" estranhas (bactérias, palavras) | vêm da descoberta em artigos; estão marcadas como `não reconhecido` e não são usadas nas etapas 3 e 5 |
| Uma espécie de outro lugar entrou pelo gênero | não deveria: gêneros só trazem espécies já presentes em `plantas.csv`. Confira a coluna `fonte` |
| A etapa 5 está lenta demais | ver seção 11 |

---

## 13. Limitações e cuidados na interpretação

- **O Llama faz triagem, não revisão sistemática.** Ele pode errar,
  sobretudo em resumos ambíguos. Confirme os resultados importantes no
  artigo (coluna `link`).
- **Só resumos são lidos**, não o texto completo. O tipo de estudo e a
  parte da planta podem ficar como `não informado` se o resumo não disser.
- **Atividade do composto ≠ atividade da planta.** Para compostos muito
  estudados (ex.: quercetina), os artigos tratam do composto em geral. A
  coluna `atividades_relatadas_planta` é a que liga a atividade à espécie.
- **Ausência de evidência não é evidência de ausência.** "Nenhum artigo
  encontrado" pode significar só que a planta é pouco estudada.
- **Bases taxonômicas discordam.** A ordem de prioridade (Flora > WFO >
  GBIF) decide o nome aceito, mas todas as versões ficam em `nomes_busca`
  e as divergências em `observacoes_taxonomia`.
- **Descoberta em artigos é textual.** A citação de uma planta num artigo
  sobre a região não garante que ela ocorra lá; confira
  `n_ocorrencias_na_area`.
- **Registros do GBIF** incluem plantas cultivadas e possíveis erros de
  identificação.
- **Via InChIKey** depende dos vínculos do PubChem; muitos produtos
  naturais raros não têm nenhum (por isso existe a busca pelo nome).
- **Estereoisômeros e previsões por similaridade** do ChEMBL são
  indicativos, não equivalentes a dados do próprio composto.
- **Bases de compostos** registram o que foi publicado: a ausência de
  compostos não significa que a planta não os tenha.

---

## 14. Bases de dados e como citá-las

| Base | Uso no pipeline | Endereço |
|---|---|---|
| GBIF | ocorrências na região; taxonomia | https://www.gbif.org |
| Flora e Funga do Brasil (JBRJ) | conferência de nomes (lista oficial do Brasil) | https://floradobrasil.jbrj.gov.br · https://ipt.jbrj.gov.br/jbrj/resource?r=lista_especies_flora_brasil |
| World Flora Online | conferência de nomes (lista mundial) | https://www.worldfloraonline.org · lista completa no Zenodo: https://doi.org/10.5281/zenodo.20782718 (junho/2026) |
| COCONUT 2.0 | produtos naturais e organismos de origem | https://coconut.naturalproducts.net |
| Dr. Duke's Phytochemical and Ethnobotanical Databases (USDA) | parte da planta, teor e atividades por composto | https://phytochem.nal.usda.gov · dados: https://agdatacommons.nal.usda.gov/articles/dataset/Dr_Duke_s_Phytochemical_and_Ethnobotanical_Databases/24660351 |
| NPASS 3.0 | pares espécie–composto, atividades e alvos | https://bidd.group/NPASS |
| ChEMBL | atividades medidas em ensaios | https://www.ebi.ac.uk/chembl |
| PubChem | InChIKey, CID, nomes, artigos ligados a cada composto | https://pubchem.ncbi.nlm.nih.gov |
| PubMed | resumos de artigos | https://pubmed.ncbi.nlm.nih.gov |
| OpenAlex | artigos (descoberta de plantas) | https://openalex.org |
| Ollama / Llama 3.1 | julgamento dos resumos | https://ollama.com |

Ao publicar resultados:

- **GBIF**: cite o **DOI do download** usado. Ele aparece no site do GBIF,
  em *Downloads* da sua conta, e a chave fica em
  `dados_gbif_download/pedidos.json`.
- **Demais bases**: cite a publicação de referência indicada em cada site e
  a versão usada (para o COCONUT, ver `dados_bioativos/coconut_versao.txt`;
  para o ChEMBL, o nome do arquivo baixado).

---

## 15. Histórico de mudanças

### Versão 2 (atual)

| Antes (v1) | Agora (v2) |
|---|---|
| Região em `config.txt` (só retângulo) | `[regiao]` no `input.txt`: círculo, retângulo ou polígono, mais termos de texto para os artigos |
| Parâmetros espalhados, sem validação | Tudo num só `input.txt`, validado antes de rodar |
| GBIF trazia plantas, animais e fungos | Só plantas e só registros de presença |
| Sem lista do usuário | Sua lista + plantas da região + plantas citadas em artigos (PubMed e OpenAlex) |
| Nomes usados como estavam | Conferidos em Flora e Funga do Brasil, WFO e GBIF; corrigidos para o aceito, com original e divergências registrados |
| Busca por um nome só | Compostos e artigos buscados por todos os nomes da planta |
| COCONUT "lite" (sem organismo de origem) | COCONUT completo |
| InChIKey buscado no arquivo errado do NPASS | InChIKey do arquivo de estruturas, completado pelo PubChem |
| Downloads feitos no meio das etapas | Etapa 0 (`downloads`) separada, que pode ser pulada, com atualização segura |
| ChEMBL por nome | ChEMBL pelo InChIKey, com estereoisômeros e PMID de cada ensaio |
| PubMed sem julgamento | PubMed + Llama: só relação causal positiva, com tipo de estudo e parte da planta |
| PubMed só para plantas com compostos | Todas as plantas da lista (configurável) |
| Uma planilha final | Planilhas por planta, por composto e combinada, mais arquivos de evidência |

**Nota sobre o cache do Llama**: na última versão o prompt passou a pedir o
tipo de estudo e a parte da planta. As respostas **negativas** de rodadas
anteriores são reaproveitadas; só os artigos que já tinham dado positivo
são lidos de novo.

