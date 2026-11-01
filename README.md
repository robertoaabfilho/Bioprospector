# Pipeline de prospecção de plantas e compostos bioativos

> **Versão 3** · roda em Linux, Windows e macOS · Python 3.10+ · Llama local (Ollama)
>
> Você informa uma **região**, uma **lista de plantas** e as **atividades
> biológicas** que interessam. O pipeline devolve planilhas com as plantas, os
> compostos de cada uma e as atividades demonstradas em ensaios e artigos,
> cada resultado com a sua referência. Um comando à parte (`./graficos.sh`)
> transforma essas planilhas em **gráficos**, reunidos num relatório HTML.

---

## Sumário

**Parte I: Entender**
1. [Para que serve](#1-para-que-serve)
2. [Como funciona, em um minuto](#2-como-funciona-em-um-minuto)
3. [Cinco ideias que explicam todo o resto](#3-cinco-ideias-que-explicam-todo-o-resto)

**Parte II: Preparar**

4. [Instalação](#4-instalação)
5. [Estrutura de pastas](#5-estrutura-de-pastas)
6. [Credenciais e chaves](#6-credenciais-e-chaves)
7. [Configuração: o `input.txt`](#7-configuração-o-inputtxt)

**Parte III: Rodar**

8. [Primeira execução, passo a passo](#8-primeira-execução-passo-a-passo)
9. [Todos os comandos](#9-todos-os-comandos)
10. [Como acompanhar o andamento](#10-como-acompanhar-o-andamento)
11. [Pausar, retomar e recomeçar](#11-pausar-retomar-e-recomeçar)

**Parte IV: As etapas em detalhe**

12. [Etapa 0: `downloads`](#12-etapa-0-downloads)
13. [Etapa 1: `gbif`](#13-etapa-1-gbif)
14. [Etapa 2: `plantas`](#14-etapa-2-plantas)
15. [Etapa 3: `bioativos`](#15-etapa-3-bioativos)
16. [Etapa 4: `chembl`](#16-etapa-4-chembl)
17. [Etapa 5: `pubmed`](#17-etapa-5-pubmed)

**Parte V: Resultados**

18. [Qual arquivo abrir e como ler](#18-qual-arquivo-abrir-e-como-ler)
19. [Mensagens de status nas planilhas](#19-mensagens-de-status-nas-planilhas)
20. [Gráficos dos resultados](#20-gráficos-dos-resultados)

**Parte VI: Referência**

21. [Caches](#21-caches)
22. [Tempo de execução e escala](#22-tempo-de-execução-e-escala)
23. [Solução de problemas](#23-solução-de-problemas)
24. [Limitações e cuidados na interpretação](#24-limitações-e-cuidados-na-interpretação)
25. [Bases de dados e como citá-las](#25-bases-de-dados-e-como-citá-las)
26. [Histórico de mudanças](#26-histórico-de-mudanças)

---

# Parte I: Entender

## 1. Para que serve

O pipeline responde a esta pergunta:

> **Quais plantas de uma região (e da minha lista) têm compostos e
> atividades biológicas documentados, e quais são as evidências?**

### O que você informa

Tudo fica em `config/input.txt` e, se a lista for grande, em
`config/lista_de_plantas.txt`.

| Entrada | Exemplo | Obrigatória? |
|---|---|---|
| **Região**: coordenadas e palavras que a identificam em textos | polígono do Brasil; `brazilian, brasileir*, Brazil, Brasil` | sim |
| **Lista de plantas**: espécies e/ou gêneros | `Euterpe oleracea, Copaifera, Carapa guianensis` | sim (pode ser curta) |
| **Atividades de interesse**, em inglês | `clareadora = tyrosinase inhibit*, melanin*` | não (vazio = qualquer atividade) |

### O que você recebe

Planilhas CSV, que abrem no Excel, no LibreOffice ou no Google Planilhas:

- a **lista de plantas**: as que ocorrem na região, as da sua lista e as
  citadas em artigos sobre a região, com os **nomes conferidos** em três
  bases taxonômicas;
- os **compostos** conhecidos de cada planta, de cinco bases (COCONUT,
  NPASS, Dr. Duke, LOTUS e FooDB), com InChIKey, SMILES, classe química,
  parte da planta, teor e referências;
- as **atividades medidas em ensaios** de cada composto (ChEMBL), com o
  valor (IC50, Ki…) e o artigo de origem;
- as **atividades relatadas em artigos** (PubMed) para plantas e
  compostos. Um modelo de linguagem que roda no seu computador (Llama, via
  Ollama) lê cada resumo e mantém **só os que relatam um resultado
  experimental positivo**. Ele anota também o **tipo de estudo** (in vitro,
  in vivo, clínico) e a **parte da planta**;
- **arquivos de evidência**, com PMID, DOI e uma justificativa para cada
  resultado, para você conferir;
- **gráficos** de cada etapa (`./graficos.sh`), num relatório
  `graficos/relatorio.html` que abre no navegador (seção 20).

---

## 2. Como funciona, em um minuto

O pipeline tem **seis etapas**, que rodam em ordem. Cada etapa lê o arquivo
produzido pela anterior e grava o seu.

```
                       config/input.txt  (+ lista_de_plantas.txt)
                                │
 [0 downloads]  baixa as bases grandes, uma vez só ─────────► dados_*/
                                │
 ── FASE A: QUAIS PLANTAS? ────────────────────────────────────────────────
 [1 gbif]       plantas com registro na região (GBIF) ──────► especies_gbif.csv
                                │
 [2 plantas]    GBIF + sua lista + plantas citadas em artigos
                nomes conferidos (Flora do Brasil > WFO > GBIF) ► plantas.csv
                                │
 ── FASE B: QUAIS COMPOSTOS E ATIVIDADES? ─────────────────────────────────
 [3 bioativos]  compostos de cada planta
                (COCONUT, NPASS, Dr. Duke, LOTUS, FooDB) ───► especies_com_compostos_bioativos.csv
                                │
 [4 chembl]     atividades MEDIDAS em ensaios (ChEMBL) ─────► compostos_chembl.csv
                                │
 [5 pubmed]     atividades RELATADAS em artigos
                (PubMed + PubChem, julgadas pelo Llama) ────► atividades_plantas.csv
                                                              atividades_compostos.csv
                                                              especies_atividades.csv
                                                              evidencias_pubmed.csv
                                │
 [gráficos]     ./graficos.sh: lê as planilhas acima ────────► graficos/relatorio.html
                (opcional; roda a qualquer momento)
```

| # | Etapa | Pergunta que responde | Arquivo principal que produz |
|---|---|---|---|
| 0 | `downloads` | (prepara as bases locais) | `bases_baixadas.txt` |
| 1 | `gbif` | Que plantas têm registro de ocorrência na região? | `especies_gbif.csv` |
| 2 | `plantas` | Qual é a lista final de plantas, com os nomes corretos? | `plantas.csv` |
| 3 | `bioativos` | Que compostos já foram identificados nessas plantas? | `especies_com_compostos_bioativos.csv` |
| 4 | `chembl` | Que atividades desses compostos foram medidas em ensaios? | `compostos_chembl.csv` |
| 5 | `pubmed` | Que atividades os artigos demonstram para plantas e compostos? | `especies_atividades.csv` + 3 planilhas |

Os nomes das etapas (`downloads`, `gbif`, `plantas`, `bioativos`,
`chembl`, `pubmed`) são usados nos comandos (`--a-partir-de pubmed`,
`--somente chembl`).

---

## 3. Cinco ideias que explicam todo o resto

Entender estas cinco ideias responde à maioria das dúvidas sobre como rodar,
pausar e retomar.

**1. Cada etapa tem um "arquivo de saída principal".** É o da última coluna
da tabela acima. Ele só é gravado quando a etapa **termina com sucesso**, e é
o último arquivo que a etapa grava. Por isso, a existência dele significa
"etapa concluída". A opção `--retomar` usa exatamente isso.

**2. Toda consulta à internet fica guardada em um cache.** Cada busca no
PubMed, cada nome conferido, cada resumo lido pelo Llama é gravado num
arquivo `cache_*.jsonl` **no momento em que termina**. Rodar de novo
reaproveita tudo e só faz o que falta. Na prática:
- interromper **nunca** perde mais do que a consulta em andamento;
- **retomar = rodar o mesmo comando de novo**.

**3. A maior parte do tempo vai para a etapa `pubmed`.** As etapas 0 a 4
levam de minutos a poucas horas. A etapa 5 pode levar **dias**, porque o
Llama lê os resumos um a um. É nela que você vai usar o acompanhamento
(seção 10) e a retomada (seção 11).

**4. Plantas e compostos são identificados por nomes e por estrutura.**
- **Plantas**: cada nome é corrigido para o **nome aceito**. Todos os nomes
  conhecidos da planta (aceito, sinônimos, o que você escreveu) são usados
  nas buscas, e ficam na coluna `nomes_busca`.
- **Compostos**: são unificados pelo **InChIKey**, um código de 27
  caracteres derivado da estrutura química (ex.:
  `REFJWTPEDVJJIY-UHFFFAOYSA-N` = quercetina). O mesmo composto vindo de
  bases diferentes vira uma linha só.

**5. "Atividade" só conta se for demonstrada.** O Llama só aceita um artigo
se ele relata um **resultado experimental positivo**, como "o extrato inibiu
a tirosinase (IC50 = 12 µg/mL)". Não contam: menção, uso tradicional,
resultado nulo, revisão, especulação ou estudo só por computador
(*docking*).

---

# Parte II: Preparar

## 4. Instalação

### 4.1 O que é preciso

| Item | Para quê | Obrigatório? |
|---|---|---|
| **Python 3.10 ou mais recente** | rodar o pipeline | sim |
| **Ollama** + modelo `llama3.1:8b` | etapa 5 (leitura dos resumos) | sim, para a etapa 5 |
| **Conta gratuita no GBIF** | etapa 1 (download da região) | sim, na 1ª vez de cada região |
| Chave gratuita do **NCBI** | PubMed/PubChem cerca de 3× mais rápidos | recomendada |
| Chave gratuita do **OpenAlex** | descoberta de plantas em artigos | recomendada |
| **≈ 6 GB** livres em disco | bases baixadas | sim |
| Placa de vídeo (GPU) | Llama de 5 a 10× mais rápido | não, mas faz muita diferença |

### 4.2 Instalando, uma vez só

Descompacte o pacote, abra um terminal **na pasta do projeto** (a que
contém `config/` e `mods/`) e rode o instalador.

**Linux / macOS**

```bash
cd caminho/do/projeto
chmod +x instalar.sh rodar.sh     # só se o zip tiver perdido as permissões
./instalar.sh
```

**Windows** (Prompt de Comando)

```bat
cd caminho\do\projeto
instalar.bat
```

O instalador:
1. confere a versão do Python;
2. cria um **ambiente virtual** `.venv` dentro da pasta do projeto e
   instala nele os pacotes de `requirements.txt` (`requests`, `pandas`,
   `tqdm`, `truststore`). Nada é instalado no Python do sistema;
3. cria `config/input.txt` e `config/credenciais.txt` a partir dos modelos,
   **se ainda não existirem** (nunca sobrescreve os seus);
4. confere se o Ollama e o modelo do `input.txt` estão instalados.

O pacote de gráficos (`matplotlib`) não faz parte do `requirements.txt`: o
`./graficos.sh` (Windows: `graficos.bat`) o instala no `.venv` sozinho, na
primeira vez em que for usado (seção 20).

> **Linux (Ubuntu/Debian)**: se o instalador avisar que falta o módulo
> `venv`, rode `sudo apt install python3 python3-venv` e de novo
> `./instalar.sh`.

**Instalação manual**, se preferir:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python -m pip install -r requirements.txt
cp config/input.txt.exemplo config/input.txt            # Windows: copy config\input.txt.exemplo config\input.txt
```

### 4.3 Ollama e o modelo Llama

O Llama roda **no seu computador**: sem custo e sem enviar os resumos para
fora.

1. Instale o Ollama:
   - **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`. Ele vira um
     serviço do sistema, que inicia sozinho. Confira com
     `systemctl status ollama`; se estiver parado,
     `sudo systemctl start ollama`.
   - **Windows / macOS**: baixe em https://ollama.com/download. Ele fica na
     bandeja do sistema e inicia sozinho.
2. Baixe o modelo (≈ 5 GB): `ollama pull llama3.1:8b`
3. Se o Ollama não estiver rodando como serviço, deixe um terminal aberto
   com `ollama serve`.

| Modelo | Memória | Velocidade por resumo | Comentário |
|---|---|---|---|
| `llama3.1:8b` | ≈ 5 GB | 1–3 s com GPU; 5–30 s só com CPU | **recomendado** (padrão) |
| `llama3.2:3b` | ≈ 2–3 GB | cerca de 2× mais rápido | um pouco menos preciso |
| modelos de 1B | — | — | não use: erram muito no julgamento |

**GPU no Linux**: com placa NVIDIA e driver instalado (`nvidia-smi`
funciona), o Ollama usa a placa automaticamente. Durante a etapa 5, rode
`ollama ps`: a coluna `PROCESSOR` deve mostrar `GPU`.

### 4.4 Espaço em disco

| Base | Tamanho aproximado |
|---|---|
| Flora e Funga do Brasil | dezenas de MB |
| World Flora Online (WFO) | ≈ 700 MB |
| COCONUT (completo) + NPASS | ≈ 2 GB |
| Dr. Duke + LOTUS | ≈ 100 MB |
| FooDB (3 tabelas, depois de extraídas) | ≈ 1–2 GB, mais ≈ 1 GB temporário durante o download |
| Estruturas do ChEMBL | ≈ 300 MB |
| Caches e resultados | dezenas a centenas de MB |

Reserve **pelo menos 6 GB**.

---

## 5. Estrutura de pastas

```
pipeline/                       ← pasta do projeto: rode os comandos daqui
├── README.md                   ← este guia
├── instalar.sh  / instalar.bat ← instalação (Linux-macOS / Windows), uma vez
├── rodar.sh     / rodar.bat    ← lançadores do pipeline (Linux-macOS / Windows)
├── graficos.sh  / graficos.bat ← lançadores dos gráficos (seção 20)
├── graficos.py                 ← script dos gráficos (só lê as planilhas)
├── requirements.txt            ← pacotes Python
├── .venv/                      ← ambiente Python (criado pelo instalador)
│
├── config/                     ← O QUE VOCÊ EDITA
│   ├── input.txt               ← configuração da pesquisa
│   ├── lista_de_plantas.txt    ← sua lista (opcional; substitui [taxons])
│   ├── credenciais.txt         ← GBIF, NCBI, OpenAlex (NÃO compartilhe)
│   ├── input.txt.exemplo       ← modelo comentado
│   └── credenciais.txt.exemplo ← modelo
│
├── mods/                       ← os scripts (não precisa mexer)
│   ├── main.py                 ← orquestrador: roda as etapas em ordem
│   ├── baixar_bases.py         ← etapa 0
│   ├── buscar_especies_gbif.py ← etapa 1
│   ├── montar_lista_plantas.py ← etapa 2
│   ├── cruzar_especies_bioativos.py ← etapa 3
│   ├── consultar_chembl.py     ← etapa 4
│   ├── consultar_atividades_pubmed.py ← etapa 5
│   └── (módulos auxiliares, tabela abaixo)
│
└── criados ao rodar, na raiz:
    ├── dados_*/                ← bases baixadas (etapas 0 e 1)
    ├── cache_*.jsonl           ← memória das consultas (seção 21)
    ├── *.csv                   ← resultados
    ├── bases_baixadas.txt, diagnostico_pubmed.txt
    └── graficos/               ← criada pelo ./graficos.sh: relatorio.html,
                                   imagens e dados/ (tabela de cada gráfico)
```

**Módulos auxiliares** (usados pelas etapas, não rodam sozinhos):

| Arquivo | Função |
|---|---|
| `config_pipeline.py` | lê e valida o `input.txt` (`./rodar.sh config` mostra o resultado) |
| `credenciais.py` | lê `config/credenciais.txt`; pergunta e abre o arquivo se faltar o login do GBIF |
| `taxonomia.py` | conferência de nomes (Flora e Funga do Brasil, WFO, GBIF) |
| `descoberta_artigos.py` | descoberta de plantas citadas em artigos (PubMed, OpenAlex) |
| `literatura.py` | acesso ao PubMed, PubChem e OpenAlex; caches |
| `duke.py`, `lotus.py`, `foodb.py` | leitura do Dr. Duke, do LOTUS e do FooDB |
| `diagnostico_pubmed.py` | resumo do andamento da etapa 5 (`./rodar.sh diagnostico`) |

---

## 6. Credenciais e chaves

Todas as credenciais ficam num **único arquivo**, igual em Windows, Linux e
macOS: **`config/credenciais.txt`**.

```ini
GBIF_USER = seu_usuario
GBIF_PWD = sua_senha
GBIF_EMAIL = seu@email
NCBI_API_KEY = sua_chave_ncbi          # opcional
OPENALEX_API_KEY = sua_chave_openalex  # opcional
```

Uma credencial por linha, no formato `CHAVE = valor`, sem aspas. Linhas
começadas com `#` são comentários.

| Credencial | Onde obter | Quando é usada |
|---|---|---|
| `GBIF_USER`, `GBIF_PWD`, `GBIF_EMAIL` | https://www.gbif.org → *Login* → *Register* | só num **download novo** do GBIF (1ª vez ou região nova) |
| `NCBI_API_KEY` | https://www.ncbi.nlm.nih.gov/account/ → *Account settings* → *API Key* | etapas 2 e 5 (PubMed, PubChem): ≈ 3× mais rápidas |
| `OPENALEX_API_KEY` | conta gratuita em https://openalex.org | etapa 2 (sem ela, a cota diária é mínima e o OpenAlex pode ser pulado) |

**Se você não preencher, o pipeline ajuda na hora certa**:

1. No início de cada rodada, ele mostra o **sistema operacional** detectado
   e a situação das credenciais, com os valores mascarados.
2. Quando o GBIF realmente precisa de login, ele **pergunta**: *"Você já
   configurou as credenciais do GBIF? [s/n]"*.
3. Respondendo **n**, ele cria o `credenciais.txt` e **abre o arquivo no
   editor do sistema**: Bloco de Notas (Windows), editor de texto (macOS),
   editor gráfico (Linux com interface) ou `nano` (terminal/SSH). Preencha,
   salve, e o pipeline continua.
4. Rodando sem terminal (`nohup`, agendamento), ele não pode perguntar: cria
   o arquivo, para e avisa onde preencher.

Outros detalhes:
- **Conferir a qualquer momento**: `./rodar.sh credenciais`
  (Windows: `rodar.bat credenciais`).
- **Prioridade**: variáveis de ambiente já definidas (`GBIF_USER` etc.) >
  `config/credenciais.txt` > arquivos antigos `gbif_credenciais.env/.bat`
  (ainda lidos).
- As chaves do NCBI e do OpenAlex também podem ficar no `input.txt`
  (`[pubmed] ncbi_api_key`, `[artigos] openalex_api_key`). Lá elas têm
  prioridade, mas é melhor deixá-las no `credenciais.txt`, para não
  expô-las ao compartilhar o `input.txt`.
- No Linux e no macOS, o arquivo é criado com permissão só para você
  (`chmod 600`).

> ⚠️ **Não compartilhe** o `credenciais.txt`: as senhas ficam em texto puro.
> Ele nunca faz parte do pacote do pipeline. Antes de enviar a pasta do
> projeto a alguém, apague-o.

---

## 7. Configuração: o `input.txt`

O arquivo `config/input.txt` é dividido em **seções** entre colchetes. As
três primeiras definem a pesquisa; as outras são parâmetros técnicos, todos
opcionais.

```ini
[regiao]          ← onde procurar                (obrigatória)
[taxons]          ← sua lista de plantas         (ou lista_de_plantas.txt)
[termos_pubmed]   ← atividades de interesse      (opcional)
[artigos] [taxonomia] [ollama] [pubmed] [bioativos] [chembl]  ← parâmetros
```

**Regras gerais**
- Linhas começadas com `#` são comentários.
- Use **ponto** como separador decimal (`-3.35`) e **vírgula** entre
  latitude e longitude (`-3.35, -64.71`).
- Uma chave apagada vale o padrão. Uma chave **repetida** na mesma seção é
  erro: a mensagem mostra as duas linhas.
- O arquivo é **validado antes de qualquer etapa**. Erros (vírgula decimal,
  latitude e longitude trocadas, chave com nome errado, valor inválido)
  aparecem com o número da linha.
- Arquivos salvos no Bloco de Notas (ANSI) ou com quebras de linha do
  Windows são lidos normalmente em qualquer sistema.
- **Para ver como o arquivo foi entendido**, sem rodar nada:
  `./rodar.sh config` (Windows: `rodar.bat config`).

### 7.1 `[regiao]`: onde procurar

A região é usada de **duas formas**, por isso as duas ficam juntas:

**a) Coordenadas, para o GBIF (etapa 1).** Um ponto por linha, no formato
`latitude, longitude`:

| Nº de pontos | Forma da região |
|---|---|
| 1 | círculo com centro no ponto e raio `raio_km` (padrão 10 km) |
| 2 | retângulo (dois cantos opostos, em qualquer ordem) |
| 3 ou mais | polígono (vértices na ordem do contorno, sem repetir o primeiro). A orientação exigida pelo GBIF é corrigida automaticamente |

Latitude negativa = hemisfério sul; longitude negativa = oeste.

**b) `termos_texto`, para o PubMed e o OpenAlex (etapa 2).** Essas bases
não entendem coordenadas, só palavras no título e no resumo. O `*` é
truncamento: `brasileir*` cobre *brasileiro*, *brasileira*, *brasileiros*.
Maiúsculas e acentos não fazem diferença.

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

> Mudou a região? Ajuste **as coordenadas e os termos**. Exemplos: Brasil
> inteiro → `brazilian, brasileir*, Brazil, Brasil`; Pará → `Pará, Belém,
> amazon*`.

### 7.2 Sua lista de plantas: `lista_de_plantas.txt` ou `[taxons]`

| Onde | Quando usar |
|---|---|
| **`config/lista_de_plantas.txt`** (mesma pasta do `input.txt`) | listas grandes (centenas a dezenas de milhares de nomes) |
| seção `[taxons]` do `input.txt` | listas curtas |

- Se o `lista_de_plantas.txt` existir e tiver nomes, ele **substitui** a
  seção `[taxons]` (a tela avisa). Para voltar à seção, apague ou renomeie
  o arquivo.
- No arquivo, os nomes podem ser separados por vírgula, ponto e vírgula ou
  um por linha. Na seção, por vírgula, em quantas linhas quiser.
- **Espécies** e **infraespecíficos** (`var.`, `subsp.`) são aceitos.
- **Gêneros** (`Copaifera`, `Acmella sp.`): na etapa 3, trazem os registros
  feitos só no nível de gênero e as espécies do gênero **que já estão na
  lista final** (vindas do GBIF da região ou dos artigos), nunca espécies de
  outras regiões. Na etapa 5, um gênero sozinho não é pesquisado.
- Repetições são removidas.
- Todos os nomes passam pela **conferência taxonômica** da etapa 2. O nome
  que você escreveu fica registrado e continua sendo usado nas buscas.

### 7.3 `[termos_pubmed]`: atividades de interesse (opcional)

**Vazia** = o pipeline procura **qualquer** atividade biológica.
**Preenchida** = a etapa 5 só busca e só aceita as atividades listadas, e
a etapa 4 só liga ensaios a elas. Na etapa 2 elas não filtram nada: só
anotam quais plantas aparecem em artigos sobre cada atividade.

Dois formatos, que podem ser misturados:

| Linha | Efeito |
|---|---|
| `rótulo = termo1, termo2, ...` | uma atividade com sinônimos. O **rótulo** (pode ser em português) é o que aparece nos resultados |
| `termo1, termo2` | cada termo vira uma atividade separada |

```ini
[termos_pubmed]
clareadora = tyrosinase inhibit*, melanin*, melanogenesis, skin whitening
antirrugas = collagenase, elastase, wrinkle*, "skin aging"
fotoproteção = UVB, UVA, photoprotect*, "sun protection factor"
antibacteriana = antibacterial, antimicrobial, "Anti-Bacterial Agents"[mh]
```

- Escreva os termos **em inglês**: eles vão para o PubMed.
- Aceita truncamento (`melanin*`) e tags do PubMed
  (`"Anti-Bacterial Agents"[mh]` = descritor MeSH).
- Cada atividade gera uma busca própria por planta e por composto, para que
  uma atividade muito estudada não tome a vaga das outras.
- **Custo**: com várias atividades, uma busca combinada (pré-checagem)
  descarta antes as plantas sem nenhum artigo; as demais recebem uma busca
  por atividade (seção 17).

### 7.4 Parâmetros técnicos

Todos são opcionais. A coluna "Padrão" é o valor usado quando a chave não
aparece.

**`[artigos]`: descoberta de plantas em artigos (etapa 2)**

| Chave | Padrão | Função |
|---|---|---|
| `ativar` | `true` | liga ou desliga a descoberta |
| `usar_pubmed` | `true` | busca no PubMed |
| `usar_openalex` | `true` | busca no OpenAlex (substituto aberto do Google Scholar, com SciELO e revistas brasileiras) |
| `max_artigos` | `10000` | artigos lidos em **cada** base (0 = todos). Acima de 10 mil, a busca no PubMed é dividida por ano automaticamente |
| `contexto_vegetal` | `false` | `true` = exige também uma palavra de contexto vegetal (*plant, extract, leaves, bark…*): menos artigos fora do tema, mas pode perder alguns |
| `openalex_api_key` | vazio | chave do OpenAlex (prefira o `credenciais.txt`) |
| `email` | vazio | e-mail de contato para o OpenAlex |

**`[taxonomia]`: conferência dos nomes (etapa 2)**

| Chave | Padrão | Função |
|---|---|---|
| `usar_flora_brasil` | `true` | Flora e Funga do Brasil (prioridade 1) |
| `usar_wfo` | `true` | World Flora Online (prioridade 2) |
| `usar_gbif` | `true` | GBIF (prioridade 3; também fornece filo, classe e ordem) |
| `corrigir_grafia` | `true` | corrige erros leves de grafia quando há um nome muito parecido no mesmo gênero |
| `flora_brasil_url`, `wfo_url` | vazio | endereço alternativo de download (vazio = automático) |

**`[bioativos]`: compostos (etapa 3)**

| Chave | Padrão | Função |
|---|---|---|
| `apenas_com_atividade_npass` | `false` | `true` = só compostos com algum registro de atividade no NPASS |
| `incluir_nao_reconhecidos` | `false` | busca também nomes que nenhuma base taxonômica reconheceu |
| `usar_duke` | `true` | Dr. Duke: parte da planta, teor (ppm) e atividades por composto |
| `usar_lotus` | `true` | LOTUS: referência (DOI) de cada par planta × composto |
| `usar_foodb` | `true` | FooDB: alimento e teor. ⚠️ **Uso comercial exige permissão dos autores** (https://foodb.ca) |
| `coconut_url`, `duke_url`, `lotus_url`, `foodb_url` | vazio | endereço alternativo de download (vazio = automático) |

**`[chembl]`: ensaios (etapa 4)**

| Chave | Padrão | Função |
|---|---|---|
| `ativar` | `true` | liga ou desliga a etapa 4 |
| `pchembl_minimo` | `5` | potência mínima para contar como ativo (5 = até 10 µM; 6 = até 1 µM) |
| `estereoisomeros` | `true` | sem o InChIKey exato, usa moléculas com a mesma conectividade |
| `prever_por_similaridade` | `false` | para compostos sem dados, mostra atividades de moléculas parecidas (**hipótese**, não evidência; lento) |
| `similaridade_minima` | `85` | similaridade mínima, em % (70 a 100) |
| `estruturas_url` | vazio | endereço alternativo do arquivo de estruturas |

**`[pubmed]`: busca de atividades (etapa 5)**

| Chave | Padrão | Função |
|---|---|---|
| `plantas_pesquisadas` | `todas` | `todas` = todas as espécies de `plantas.csv`; `com_compostos` = só as que têm compostos (mais rápido) |
| `max_plantas` | `0` | teto de plantas (0 = sem teto). Prioriza as com compostos e depois as com mais ocorrências na área |
| `incluir_nao_reconhecidos` | `false` | pesquisa também nomes não reconhecidos |
| `max_artigos_por_planta` | `20` | resumos mais relevantes por planta, **por atividade** |
| `max_artigos_por_composto` | `10` | resumos por composto, por atividade |
| `max_compostos` | `0` | teto de compostos (0 = todos). Prioriza os com atividade no NPASS e os presentes em mais plantas |
| `busca_composto_por_nome` | `complemento` | `complemento` = busca pelo nome só se o InChIKey não trouxer artigos; `sempre`; `nunca` |
| `excluir_revisoes` | `true` | ignora artigos de revisão |
| `ncbi_api_key` | vazio | chave do NCBI (prefira o `credenciais.txt`) |
| `email` | vazio | e-mail de contato para o NCBI (vazio = usa `GBIF_EMAIL`) |

**`[ollama]`: modelo de linguagem (etapa 5)**

| Chave | Padrão | Função |
|---|---|---|
| `modelo` | `llama3.1:8b` | modelo que julga os resumos |
| `url` | `http://localhost:11434` | endereço do Ollama |
| `timeout_segundos` | `180` | tempo máximo por resumo |

Chaves de versões antigas (`max_artigos_por_atividade`, `termos_regiao`,
`incluir_plantas_listadas`, `filtro_ocorrencia`, `estados`, `dominios`) são
aceitas e ignoradas, com aviso. O nome antigo de seção `[coordenadas]`
continua valendo para `[regiao]`.

---

# Parte III: Rodar

## 8. Primeira execução, passo a passo

Nos exemplos, `./rodar.sh` é para Linux/macOS e `rodar.bat` para Windows.
Os dois aceitam exatamente as mesmas opções.

| Passo | Linux / macOS | Windows | O que acontece |
|---|---|---|---|
| 1. Instalar | `./instalar.sh` | `instalar.bat` | cria o `.venv` e os arquivos de configuração (seção 4) |
| 2. Credenciais (opcional) | `nano config/credenciais.txt` | `notepad config\credenciais.txt` | ou deixe o pipeline perguntar (seção 6) |
| 3. Configurar | `nano config/input.txt` | `notepad config\input.txt` | região, lista e atividades (seção 7) |
| 4. Conferir | `./rodar.sh config` | `rodar.bat config` | mostra como o `input.txt` foi entendido |
| 5. Baixar as bases (opcional) | `./rodar.sh --somente downloads` | `rodar.bat --somente downloads` | 15–40 min, uma vez só |
| 6. Rodar | `./rodar.sh` | `rodar.bat` | todas as etapas, em ordem |

> 💡 **Faça um teste pequeno primeiro.** Em `[pubmed]`, coloque
> `max_plantas = 300` e `max_compostos = 200`. Em poucas horas você vê os
> resultados e confere se a configuração está como queria. Depois volte os
> dois para `0` e rode `./rodar.sh --a-partir-de pubmed --pular-downloads`.
> Nada do que foi feito no teste é refeito.

> 💡 **Execução longa no Linux (servidor, SSH)?** Use o `tmux` ou o `nohup`
> (seção 10.4). Sem eles, fechar o terminal interrompe o pipeline.

---

## 9. Todos os comandos

### 9.1 Opções do pipeline

| Comando | Efeito |
|---|---|
| `./rodar.sh` | todas as etapas, com `config/input.txt` |
| `./rodar.sh --a-partir-de ETAPA` | começa na etapa indicada e segue até o fim |
| `./rodar.sh --somente ETAPA` | roda só a etapa indicada |
| `./rodar.sh --retomar` | pula as etapas cujo arquivo de saída principal já existe |
| `./rodar.sh --pular-downloads` | não roda a etapa 0 (bases já baixadas) |
| `./rodar.sh --atualizar-bases` | procura versões novas das bases e baixa de novo, com segurança (seção 12) |
| `./rodar.sh --sem-gbif` | não usa o GBIF: a lista fica só com a sua lista e as plantas dos artigos |
| `./rodar.sh --input outro.txt` | usa outro arquivo de configuração. O caminho pode ser relativo à pasta onde você está, à raiz do projeto ou a `config/`. A `lista_de_plantas.txt` é procurada na mesma pasta desse arquivo |

`ETAPA` é um destes: `downloads`, `gbif`, `plantas`, `bioativos`, `chembl`,
`pubmed`.

As opções se combinam. Exemplo: `./rodar.sh --a-partir-de bioativos
--pular-downloads`.

### 9.2 Comandos auxiliares

| Comando | Efeito |
|---|---|
| `./rodar.sh config` | mostra como o `input.txt` foi entendido; não roda nada |
| `./rodar.sh credenciais` | mostra o sistema e a situação das credenciais; se faltar o login do GBIF, pergunta e abre o arquivo |
| `./rodar.sh diagnostico` | resumo do andamento da etapa 5 → `diagnostico_pubmed.txt` (seção 10.3) |
| `./rodar.sh parcial` | planilhas da etapa 5 com o que o Llama já leu → arquivos `*_parcial.csv` (seção 10.3) |
| `./graficos.sh` | gráficos de todas as etapas já concluídas → `graficos/relatorio.html` (seção 20) |
| `./graficos.sh --parcial` | idem, com a etapa 5 lida dos `*_parcial.csv` |

### 9.3 Sem os lançadores

Os lançadores só entram na pasta do projeto, escolhem o Python do `.venv` e
ativam a saída imediata das mensagens. Se preferir chamar o Python direto,
as opções são as mesmas:

```bash
.venv/bin/python mods/main.py --a-partir-de pubmed        # Linux/macOS
.venv\Scripts\python mods\main.py --a-partir-de pubmed    # Windows
```

Cada etapa também roda sozinha (`.venv/bin/python mods/consultar_chembl.py`),
mas pelo `main.py` o `input.txt` é validado antes e o tempo de cada etapa é
mostrado.

---

## 10. Como acompanhar o andamento

### 10.1 O que aparece na tela

No início, o pipeline mostra o que entendeu da configuração. Depois, cada
etapa abre com um cabeçalho e termina com o seu tempo:

```
Sistema: Linux
Credenciais: GBIF ok (usuário rob***); NCBI ok; OpenAlex ok (de config/credenciais.txt)
Entrada: /home/voce/pipeline/config/input.txt
  Região: polígono com 69 vértices
  Táxons do usuário (33967, de lista_de_plantas.txt): ...
======================================================================
ETAPA [pubmed]: Atividades relatadas no PubMed, filtradas pelo Llama
======================================================================
PubChem: consultando 1520 composto(s) (48210 já em cache)...
PubChem (em lote): 100%|██████████| 8/8 [00:21<00:00,  2.6s/it]
Pré-checagem: 2900 planta(s)/composto(s) - uma busca com todas as 7 atividades juntas ...
PubMed esearch:  45%|████▌     | 1302/2890 [09:41<11:48,  2.2it/s]
...
Llama (llama3.1:8b): 19104 par(es) entidade x artigo a classificar (2015 em cache)
Classificando:  11%|█         | 2015/19104 [6:20:24<61:33:19, 12.97s/it]
```

**Como ler uma barra de progresso**:
`2015/19104 [6:20:24<61:33:19, 12.97s/it]` = 2.015 de 19.104 itens feitos;
6 h 20 min decorridas; **cerca de 61 h e meia restantes**; 12,97 segundos
por item. A estimativa se ajusta ao longo da rodada.

**"(N já em cache)"**: quanto do trabalho veio de rodadas anteriores. Numa
retomada, esse número deve ser alto.

No fim de cada rodada, um **resumo** mostra cada etapa, o arquivo gerado, o
número de linhas e o tempo:

```
RESUMO
  [downloads] não executada nesta rodada
  [gbif     ] especies_gbif.csv (48211 linhas) [12s]
  [plantas  ] plantas.csv (51032 linhas) [3m10s]
  ...
Tempo total: 2h14m05s
```

### 10.2 Etapa a etapa: o que observar

| Etapa | Mensagens úteis para acompanhar |
|---|---|
| `downloads` | uma linha por base; no final, a tabela `[OK]` / `[FALHOU]` com o tamanho de cada arquivo |
| `gbif` | chave do pedido e o link `gbif.org/occurrence/download/...` (dá para acompanhar no site); `status: PREPARING / RUNNING / SUCCEEDED` a cada 30 s |
| `plantas` | número de artigos encontrados por base; barra de conferência dos nomes; contagem por fonte e por situação do nome |
| `bioativos` | quantos táxons e pares planta × composto vieram de cada base |
| `chembl` | quantos compostos foram achados (exatos e estereoisômeros) e quantos têm atividade |
| `pubmed` | barras do PubChem, das buscas, do download de resumos e, a mais longa, **Classificando** (Llama) |

### 10.3 Acompanhando a etapa 5 sem interromper

A leitura pelo Llama pode levar dias. Duas ferramentas mostram o andamento
**sem atrapalhar a rodada principal**. Abra **outro terminal**, na mesma
pasta:

**`./rodar.sh parcial`** (Windows: `rodar.bat parcial`): gera as planilhas
com o que o Llama **já leu**.
- Não acessa a internet e não lê nenhum artigo novo: usa só os caches.
- Grava em arquivos separados, para não confundir com o resultado final:
  `atividades_plantas_parcial.csv`, `atividades_compostos_parcial.csv`,
  `especies_atividades_parcial.csv`, `evidencias_pubmed_parcial.csv`.
- O que ainda não foi lido aparece como `artigos encontrados; leitura pelo
  Llama pendente`.
- Pode rodar quantas vezes quiser. Os `*_parcial.csv` podem ser apagados
  quando a rodada principal terminar.
- **Para ver em gráficos**: depois do `parcial`, rode
  `./graficos.sh --parcial` (seção 20). O gráfico *Julgamentos do Llama*
  mostra quantos resumos já foram lidos e quantos deram positivo.

**`./rodar.sh diagnostico`**: grava `diagnostico_pubmed.txt` (alguns KB),
um resumo dos caches: quantas buscas foram feitas e quantas vieram vazias,
quantos resumos foram baixados, quantos pares o Llama já julgou e quantos
deram positivo. É o arquivo a mandar para alguém analisar o andamento, no
lugar dos caches, que podem ter centenas de MB.

**Contagens rápidas** (cada linha de um cache = uma consulta concluída):

```bash
wc -l cache_llm_classificacao.jsonl      # resumos já julgados pelo Llama
wc -l cache_pubmed_buscas.jsonl          # buscas no PubMed já feitas
```
No Windows (PowerShell): `(Get-Content cache_llm_classificacao.jsonl).Count`

**O Llama está usando a GPU?** `ollama ps` → a coluna `PROCESSOR` deve
mostrar `GPU`.

### 10.4 Execuções longas: deixar rodando e ver depois

**Linux/macOS com `tmux`** (recomendado em servidores e via SSH):

```bash
tmux new -s pipeline                       # abre uma sessão
./rodar.sh --pular-downloads
# Ctrl+B e depois D: sai da sessão SEM parar o pipeline (pode fechar o terminal)
tmux attach -t pipeline                    # volta para ver o andamento
```

**Linux/macOS com `nohup`** (registro em arquivo):

```bash
nohup ./rodar.sh --pular-downloads > execucao.log 2>&1 &
tail -f execucao.log                       # acompanha; Ctrl+C só para de acompanhar
```

> Com `nohup` não há terminal para perguntas: preencha o
> `config/credenciais.txt` antes, se a etapa `gbif` precisar de um
> download novo.

**Windows**: deixe a janela do Prompt aberta. Para gravar um registro:

```bat
rodar.bat --pular-downloads > execucao.log 2>&1
```
e acompanhe em outra janela do PowerShell com
`Get-Content execucao.log -Wait -Tail 20`.

**Impeça o computador de dormir** durante rodadas longas:
- Linux: `systemd-inhibit --what=sleep:idle ./rodar.sh --pular-downloads`
- macOS: `caffeinate -i ./rodar.sh --pular-downloads`
- Windows: *Configurações → Sistema → Energia → Suspensão: Nunca* (durante
  a rodada).

---

## 11. Pausar, retomar e recomeçar

### 11.1 Pausar

**Para pausar, interrompa: `Ctrl+C`.** É seguro em qualquer momento,
inclusive no meio de uma etapa longa (no Windows, se aparecer *"Deseja
finalizar o arquivo em lotes (S/N)?"*, responda `S`).

O que se perde: **no máximo a consulta em andamento**, porque cada consulta
concluída já está no cache. Além disso:
- downloads interrompidos ficam como `*.parcial` e são refeitos;
- extrações de arquivos `.zip` interrompidas não deixam pastas incompletas
  (a pasta só ganha o nome final quando termina);
- as planilhas são gravadas de uma vez, no fim de cada etapa, e o arquivo
  de saída principal é o último a ser gravado. Uma etapa interrompida nunca
  parece "concluída".

Se o computador desligar ou a internet cair, o efeito é o mesmo de um
`Ctrl+C`.

### 11.2 Retomar

**Rode o mesmo comando de novo.** O pipeline refaz rapidamente o que já está
em cache e continua de onde parou.

Para não esperar as etapas que já terminaram, diga onde começar:

| Situação | Comando |
|---|---|
| Parou na etapa 5 (o caso mais comum) | `./rodar.sh --a-partir-de pubmed --pular-downloads` |
| Parou numa etapa qualquer | `./rodar.sh --a-partir-de ETAPA --pular-downloads` |
| Não sei onde parou | `./rodar.sh --retomar --pular-downloads` |
| Uma etapa falhou com erro | o próprio erro mostra o comando: `Corrija e retome com: ./rodar.sh --a-partir-de ETAPA` |

**`--a-partir-de` ou `--retomar`?**

- `--a-partir-de ETAPA` roda a etapa indicada e **todas as seguintes**,
  sempre. É a escolha certa depois de **mudar o `input.txt`**.
- `--retomar` pula toda etapa cujo arquivo de saída principal já existe e
  roda as demais. Só verifica se o arquivo existe: **não use `--retomar`
  depois de mudar o `input.txt`**, porque ele pularia etapas que precisam
  ser refeitas.

### 11.3 Rodar uma etapa só

```bash
./rodar.sh --somente chembl
```

Útil para refazer uma etapa sem refazer as seguintes. Lembre que as etapas
seguintes **não** se atualizam sozinhas: se a saída mudar, rode depois
`--a-partir-de` a etapa seguinte.

### 11.4 Mudei o `input.txt`: o que rodar?

Sempre com `--a-partir-de` e, se as bases já estiverem baixadas,
`--pular-downloads`. Os caches garantem que só o que mudou seja refeito.

| O que mudou | Rode a partir de | O que é refeito de verdade |
|---|---|---|
| coordenadas de `[regiao]` | `gbif` | um download novo no GBIF (precisa de login) e tudo o que depende das plantas novas |
| `termos_texto`, `[artigos]` | `plantas` | a descoberta em artigos com os termos novos |
| sua lista (`lista_de_plantas.txt` ou `[taxons]`), `[taxonomia]` | `plantas` | só os nomes novos são conferidos |
| `[termos_pubmed]` | `plantas` | anotação das atividades nos artigos (etapa 2), ligação dos ensaios (etapa 4) e buscas por atividade (etapa 5) |
| `[bioativos]` | `bioativos` | o cruzamento com as bases (minutos) |
| `[chembl]` | `chembl` | só o que a opção afeta |
| `[pubmed]` | `pubmed` | só as buscas novas (mudar `max_artigos_por_*` refaz as buscas, porque o limite faz parte da consulta) |
| `[ollama] modelo` | `pubmed` | **todos os julgamentos do Llama**: o modelo faz parte da chave do cache (demorado) |

### 11.5 Refazer só uma parte, apagando um cache

Às vezes você quer forçar uma consulta nova: buscar artigos publicados
depois da última rodada, reconferir nomes. Para isso, apague o cache
correspondente (tabela completa na seção 21) e rode a etapa de novo.

| Quero… | Apague | E rode |
|---|---|---|
| buscar artigos publicados desde a última rodada | `cache_pubmed_buscas.jsonl`, `cache_pubchem_vinculos.jsonl`, `cache_pubmed_filtro.jsonl` | `--a-partir-de pubmed` |
| refazer a descoberta de plantas em artigos | `cache_openalex.jsonl` e `cache_pubmed_buscas.jsonl` | `--a-partir-de plantas` |
| reconferir todos os nomes | `cache_taxonomia_*.jsonl` | `--a-partir-de plantas` |
| fazer o Llama reler todos os resumos | `cache_llm_classificacao.jsonl` ⚠️ | `--a-partir-de pubmed` |
| atualizar os dados do ChEMBL | `cache_chembl_*.jsonl` (ou use `--atualizar-bases`) | `--a-partir-de chembl` |
| um download novo do GBIF para a mesma região | `dados_gbif_download/pedidos.json` | `--a-partir-de gbif` |

> ⚠️ **`cache_llm_classificacao.jsonl` guarda dias de trabalho do Llama.**
> Em vez de apagá-lo, **mova-o** para uma pasta de reserva: se mudar de
> ideia, é só trazê-lo de volta.

### 11.6 Recomeçar do zero

Há três níveis. Em todos, **suas configurações em `config/` são mantidas**.

**Nível 1: refazer as planilhas, aproveitando todas as consultas.** Apaga
só os resultados; a próxima rodada os recria a partir dos caches (rápido,
exceto o que nunca foi consultado).

```bash
rm -f *.csv                      # Linux/macOS (Windows: del *.csv)
./rodar.sh --pular-downloads     # Windows: rodar.bat --pular-downloads
```

**Nível 2: refazer todas as consultas, mantendo as bases baixadas.** Uma
pesquisa realmente nova, sem reaproveitar nada da internet nem do Llama.

```bash
mkdir reserva && mv cache_*.jsonl *.csv reserva/     # Linux/macOS
./rodar.sh --pular-downloads
```
```bat
mkdir reserva
move cache_*.jsonl reserva
move *.csv reserva
rodar.bat --pular-downloads
```

**Nível 3: tudo do zero, inclusive as bases e o GBIF.**

```bash
rm -rf dados_* cache_*.jsonl *.csv bases_baixadas.txt diagnostico_pubmed.txt     # Linux/macOS
./rodar.sh
```
No Windows: apague as pastas `dados_*` pelo Explorador de Arquivos e depois
`del cache_*.jsonl *.csv bases_baixadas.txt`.

Isso baixa de novo cerca de 5 GB e faz um pedido novo ao GBIF (precisa de
login). Para só **atualizar** as bases, prefira `--atualizar-bases`, que é
seguro: se um download novo falhar, a versão anterior volta.

### 11.7 Levar a rodada para outro computador ou sistema

Copie a pasta do projeto inteira: `config/`, `dados_*/`, os `cache_*.jsonl`
e os `.csv`. Tudo é compatível entre Windows, Linux e macOS, e o pipeline
continua de onde parou. No computador novo:

1. **não copie o `.venv`** (ele não serve de um sistema para outro): rode o
   instalador;
2. o `config/credenciais.txt` é o mesmo em todos os sistemas;
3. instale o Ollama e o modelo.

---

# Parte IV: As etapas em detalhe

Cada etapa é descrita no mesmo formato: **objetivo**, **entradas**, **como
funciona**, **saídas** e **retomada**.

## 12. Etapa 0: `downloads`

`mods/baixar_bases.py` → `bases_baixadas.txt`

**Objetivo**: baixar uma vez as bases usadas como arquivos inteiros.

**Entradas**

| Tipo | O quê |
|---|---|
| Configuração | `[taxonomia] flora_brasil_url, wfo_url`; `[bioativos] coconut_url, usar_duke/lotus/foodb, *_url`; `[chembl] ativar, estruturas_url` |
| Internet | servidores das bases abaixo |

**Como funciona**

| Base | Usada na etapa | Onde fica |
|---|---|---|
| Flora e Funga do Brasil (IPT/JBRJ) | 2 | `dados_flora_brasil/flora_brasil_dwca.zip` |
| World Flora Online (*WFO Plant List*, Zenodo; versão mais recente) | 2 | `dados_wfo/WFO_Backbone.zip` |
| COCONUT (CSV completo, com organismos) | 3 | `dados_bioativos/coconut_csv.zip`, `coconut_extraido/`, `coconut_versao.txt` |
| NPASS 3.0 (6 arquivos) | 3 | `dados_bioativos/npass_*.txt` |
| Dr. Duke (USDA) | 3 | `dados_bioativos/duke_csv.zip`, `duke_extraido/` |
| LOTUS (export "frozen", Zenodo; ≈ 20 MB) | 3 | `dados_bioativos/lotus_frozen.csv.gz` |
| FooDB (≈ 950 MB baixados; só 3 tabelas guardadas) | 3 | `dados_bioativos/foodb/` |
| ChEMBL: estruturas (`chemreps.txt.gz`) | 4 | `dados_chembl/chembl_chemreps.txt.gz` |

- **Primeira vez**: baixa tudo (15–40 min). **Depois**: só confere e
  termina em segundos.
- **Bases opcionais** (ChEMBL, Dr. Duke, LOTUS, FooDB): se falharem, a
  etapa termina mesmo assim, com aviso. Sem o arquivo do ChEMBL, a etapa 4
  usa a API (mais lenta). Sem as outras, a etapa 3 segue sem elas.
- **Bases essenciais** (Flora, WFO, COCONUT, NPASS): se falharem, a etapa
  para com erro.
- **`--atualizar-bases`**: guarda a versão atual como `*.anterior`, baixa a
  nova e só então apaga a antiga. Se o download falhar, a antiga volta. O
  COCONUT só é baixado se a versão publicada mudou. Os caches que dependem
  das bases atualizadas (taxonomia e ChEMBL) são apagados, para não misturar
  versões.
- **Download manual**: se um servidor recusar o programa, baixe o arquivo
  pelo navegador e salve-o com o nome e na pasta da tabela (a mensagem de
  erro mostra o endereço e o caminho exatos).
- O GBIF não entra aqui: o download dele depende da região (etapa 1).

**Saídas**: as pastas `dados_*` e `bases_baixadas.txt` (data, `OK`/`FALHOU`
e caminho de cada base). O arquivo só é gravado se nenhuma base essencial
falhar.

**Retomada**: downloads interrompidos são refeitos do início (ficam como
`*.parcial` até terminar).

---

## 13. Etapa 1: `gbif`

`mods/buscar_especies_gbif.py` → `especies_gbif.csv`

**Objetivo**: levantar **todas as plantas com registro de ocorrência dentro
da região**.

**Entradas**

| Tipo | O quê |
|---|---|
| Configuração | coordenadas de `[regiao]` (e `raio_km`) |
| Credenciais | `GBIF_USER`, `GBIF_PWD`, `GBIF_EMAIL`, só para um download novo |
| Internet | API de downloads do GBIF |

**Como funciona**

1. Envia ao GBIF um **pedido de download** no formato `SPECIES_LIST` (sem
   limite de paginação), com os filtros: dentro da região; reino
   **Plantae**; com coordenada e sem problema geoespacial; ocorrência
   **presente**.
2. Espera o GBIF preparar o arquivo (de 5 min a 1 h, conforme a fila),
   conferindo a cada 30 s. Falhas passageiras de rede não interrompem a
   espera.
3. Baixa e agrega sinônimos e infraespecíficos na espécie aceita
   (`speciesKey`), somando as ocorrências.
4. Busca o **nome popular em português** das 1.500 espécies com mais
   ocorrências (guardado em cache).

**Reaproveitamento**: a chave de cada pedido fica em
`dados_gbif_download/pedidos.json`. Rodar de novo com a **mesma região**
reaproveita o download, sem gastar cota nem esperar a fila. Para usar um
download que você já fez no site do GBIF, defina a variável de ambiente
`GBIF_DOWNLOAD_KEY` com a chave dele.

**Saídas**

`especies_gbif.csv`, uma linha por espécie, da mais para a menos
registrada:

| Coluna | Conteúdo |
|---|---|
| `speciesKey` | identificador da espécie no GBIF |
| `reino`, `filo`, `classe`, `ordem`, `familia` | taxonomia |
| `nome_cientifico` | nome da espécie |
| `nome_popular_pt` | nome(s) popular(es) em português |
| `categoria_taxonomica` | `SPECIES` |
| `n_ocorrencias_na_area` | número de registros dentro da região |

Também: `dados_gbif_download/` (pedidos, zip e dados extraídos, cache dos
nomes populares).

**Retomada**: se a espera for interrompida, a próxima rodada reaproveita o
mesmo pedido (a chave já foi registrada).

---

## 14. Etapa 2: `plantas`

`mods/montar_lista_plantas.py` → `plantas.csv`

**Objetivo**: montar a **lista final de plantas**, com nomes conferidos,
antes de qualquer busca de compostos ou atividades.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivos | `especies_gbif.csv` (etapa 1); `config/lista_de_plantas.txt` ou `[taxons]` |
| Bases locais | Flora e Funga do Brasil e WFO (etapa 0) |
| Configuração | `[regiao] termos_texto`; `[termos_pubmed]` (só para anotar); `[artigos]`; `[taxonomia]` |
| Internet | PubMed, OpenAlex, API do GBIF |

**Como funciona**

**a) Três fontes de plantas**

| Fonte | O que entra |
|---|---|
| `gbif` | plantas com ocorrência na região (etapa 1) |
| `lista` | a sua lista |
| `artigos` | plantas citadas em artigos que mencionam a região |

**b) Descoberta de plantas em artigos.** Busca no PubMed e no OpenAlex os
artigos cujo título ou resumo cita **um termo da região** (`termos_texto`),
seja qual for o tema, até `max_artigos` em cada base. Os nomes científicos
citados (inclusive abreviados, como *E. oleracea*) entram na lista.
- **As atividades não filtram a busca.** Quando um artigo cita um termo de
  uma atividade de `[termos_pubmed]`, as plantas dele recebem a anotação na
  coluna `atividades_artigos` (ex.: `clareadora (3 artigos)`). É só uma
  pista de tema: quem julga a atividade é o Llama, na etapa 5.
- **OpenAlex conferido no texto**: a busca do OpenAlex reduz palavras ao
  radical e traz trabalhos que não citam a região. Cada um é conferido, e só
  fica se o título ou o resumo citar um termo da região.
- **`contexto_vegetal = true`** exige também uma palavra como *plant*,
  *extract* ou *bark*, o que reduz artigos de outros temas.
- Como a busca não filtra o tema, aparecem também animais e microrganismos
  (*Plasmodium falciparum*). Nomes vindos só de artigos que nem a Flora nem
  o WFO reconhecem ficam como `não reconhecido` e não são usados nas etapas
  3 e 5.

**c) Conferência dos nomes em três bases.** Todo nome, de qualquer fonte, é
conferido:

| Prioridade | Base | Como | Fornece |
|---|---|---|---|
| 1 | Flora e Funga do Brasil | arquivo local | nome aceito ou sinônimo, família |
| 2 | World Flora Online | arquivo local | nome aceito ou sinônimo, família |
| 3 | GBIF | API, um nome por vez | nome aceito ou sinônimo, filo, classe, ordem, família |

Cada nome é corrigido para o **nome aceito**. Quando as bases discordam,
vale a de maior prioridade, e a divergência fica anotada. Erros leves de
grafia (*Alpinia speciosas*) são corrigidos se houver um nome muito
parecido no mesmo gênero.

**d) Uma linha por planta.** Nomes que levam ao mesmo nome aceito viram uma
linha só: *Pothomorphe umbellata* (sua lista) e *Piper umbellatum* (GBIF)
viram *Piper umbellatum*, com os dois nomes em `nomes_busca`.

**e) Complementos.** Para as plantas da lista e dos artigos, o GBIF fornece
também o número de ocorrências na área e o nome popular, só como
informação.

**Saídas**

**`plantas.csv`**: uma linha por planta; primeiro as da sua lista, depois
por número de ocorrências.

| Coluna | Conteúdo |
|---|---|
| `speciesKey` | identificador no GBIF |
| `reino`, `filo`, `classe`, `ordem`, `familia` | taxonomia |
| `nome_cientifico` | **nome aceito**, usado em todas as etapas seguintes |
| `nome_popular_pt` | nome popular em português |
| `categoria_taxonomica` | `SPECIES`, `GENUS`, `VARIETY`… |
| `n_ocorrencias_na_area` | registros do GBIF dentro da região |
| `nome_original` | nome(s) como apareceram nas fontes |
| `situacao_nome` | `aceito`, `aceito (sem status confirmado)`, `sinônimo corrigido`, `grafia corrigida`, `grafia e sinônimo corrigidos`, `gênero` ou `não reconhecido` |
| `nomes_busca` | **todos** os nomes da planta, separados por `;`. As etapas 3 e 5 buscam por todos |
| `observacoes_taxonomia` | o que cada base disse, divergências, avisos |
| `fonte` | `gbif`, `lista`, `artigos` ou combinações (ex.: `gbif; lista`) |
| `atividades_artigos` | atividades do input citadas nos artigos da descoberta, ex.: `clareadora (3 artigos)` |

**`plantas_conferencia_taxonomica.csv`**: um nome por linha (original ou
aceito), para conferir as decisões taxonômicas. Colunas:
`nome_cientifico`, `fonte`, `status`, `veredito_flora`, `veredito_wfo`,
`veredito_gbif`.

**`plantas_artigos_evidencias.csv`**: uma linha por planta × artigo da
descoberta. Colunas: `nome_no_artigo`, `nome_aceito`,
`atividades_no_texto`, `base`, `referencia` (PMID ou id do OpenAlex),
`ano`, `titulo`, `doi`.

**Retomada**: caches `cache_taxonomia_*.jsonl` (nomes),
`cache_gbif_extras.jsonl` (ocorrências e nomes populares),
`cache_openalex.jsonl` e `cache_pubmed_*.jsonl` (artigos). Com listas muito
grandes, a primeira rodada pode levar horas (seção 22), mas pode ser
interrompida e retomada à vontade.

---

## 15. Etapa 3: `bioativos`

`mods/cruzar_especies_bioativos.py` → `especies_com_compostos_bioativos.csv`

**Objetivo**: encontrar os **compostos já registrados** para cada planta.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivo | `plantas.csv` (etapa 2) |
| Bases locais | COCONUT, NPASS, Dr. Duke, LOTUS, FooDB (etapa 0) |
| Configuração | `[bioativos]`; `[termos_pubmed]` (para filtrar as atividades do Dr. Duke) |
| Internet | PubChem, só para dar InChIKey aos compostos do Dr. Duke e do FooDB que não o têm |

**Como funciona**

| Base | O que acrescenta |
|---|---|
| **COCONUT** | compostos, organismos de origem, SMILES, InChIKey, classificação química, semelhança com fármacos |
| **NPASS 3.0** | pares composto–espécie, nomes, estruturas e **atividades e alvos medidos** |
| **Dr. Duke** (USDA) | **parte da planta**, **teor (ppm)** e **atividades** atribuídas a cada composto na literatura |
| **LOTUS** | **referência (DOI)** do artigo que relata cada par composto × planta (o COCONUT já inclui os pares do LOTUS, mas sem a referência) |
| **FooDB** | para plantas **alimentícias**: o alimento e o **teor** |

- Cada planta é procurada por **todos os nomes** de `nomes_busca`: um
  composto registrado sob um sinônimo vai para a linha do nome aceito.
- O mesmo composto vindo de várias bases vira **uma linha**, unificada pelo
  InChIKey (`base = COCONUT; DUKE; LOTUS`).
- O Dr. Duke só traz o nome do composto (ex.: `CAFFEIC-ACID`). O InChIKey é
  obtido no PubChem, pelo nº CAS ou pelo nome, e guardado em
  `cache_pubchem_duke.jsonl`. O FooDB usa o mesmo mecanismo para os poucos
  compostos sem InChIKey.
- Plantas `não reconhecido` não são buscadas (`incluir_nao_reconhecidos`).
- Gêneros: ver seção 7.2.
- Se uma base complementar (Dr. Duke, LOTUS, FooDB) não puder ser lida, a
  etapa segue sem ela, com aviso.

**Saída**

`especies_com_compostos_bioativos.csv`: uma linha por **composto ×
planta**, ordenada pelo nome do composto.

| Coluna | Conteúdo |
|---|---|
| `composto_nome` | nome do composto |
| `composto_id` | identificador(es) nas bases (`CNP…` COCONUT, `NPC…` NPASS, `DUKE:…`, `LOTUS:…`, `FOODB:…`) |
| `composto_inchikey` | InChIKey |
| `especie_normalizada` | nome da planta como está na base de compostos |
| `base` | base(s) em que o par foi encontrado |
| `atividade_ou_alvo` | alvos e tipos de medida do NPASS |
| `nome_cientifico`, `reino`, `familia`, `nome_popular_pt`, `fonte` | dados da planta (de `plantas.csv`) |
| `pubchem_cid` | identificador no PubChem |
| `composto_smiles` | estrutura (SMILES) |
| `np_classifier_pathway`, `np_classifier_superclass`, `np_classifier_class` | via biossintética e classe (NP Classifier) |
| `chemical_class` | classe química (ClassyFire) |
| `qed_drug_likeliness` | semelhança com fármacos (QED, 0 a 1) |
| `np_likeness` | semelhança com produtos naturais |
| `molecular_formula` | fórmula molecular |
| `parte_planta_duke` | partes em que o composto foi registrado no Dr. Duke (ex.: `Seed; Leaf`) |
| `teor_ppm_duke` | teor por parte (ex.: `Seed: 10000-30000 ppm`) |
| `atividades_duke` | atividades do composto no Dr. Duke. Com `[termos_pubmed]`, só as que casam com as suas (ex.: `clareadora (Tyrosinase-Inhibitor)`); sem, todas (até 40) |
| `referencias_lotus` | DOIs que relatam o composto naquela planta (até 10) |
| `alimento_foodb` | alimento(s) do FooDB (ex.: `Cocoa bean`) |
| `teor_foodb` | teor por alimento e parte (ex.: `Cocoa bean, seed: 10-30 mg/100 g`) |

**Retomada**: a etapa leva minutos e é refeita por inteiro; só as consultas
ao PubChem ficam em cache.

---

## 16. Etapa 4: `chembl`

`mods/consultar_chembl.py` → `compostos_chembl.csv`

**Objetivo**: trazer as atividades **medidas em ensaios** de cada composto
(IC50, Ki, % de inibição…), de artigos de química medicinal. É um
complemento ao PubMed.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivo | `especies_com_compostos_bioativos.csv` (etapa 3) |
| Base local | estruturas do ChEMBL (etapa 0) |
| Configuração | `[chembl]`; `[termos_pubmed]` |
| Internet | API do ChEMBL |

**Como funciona**

1. **Localização pelo InChIKey**, comparando com o arquivo de estruturas,
   localmente (sem o arquivo, pela API).
2. **Estereoisômeros** (`estereoisomeros = true`): sem o InChIKey exato,
   procura moléculas com a mesma conectividade (os 14 primeiros caracteres
   do InChIKey), até 5 por composto. O resultado é marcado como tal, porque
   estereoisômeros podem ter atividades diferentes.
3. **Registros ativos**: `pChEMBL ≥ pchembl_minimo` (padrão 5, isto é, até
   10 µM) ou marcados como ativos pelo ChEMBL. Registros com alerta de
   validade são descartados.
4. **Ligação com as suas atividades**: o alvo e a descrição do ensaio são
   comparados ao núcleo de cada termo de `[termos_pubmed]`
   (`tyrosinase inhibit*` → *tyrosinase*). Os núcleos usados aparecem na
   tela.
5. **Documento de origem**: PMID, DOI, ano e revista de cada registro.
6. **Previsão por similaridade** (opcional): para compostos sem dados,
   atividades de moléculas parecidas, numa coluna própria. É **hipótese**.

**Saídas**

`compostos_chembl.csv` (as colunas são anexadas às planilhas da etapa 5):

| Coluna | Exemplo |
|---|---|
| `InChIKey` | `REFJWTPEDVJJIY-UHFFFAOYSA-N` |
| `chembl_id` | `CHEMBL50` |
| `correspondencia_chembl` | `exata` ou `estereoisômero (mesma conectividade)` |
| `atividades_chembl` | `clareadora (Tyrosinase, IC50 = 900 nM, 2 registros; PMID 11111, 22222)` |
| `atividades_previstas_chembl` | só com a previsão ligada |

`evidencias_chembl.csv`: um registro de ensaio por linha. Colunas:
`InChIKey`, `composto`, `atividade`, `correspondencia`,
`molecula_ensaiada`, `alvo`, `organismo_alvo`, `descricao_ensaio`,
`tipo_ensaio`, `medida`, `relacao`, `valor`, `unidade`, `pchembl`,
`comentario`, `PMID`, `DOI`, `ano`, `revista`, `documento_chembl`.

**Retomada**: caches `cache_chembl_*.jsonl`. Compostos cuja consulta falhou
ficam como `consulta pendente (rode de novo)`.

---

## 17. Etapa 5: `pubmed`

`mods/consultar_atividades_pubmed.py` → `especies_atividades.csv` +
`atividades_plantas.csv` + `atividades_compostos.csv` +
`evidencias_pubmed.csv`

**Objetivo**: encontrar no PubMed artigos sobre as atividades das
**plantas** e dos **compostos** e manter, com o Llama, só os que
**demonstram experimentalmente** um efeito.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivos | `especies_com_compostos_bioativos.csv` (etapa 3), `plantas.csv` (etapa 2), `compostos_chembl.csv` (etapa 4) |
| Configuração | `[termos_pubmed]`, `[pubmed]`, `[ollama]` |
| Internet | PubChem e PubMed (NCBI) |
| Local | Ollama com o modelo de `[ollama]` |

**Como funciona**, em seis fases (a ordem em que aparecem na tela):

**1. Identificação dos compostos (PubChem).** Para cada composto: InChIKey
validado, CID e nome preferido no PubChem, em lotes de 200.

**2. Artigos ligados à estrutura (via InChIKey).** O PubChem liga cada CID
aos artigos que tratam do composto (indexação MeSH e depositantes). Esses
artigos são filtrados pelas suas atividades, pela existência de resumo e,
se configurado, pela exclusão de revisões. Isso identifica o composto pela
estrutura, sem depender do nome.

**3. Busca pelo nome.**
- **Plantas**: todos os nomes de `nomes_busca`, no título e no resumo, uma
  busca por atividade, até `max_artigos_por_planta` (os mais relevantes).
- **Compostos**: conforme `busca_composto_por_nome`. Nomes sistemáticos
  (IUPAC) e códigos não são pesquisados, porque não aparecem em resumos.
- **Pré-checagem**: com mais de uma atividade, cada planta ou composto
  passa antes por **uma** busca com todas as atividades juntas. Só quem tem
  algum artigo segue para as buscas por atividade. Como a maioria das
  plantas não tem artigo nenhum, isso troca, por exemplo, 7 buscas por 1.

**4. Download dos resumos** (PubMed, em lotes de 200).

**5. Pré-filtro.** Um artigo achado pelo nome precisa citar a planta
(qualquer nome, inclusive abreviado) ou o composto no título ou no resumo.

**6. Julgamento pelo Llama.** Ele lê cada par **entidade × resumo** e
responde em JSON:

- **Positivo**: o texto relata um **resultado experimental** (in vitro, ex
  vivo, in vivo ou clínico) em que a planta (extrato, fração, óleo, resina,
  substância isolada dela) ou o composto **produziu** o efeito. Ex.: "o
  extrato etanólico das folhas inibiu *S. aureus* (CIM 125 µg/mL)".
- **Negativo**: só menção; efeito de outra espécie ou composto; uso
  tradicional sem teste; resultado nulo ou fraco; química sem ensaio
  biológico; revisão ou especulação; estudo só in silico.
- Com `[termos_pubmed]`, só contam as atividades listadas.
- Quando a planta tem sinônimos, o Llama é avisado ("mesma planta, também
  citada como…").

Para cada artigo positivo, o Llama informa também:

| Informação | Valores |
|---|---|
| tipo de estudo | `in vitro`, `ex vivo`, `in vivo`, `clínico` |
| parte da planta (só plantas) | `folha`, `caule`, `casca`, `raiz`, `rizoma`, `tubérculo/bulbo`, `flor`, `fruto`, `semente`, `parte aérea`, `planta inteira`, `exsudato (látex/resina)`, `broto/calo/cultura` ou `não informado` |

A **melhor evidência** é o tipo de estudo mais forte entre os artigos
positivos: **clínico > in vivo > ex vivo > in vitro**.

**Ordem de leitura**: primeiro as plantas (as com compostos e mais
ocorrências primeiro), depois os compostos (os com atividade no NPASS e em
mais plantas primeiro). Assim, os resultados mais úteis ficam prontos
antes.

**Quais plantas são pesquisadas**: por padrão, todas as espécies de
`plantas.csv`, inclusive as sem compostos conhecidos (uma planta pouco
estudada quimicamente pode ter atividade relatada para o extrato). Ficam de
fora: gêneros sem espécie, nomes `não reconhecido`, as sem compostos se
`plantas_pesquisadas = com_compostos`, e as que passam de `max_plantas`.

**Saídas**: quatro planilhas, descritas em detalhe na seção 18.

| Arquivo | Uma linha por |
|---|---|
| `atividades_plantas.csv` | planta de `plantas.csv` (todas, pesquisadas ou não) |
| `atividades_compostos.csv` | composto |
| `especies_atividades.csv` | par planta × composto (visão combinada; **arquivo principal**) |
| `evidencias_pubmed.csv` | artigo positivo |

**Retomada**: todas as fases têm cache (seção 21). Cada julgamento do Llama
é gravado assim que termina, em `cache_llm_classificacao.jsonl`. Buscas que
falharam aparecem como `busca pendente (rode de novo)` e são refeitas na
próxima rodada.

---

# Parte V: Resultados

## 18. Qual arquivo abrir e como ler

### 18.1 Qual arquivo responde a cada pergunta

| Pergunta | Arquivo |
|---|---|
| Que plantas entraram na lista, e de onde vieram? | `plantas.csv` |
| Por que um nome foi corrigido? O que cada base disse? | `plantas_conferencia_taxonomica.csv` |
| Em que artigos sobre a região cada planta aparece? | `plantas_artigos_evidencias.csv` |
| Que compostos cada planta tem? | `especies_com_compostos_bioativos.csv` |
| Que **plantas** têm atividade demonstrada, com que evidência e em que parte? | **`atividades_plantas.csv`** |
| Que **compostos** têm atividade demonstrada (PubMed, ChEMBL, Dr. Duke), e em que plantas ocorrem? | **`atividades_compostos.csv`** |
| Tudo junto, planta × composto | `especies_atividades.csv` |
| Qual artigo sustenta cada resultado? | `evidencias_pubmed.csv`, `evidencias_chembl.csv` |

> Abrindo no Excel: os arquivos são UTF-8 com BOM, separados por vírgula, e
> os acentos aparecem corretamente. Se tudo cair numa coluna só, use
> *Dados → De Texto/CSV* e escolha "vírgula" como delimitador.

### 18.2 `atividades_plantas.csv`

Uma linha por planta de `plantas.csv`, as com mais artigos positivos
primeiro.

| Coluna | Conteúdo |
|---|---|
| `nome_cientifico`, `familia`, `nome_popular_pt` | identificação |
| `situacao_nome`, `fonte`, `n_ocorrencias_na_area` | de `plantas.csv` |
| `n_compostos` | compostos conhecidos (etapa 3) |
| `bases_compostos` | quantos desses compostos vieram de cada base (ex.: `COCONUT 120; NPASS 85; LOTUS 60; DUKE 14; FOODB 9`). Um composto em duas bases conta nas duas |
| `atividades_relatadas_planta` | ex.: `anti-inflamatória (PMID 123, 456); antioxidante (PMID 789)`, ou o motivo de não haver resultado (seção 19) |
| `melhor_evidencia_planta` | `clínico`, `in vivo`, `ex vivo`, `in vitro` ou `não informado` |
| `estudos_planta` | ex.: `in vivo (PMID 456); in vitro (PMID 123, 789)` |
| `partes_planta` | ex.: `folha (PMID 123, 789); casca (PMID 456)` |
| `n_artigos_positivos` | artigos positivos distintos |
| `compostos_com_atividade_relatada` | compostos desta planta com atividade positiva no PubMed |

As atividades desta planilha vêm **só do PubMed** (artigos sobre a própria
planta). Os compostos de cada planta e as atividades atribuídas a eles nas
bases químicas e no ChEMBL estão em `atividades_compostos.csv` e
`especies_atividades.csv`.

### 18.3 `atividades_compostos.csv`

Uma linha por composto (unificado pelo InChIKey), os com mais artigos
positivos primeiro.

| Coluna | Conteúdo |
|---|---|
| `composto_nome` | nome nas bases de produtos naturais |
| `nome_pubchem` | nome preferido no PubChem |
| `InChIKey`, `pubchem_cid` | identificadores |
| `composto_ids` | identificadores nas bases de compostos |
| `plantas`, `n_plantas` | plantas da lista em que o composto ocorre |
| `atividades_relatadas_composto` | ex.: `clareadora (PMID 111, 222)` |
| `melhor_evidencia_composto`, `estudos_composto` | como nas plantas |
| `n_artigos_positivos` | artigos positivos distintos |
| `bases` | bases químicas em que o composto foi encontrado nessas plantas (ex.: `COCONUT; DUKE; LOTUS; NPASS`) |
| `atividades_duke` | atividades no Dr. Duke (com `[termos_pubmed]`, só as que casam com as suas) |
| `referencias_lotus` | DOIs por planta, segundo o LOTUS (ex.: `Euterpe oleracea: DOI 10.1/abc; …`; até 5 plantas) |
| `chembl_id`, `correspondencia_chembl`, `atividades_chembl`, `atividades_previstas_chembl` | da etapa 4 |

Esta planilha reúne as **três fontes de atividade** de cada composto:
**PubMed** (artigos lidos pelo Llama), **ChEMBL** (ensaios medidos) e **Dr.
Duke** (atividades compiladas da literatura).

### 18.4 `especies_atividades.csv`

A visão combinada: uma linha por **composto × planta** (as mesmas linhas de
`especies_com_compostos_bioativos.csv`), com todas as colunas daquele
arquivo e mais `InChIKey` (validado ou completado pelo PubChem), as
colunas de atividade do composto e da planta (`atividades_relatadas_*`,
`melhor_evidencia_*`, `estudos_*`, `partes_planta`) e as colunas do ChEMBL.

Plantas **sem compostos conhecidos** não aparecem aqui; estão em
`atividades_plantas.csv`.

### 18.5 `evidencias_pubmed.csv`

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

### 18.6 Um roteiro de leitura

0. Para ter a visão de conjunto antes das planilhas, rode `./graficos.sh` e
   abra `graficos/relatorio.html` (seção 20): o funil da visão geral e o
   *mapa de oportunidades* da etapa 5 apontam por onde começar.
1. Em `atividades_plantas.csv`, filtre `n_artigos_positivos > 0` e ordene
   por `melhor_evidencia_planta`. Plantas com estudo **in vivo** ou
   **clínico** e **poucos artigos** podem ser oportunidades pouco
   exploradas.
2. Em `partes_planta`, veja se a atividade vem de uma parte de coleta
   sustentável (folha, fruto, semente, exsudato) ou destrutiva (raiz,
   casca, planta inteira).
3. Em `atividades_compostos.csv`, procure compostos com atividade **no
   PubMed e no ChEMBL**: são os mais bem sustentados.
4. Antes de qualquer conclusão, abra o `link` em `evidencias_pubmed.csv`: o
   Llama faz uma triagem, não uma revisão sistemática.

---

## 19. Mensagens de status nas planilhas

Quando não há atividade, a célula explica o motivo.

**Colunas `atividades_relatadas_planta` e `atividades_relatadas_composto`**

| Mensagem | Significado | O que fazer |
|---|---|---|
| `nenhuma relação causal positiva encontrada…` | houve artigos, mas nenhum demonstrou a atividade | — |
| `nenhum artigo encontrado no PubMed` | as buscas não trouxeram artigos | — |
| `artigos encontrados; leitura pelo Llama pendente` | só nos arquivos `*_parcial.csv`: ainda não lido | esperar a rodada principal |
| `busca pendente (rode de novo)` | alguma busca falhou (rede, limite do NCBI) | `./rodar.sh --a-partir-de pubmed` |
| `não pesquisado: táxon sem nível de espécie` | gênero sozinho | — |
| `não pesquisado: nome não reconhecido em nenhuma base…` | nome não reconhecido | `[pubmed] incluir_nao_reconhecidos = true`, se quiser |
| `não pesquisado: plantas_pesquisadas = com_compostos` | planta sem compostos, excluída pela opção | `plantas_pesquisadas = todas` |
| `não pesquisado: fora do limite max_plantas` | passou do teto | aumente ou zere `max_plantas` |
| `não pesquisado: fora do limite max_compostos` | passou do teto | aumente ou zere `max_compostos` |
| `não pesquisado: sem vínculo no PubChem e sem nome adequado para busca` | sem artigos ligados ao CID e com nome só sistemático | — |

**Coluna `atividades_chembl`**

| Mensagem | Significado |
|---|---|
| `sem InChIKey válido` | o composto não tem estrutura identificável |
| `composto não encontrado no ChEMBL` | nem o InChIKey nem estereoisômeros estão no ChEMBL |
| `no ChEMBL, sem atividade do input medida como ativa` | está no ChEMBL, sem registro ativo para as suas atividades |
| `consulta pendente (rode de novo)` | a consulta falhou: rode `--a-partir-de chembl` |
| `não consultado no ChEMBL` | a etapa 4 está desligada ou não rodou depois da etapa 3 |

---

## 20. Gráficos dos resultados

`graficos.py` → `graficos/relatorio.html`

**Objetivo**: ver os resultados de cada etapa em gráficos, sem abrir as
planilhas uma a uma. O script **só lê** os arquivos que o pipeline já
gravou: não acessa a internet, não altera nenhuma planilha nem cache e não
interfere numa rodada em andamento.

### 20.1 Como rodar

| Linux / macOS | Windows | Efeito |
|---|---|---|
| `./graficos.sh` | `graficos.bat` | gráficos de todas as etapas já concluídas |
| `./graficos.sh --parcial` | `graficos.bat --parcial` | etapa 5 a partir dos `*_parcial.csv` (rode antes `./rodar.sh parcial`) |
| `./graficos.sh --etapas plantas,pubmed` | idem | só as etapas indicadas |
| `./graficos.sh --top 40` | idem | rankings com 40 itens (padrão: 25) |
| `./graficos.sh --formato svg` | idem | arquivos em SVG (ou `pdf`) para publicação; o relatório continua com PNG |
| `./graficos.sh --dpi 300` | idem | PNG em alta resolução (padrão: 150) |
| `./graficos.sh --pasta graficos_amazonas` | idem | outra pasta de saída (para guardar rodadas diferentes) |

Os nomes de etapa em `--etapas` são `geral`, `downloads`, `gbif`,
`plantas`, `bioativos`, `chembl` e `pubmed`.

- **Na primeira vez**, o lançador instala o `matplotlib` no `.venv` (precisa
  de internet só nesse momento). Sem os lançadores:
  `.venv/bin/python graficos.py` (Windows: `.venv\Scripts\python graficos.py`).
- **Pode rodar a qualquer momento**: etapas sem arquivo de saída são puladas,
  com um aviso na tela e no relatório. Rodar de novo substitui os gráficos
  das etapas escolhidas.
- Leva de segundos a poucos minutos (a planilha de compostos pode ter
  milhões de linhas; só as colunas necessárias são lidas).

### 20.2 O que é gerado

```
graficos/
├── relatorio.html          ← abra no navegador: todos os gráficos, etapa por etapa
├── 00a_geral_funil.png     ← um arquivo por gráfico: <etapa><letra>_<etapa>_<assunto>
├── 1a_gbif_especies_mais_registradas.png
├── ...
└── dados/                  ← a tabela por trás de cada gráfico (CSV, abre no Excel)
    ├── 00a_geral_funil.csv
    └── ...
```

O **relatório** traz, para cada etapa, os números-chave em destaque, os
gráficos com uma explicação de como lê-los e, embaixo de cada um, o link
para a tabela correspondente. No fim, a lista dos arquivos lidos, com a
data de gravação de cada um. Para mandar o relatório a alguém, envie a
pasta `graficos/` inteira (o HTML procura as imagens ao lado dele).

### 20.3 Os gráficos, etapa por etapa

| Etapa | Gráfico | Responde |
|---|---|---|
| **Visão geral** | Funil de plantas e de compostos | quantos passam por cada filtro, do GBIF à atividade demonstrada (e do composto ao ChEMBL e ao PubMed) |
| **0 downloads** | Bases baixadas | tamanho de cada base; downloads que falharam em vermelho, com `FALHOU` escrito |
| **1 gbif** | Espécies mais registradas | as plantas mais comuns (ou mais coletadas) na região, com o nome popular |
| | Famílias com mais espécies | riqueza por família |
| | Curva de abundância | quantas espécies concentram metade dos registros; a cauda de espécies raras |
| **2 plantas** | Origem das plantas | quantas vieram do GBIF, da sua lista, dos artigos e de cada combinação |
| | Situação dos nomes | aceitos, sinônimos e grafias corrigidos, não reconhecidos |
| | Vereditos das três bases | o que a Flora do Brasil, o WFO e o GBIF disseram sobre os nomes |
| | Artigos da descoberta por ano | PubMed × OpenAlex ao longo do tempo |
| | Plantas mais citadas nos artigos | as mais estudadas na literatura sobre a região; em **cinza**, os nomes que nenhuma base reconheceu (palavras, animais, microrganismos), que ficam fora das etapas 3 e 5 |
| | Atividades citadas nos artigos | quantas plantas aparecem em artigos sobre cada atividade de `[termos_pubmed]` |
| | Famílias na lista final | riqueza por família, juntando as três fontes |
| **3 bioativos** | Contribuição de cada base | pares e compostos de COCONUT, NPASS, LOTUS, Dr. Duke e FooDB (a tabela traz também a contribuição exclusiva de cada uma) |
| | Plantas com mais compostos | as quimicamente mais estudadas |
| | Vias biossintéticas e superclasses | perfil químico do conjunto (NP Classifier) |
| | Famílias × vias | mapa de calor: a "assinatura química" de cada família |
| | Compostos mais frequentes | os de distribuição ampla e os possíveis marcadores |
| | QED × NP-likeness | espaço químico: compostos mais próximos de fármacos orais |
| | Partes da planta (Dr. Duke) | onde os compostos foram registrados |
| **4 chembl** | Situação dos compostos | com atividade (exata ou estereoisômero), sem registro ativo, não encontrados, pendentes |
| | Atividades e alvos | quantos compostos têm ensaio ativo para cada atividade e cada alvo |
| | Potência (pChEMBL) | distribuição geral e por atividade, com as marcas de 10 µM, 1 µM, 100 nM e 10 nM |
| | Tipos de medida e de ensaio | IC50, Ki, CIM...; ligação, funcional, ADME, toxicidade |
| | Artigos de origem por ano | de quando são os dados de ensaio |
| **5 pubmed** | Julgamentos do Llama | quantos resumos já foram lidos e a proporção de positivos (vem do cache: útil com a etapa em andamento) |
| | Resultado da busca (plantas e compostos) | com atividade, sem resultado positivo, sem artigo, pendentes, não pesquisados |
| | Plantas e compostos com mais artigos positivos | cor = melhor evidência (clínico > in vivo > ex vivo > in vitro) |
| | **Mapa de oportunidades** | compostos conhecidos × artigos positivos; nomeia as plantas com evidência in vivo ou clínica, poucos artigos e química pouco conhecida |
| | Fontes de atividade dos compostos | PubMed, ChEMBL e Dr. Duke, sozinhos ou combinados |
| | Atividades demonstradas | artigos positivos por atividade, em plantas e em compostos |
| | Plantas × atividades | mapa de calor das plantas mais estudadas |
| | Tipo de estudo | in vitro, ex vivo, in vivo, clínico |
| | Partes da planta | coloridas pela coleta: sustentável (folha, fruto, semente, flor, exsudato, parte aérea) ou destrutiva (raiz, casca, caule, rizoma, tubérculo, planta inteira) |
| | Artigos positivos por ano | interesse da pesquisa ao longo do tempo |
| | Via de busca dos compostos | quantos artigos vieram pelo InChIKey e quantos pelo nome |

Um gráfico só aparece quando há dados para ele: por exemplo, *Atividades
citadas nos artigos* exige `[termos_pubmed]` preenchido, e *Partes da planta
(Dr. Duke)* exige `usar_duke = true`.

### 20.4 Cuidados na leitura

- Os gráficos herdam as **limitações das planilhas** (seção 24): contagem de
  artigos mede atenção da pesquisa, não força do efeito; "nenhum artigo"
  não é ausência de atividade.
- As **atividades** da etapa 5 são os rótulos escritos pelo Llama; nomes
  parecidos (`antibacteriana` e `antimicrobiana`) aparecem separados.
- No **modo parcial**, os números da etapa 5 crescem a cada rodada do
  `./rodar.sh parcial`: anote a data do relatório (aparece no topo).
- Cores: a paleta foi escolhida para ser distinguível por pessoas com
  daltonismo, e nenhuma informação depende só da cor (há rótulos e
  legendas em todos os gráficos).

---

# Parte VI: Referência

## 21. Caches

Cada linha de um arquivo `cache_*.jsonl` é uma consulta concluída. As
chaves incluem a consulta exata (e, quando importa, o modelo do Llama e as
atividades), de modo que mudar a configuração não reaproveita resultados
errados: só o que mudou é refeito.

| Cache | Etapa | Guarda | Apague para… |
|---|---|---|---|
| `dados_gbif_download/pedidos.json` | 1 | chave do pedido de cada região | forçar um download novo do GBIF |
| `dados_gbif_download/cache_nomes_populares.json` | 1 | nomes populares das espécies da região | atualizar os nomes populares |
| `cache_taxonomia_flora.jsonl`, `cache_taxonomia_wfo.jsonl`, `cache_taxonomia_gbif.jsonl` | 2 | veredito de cada base para cada nome | reconferir nomes (feito sozinho com `--atualizar-bases`) |
| `cache_gbif_extras.jsonl` | 2 | ocorrências e nome popular das plantas da lista e dos artigos | atualizar esses dados |
| `cache_openalex.jsonl` | 2 | buscas no OpenAlex | buscar artigos novos |
| `cache_pubmed_buscas.jsonl` | 2 e 5 | PMIDs de cada busca no PubMed | buscar artigos publicados depois |
| `cache_pubmed_artigos.jsonl` | 2 e 5 | títulos e resumos baixados | (raramente necessário) |
| `cache_pubchem_duke.jsonl` | 3 | InChIKey dos compostos do Dr. Duke e do FooDB | refazer essa identificação |
| `cache_chembl_*.jsonl` | 4 | moléculas, atividades, estereoisômeros, documentos, similares | atualizar o ChEMBL (feito sozinho com `--atualizar-bases`) |
| `cache_pubchem.jsonl`, `cache_pubchem_cid.jsonl` | 5 | nome e CID de cada composto | atualizar identificadores |
| `cache_pubchem_vinculos.jsonl` | 5 | artigos ligados a cada CID | buscar vínculos novos |
| `cache_pubmed_filtro.jsonl` | 5 | quais artigos ligados tratam de cada atividade | buscar artigos novos |
| `cache_llm_classificacao.jsonl` | 5 | julgamento do Llama para cada par entidade × artigo | ⚠️ **reavaliar tudo** (dias de trabalho; mova em vez de apagar) |

---

## 22. Tempo de execução e escala

| Etapa | Primeira vez | Nas seguintes |
|---|---|---|
| 0 `downloads` | 15–40 min (conexão) | segundos |
| 1 `gbif` | 5 min a ≈ 1 h (fila do GBIF) + nomes populares | segundos |
| 2 `plantas` | minutos a horas (leitura do WFO, descoberta em artigos, ≈ 3 consultas ao GBIF por nome fora da etapa 1) | minutos |
| 3 `bioativos` | minutos (mais a identificação dos compostos do Dr. Duke no PubChem, na 1ª vez) | minutos |
| 4 `chembl` | minutos a poucas horas (a previsão por similaridade pode levar muitas horas) | minutos |
| 5 `pubmed` | **horas a dias** | só o que falta |

**Listas grandes**: com 30 mil nomes em `lista_de_plantas.txt`, a etapa 2
pode levar de 10 a 20 horas na primeira vez (tudo em cache, pode
interromper).

**O que pesa na etapa 5**

- **Buscas no PubMed**: plantas × atividades, reduzidas pela pré-checagem.
  Com a chave do NCBI, ≈ 8 por segundo; sem ela, ≈ 3.
- **Leituras do Llama**: ≈ nº de pares entidade × artigo. A 12 s por
  resumo em CPU, 20 mil resumos levam cerca de 2,5 dias; com GPU, poucas
  horas.

**Para controlar o tempo**

- comece com `max_plantas = 300` e `max_compostos = 200`;
- restrinja as atividades em `[termos_pubmed]`;
- use `plantas_pesquisadas = com_compostos`;
- reduza `max_artigos_por_planta` e `max_artigos_por_composto`;
- `busca_composto_por_nome = nunca` (só a via InChIKey);
- use GPU, ou o `llama3.2:3b` em CPU;
- use a chave do NCBI.

---

## 23. Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `Problema no arquivo de entrada…` | o erro indica a linha: vírgula decimal, latitude e longitude trocadas, chave com nome errado ou repetida. Rode `./rodar.sh config` |
| A etapa 1 pergunta se você já configurou as credenciais | falta o login do GBIF em `config/credenciais.txt`. Responda **n**, preencha no editor que abrir, salve |
| `Credenciais do GBIF não configuradas…` e o pipeline para | rodando sem terminal, ele não pode perguntar. Preencha o `credenciais.txt` e rode de novo |
| `GBIF recusou o login (HTTP 401)` | usuário ou senha errados (use o **usuário**, não o e-mail) |
| O editor não abriu (Linux sem interface) | o pipeline usa `$EDITOR`, `nano` ou `vi`; se nenhum existir, edite o arquivo à mão |
| `[FALHOU]` na etapa 0 | sem internet ou servidor fora. Rode `./rodar.sh --somente downloads` mais tarde ou faça o download manual (seção 12) |
| `403 Client Error` ao baixar a Flora do Brasil | baixe pelo navegador em https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil e salve como `dados_flora_brasil/flora_brasil_dwca.zip` |
| `CERTIFICATE_VERIFY_FAILED` | o Python não confia no certificado do servidor. Confira se o `truststore` está instalado (`pip install truststore`), que faz o Python usar os certificados do sistema |
| `ERRO: Ollama não está acessível` | inicie o Ollama (Linux: `sudo systemctl start ollama` ou `ollama serve`; Windows/macOS: abra o aplicativo) e rode `--a-partir-de pubmed` |
| `modelo '…' não encontrado no Ollama` | `ollama pull llama3.1:8b` (ou o modelo de `[ollama]`) |
| `classificação(ões) falharam (timeout/JSON inválido)` | o Llama demorou demais; rode de novo ou aumente `timeout_segundos` |
| Muitas linhas `busca pendente` | limite de requisições do NCBI; use a chave e rode de novo para completar |
| OpenAlex pulado (sem cota) | coloque `OPENALEX_API_KEY`; a descoberta segue só com o PubMed |
| A lista tem "plantas" estranhas (bactérias, palavras) | vêm da descoberta em artigos; estão como `não reconhecido` e não são usadas nas etapas 3 e 5 |
| A etapa 5 está lenta demais | seção 22; confira se o Llama usa a GPU (`ollama ps`) |
| O Excel diz que o arquivo está em uso | feche a planilha no Excel antes de a etapa terminar: o pipeline não consegue substituir um arquivo aberto no Windows |
| Linux: `Permission denied` em `./rodar.sh` | `chmod +x rodar.sh instalar.sh`, ou `bash rodar.sh` |
| Linux: `externally-managed-environment` | use o `./instalar.sh` (cria o `.venv`); se faltar o venv: `sudo apt install python3-venv` |
| Linux: `bash\r: No such file or directory` | o arquivo foi salvo com quebras de linha do Windows: `sed -i 's/\r$//' rodar.sh instalar.sh` |
| Linux: o pipeline parou ao fechar o terminal | use `tmux` ou `nohup` (seção 10.4) |
| `ERRO: matplotlib não encontrado` | rode pelo `./graficos.sh` / `graficos.bat`, que o instala; à mão: `.venv/bin/python -m pip install matplotlib` (Windows: `.venv\Scripts\python -m pip install matplotlib`) |
| `./graficos.sh` falha ao instalar o matplotlib | a internet só é necessária na primeira vez; atrás de proxy, instale à mão com o comando acima |
| `Permission denied` em `./graficos.sh` | `chmod +x graficos.sh`, ou `bash graficos.sh` |
| Um gráfico esperado não aparece | a etapa dele não terminou ou a coluna está vazia: o aviso aparece na tela e no topo da etapa, no relatório |
| O relatório abre sem as imagens | o `relatorio.html` procura as imagens na mesma pasta: copie a pasta `graficos/` inteira, não só o HTML |
| `erro ao gerar os gráficos desta etapa` no relatório | em geral, uma planilha foi aberta e salva noutro formato (ex.: no Excel, com `;`). Rode a etapa de novo para regravá-la; as outras etapas não são afetadas |

---

## 24. Limitações e cuidados na interpretação

- **O Llama faz triagem, não revisão sistemática.** Ele pode errar,
  sobretudo com resumos ambíguos. Confirme os resultados importantes no
  artigo (coluna `link`).
- **Só resumos são lidos**, não o texto completo. Tipo de estudo e parte da
  planta podem ficar como `não informado`.
- **Atividade do composto ≠ atividade da planta.** Para compostos muito
  estudados (ex.: quercetina), os artigos tratam do composto em geral. A
  coluna `atividades_relatadas_planta` é a que liga a atividade à espécie.
- **Ausência de evidência não é evidência de ausência.** "Nenhum artigo
  encontrado" pode significar só que a planta é pouco estudada.
- **As bases taxonômicas discordam.** A prioridade (Flora > WFO > GBIF)
  decide o nome aceito; todas as versões ficam em `nomes_busca` e as
  divergências em `observacoes_taxonomia`.
- **A descoberta em artigos é textual.** Uma planta citada num artigo sobre
  a região não ocorre necessariamente lá; confira
  `n_ocorrencias_na_area`.
- **Registros do GBIF** incluem plantas cultivadas e erros de
  identificação.
- **A via InChIKey** depende dos vínculos do PubChem; muitos produtos
  naturais raros não têm nenhum (por isso existe a busca pelo nome).
- **Estereoisômeros e previsões** do ChEMBL são indicativos, não dados do
  próprio composto.
- **As bases de compostos** registram o que foi publicado: a falta de
  compostos não significa que a planta não os tenha.
- **FooDB**: uso comercial exige permissão dos autores. Se o projeto for
  comercial, use `usar_foodb = false` ou obtenha a permissão.

---

## 25. Bases de dados e como citá-las

| Base | Uso no pipeline | Endereço |
|---|---|---|
| GBIF | ocorrências na região; taxonomia | https://www.gbif.org |
| Flora e Funga do Brasil (JBRJ) | nomes (lista oficial do Brasil) | https://floradobrasil.jbrj.gov.br |
| World Flora Online | nomes (lista mundial) | https://www.worldfloraonline.org |
| COCONUT 2.0 | produtos naturais e organismos | https://coconut.naturalproducts.net |
| NPASS 3.0 | pares espécie–composto, atividades, alvos | https://bidd.group/NPASS |
| Dr. Duke's Phytochemical and Ethnobotanical Databases (USDA) | parte da planta, teor, atividades | https://phytochem.nal.usda.gov |
| LOTUS | pares composto–organismo com DOI | https://lotus.naturalproducts.net · dados: https://zenodo.org/records/19360665 |
| FooDB | compostos de alimentos e teores (uso comercial exige permissão) | https://foodb.ca |
| ChEMBL | atividades medidas em ensaios | https://www.ebi.ac.uk/chembl |
| PubChem | InChIKey, CID, nomes, artigos ligados | https://pubchem.ncbi.nlm.nih.gov |
| PubMed | resumos de artigos | https://pubmed.ncbi.nlm.nih.gov |
| OpenAlex | artigos (descoberta de plantas) | https://openalex.org |
| Ollama / Llama 3.1 | julgamento dos resumos | https://ollama.com |

Ao publicar resultados:
- **GBIF**: cite o **DOI do download**. Ele aparece no site do GBIF, em
  *Downloads* da sua conta; a chave está em
  `dados_gbif_download/pedidos.json`.
- **Demais bases**: cite a publicação de referência indicada no site de
  cada uma e a versão usada (COCONUT: `dados_bioativos/coconut_versao.txt`;
  LOTUS: `dados_bioativos/lotus_versao.txt`; ChEMBL: nome do arquivo
  baixado).

---

## 26. Histórico de mudanças

### Versão 3 + gráficos (atual)

| Mudança | Detalhe |
|---|---|
| Gráficos dos resultados | `graficos.py`, com os lançadores `graficos.sh` / `graficos.bat`: cerca de 40 gráficos, da visão geral à etapa 5, num relatório `graficos/relatorio.html`, com a tabela de cada gráfico em `graficos/dados/` (seção 20) |
| Nomes não reconhecidos em destaque | no gráfico *Plantas mais citadas nos artigos*, os nomes `não reconhecido` aparecem em cinza, com legenda, e a tabela do gráfico traz a coluna `situacao_nome` |
| Pipeline inalterado | os gráficos só leem as planilhas e o cache do Llama; nenhum script de `mods/` mudou. O `matplotlib` é instalado no `.venv` pelo próprio `graficos.sh` |

### Versão 3

| Mudança | Detalhe |
|---|---|
| Cinco bases de compostos | além do COCONUT e do NPASS: Dr. Duke (parte da planta, teor, atividades), LOTUS (DOI de cada par) e FooDB (alimento e teor) |
| Novas colunas de síntese | `bases_compostos` (plantas); `bases`, `atividades_duke`, `referencias_lotus` (compostos) |
| Pastas organizadas | `mods/` para os scripts, `config/` para a configuração |
| Linux, Windows e macOS | instaladores com ambiente virtual, lançadores `rodar.sh`/`rodar.bat`, leitura de arquivos salvos no Windows |
| Credenciais | um só `config/credenciais.txt` para todos os sistemas; o pipeline pergunta e abre o arquivo se faltar o login do GBIF |
| Lista de plantas em arquivo | `config/lista_de_plantas.txt` substitui `[taxons]` |
| Descoberta em artigos pela região | só os termos da região buscam; as atividades apenas anotam; contexto vegetal opcional; busca dividida por ano acima de 10 mil artigos |
| Etapa 5 mais rápida | PubChem em lotes; pré-checagem com todas as atividades juntas; plantas lidas pelo Llama antes dos compostos |
| Acompanhamento | `./rodar.sh parcial` (sem internet, em arquivos `*_parcial.csv`) e `./rodar.sh diagnostico` |
| Robustez | gravação atômica das planilhas e das extrações; falhas de rede não viram "nenhum artigo"; cache dos nomes populares do GBIF; espera do GBIF tolerante a falhas passageiras |

### Versão 2

Região como círculo, retângulo ou polígono; todo o controle num só
`input.txt` validado; só plantas e só registros de presença no GBIF; lista
do usuário mais plantas de artigos; nomes conferidos em três bases; busca
por todos os nomes da planta; COCONUT completo; etapa de downloads
separada; ChEMBL pelo InChIKey com estereoisômeros; PubMed julgado pelo
Llama, com tipo de estudo e parte da planta; planilhas por planta, por
composto e combinada.
