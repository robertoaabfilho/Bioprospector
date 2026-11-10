# Pipeline de prospecção de plantas e compostos bioativos

> **Versão 3.20** · roda em Linux, Windows e macOS · Python 3.10+ · modelo local via Ollama (Qwen 3.5)
>
> Você informa uma **região**, uma **lista de plantas** e as **atividades
> biológicas** que interessam. O pipeline devolve planilhas com as plantas, os
> compostos de cada uma e as atividades demonstradas em ensaios e artigos,
> cada resultado com a sua referência. Ao fim, consolida tudo num **banco
> relacional FAIR** (pasta `banco/`): CSVs interligados pelo InChIKey canônico,
> com identidade química, proveniência, bioatividade, vias, espectros e perfil
> ADMET, mais dicionário de dados, `datapackage.json` e análise de qualidade.
> Também gera **gráficos**, reunidos num relatório HTML, e tem um **painel
> interativo** (`./painel.sh`) para filtrar e cruzar os resultados no navegador.

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
17-A. [Etapas 6 a 8: `normalizacao`, `banco` e `qualidade` (banco relacional)](#17-a-etapas-6-a-8-normalizacao-banco-e-qualidade)

**Parte V: Resultados**

18. [Qual arquivo abrir e como ler](#18-qual-arquivo-abrir-e-como-ler)
19. [Mensagens de status nas planilhas](#19-mensagens-de-status-nas-planilhas)
20. [Gráficos dos resultados](#20-gráficos-dos-resultados)
20-A. [Painel interativo (Streamlit)](#20-a-painel-interativo-streamlit)

**Parte VI: Referência**

21. [Caches](#21-caches)
22. [Tempo de execução e escala](#22-tempo-de-execução-e-escala)
23. [Solução de problemas](#23-solução-de-problemas)
24. [Limitações e cuidados na interpretação](#24-limitações-e-cuidados-na-interpretação)
25. [Bases de dados e como citá-las](#25-bases-de-dados-e-como-citá-las)
26. [Como acrescentar uma fonte de dados ao pipeline](#26-como-acrescentar-uma-fonte-de-dados-ao-pipeline)
27. [Histórico de mudanças](#27-histórico-de-mudanças)

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
  citadas em artigos sobre a região, sem o que não é planta e com **uma
  linha por espécie aceita** (conferida em quatro bases taxonômicas). Os
  sinônimos e grafias, inclusive os da sua lista, ficam registrados na
  linha da espécie e são usados nas buscas: nenhum nome se perde;
- a **distribuição no Brasil** de cada planta: estados, domínios
  fitogeográficos, endemismo e origem (Flora e Funga do Brasil; para as que
  ela não cobre, registros do GBIF);
- os **compostos** conhecidos de cada planta, de cinco bases (COCONUT,
  NPASS, Dr. Duke, LOTUS e FooDB), com InChIKey, classe química, parte da
  planta, teor, referências, os estados em que ocorrem e a **estrutura
  (SMILES) de cada fonte**, conferida entre as fontes;
- as **atividades medidas em ensaios** de cada composto (ChEMBL), com o
  valor (IC50, Ki…) e o artigo de origem;
- as **atividades relatadas em artigos** (PubMed) para plantas e
  compostos. Um modelo de linguagem que roda no seu computador (via Ollama) lê cada resumo e mantém **só os que relatam um resultado
  experimental positivo**. Ele anota também o **tipo de estudo** (in vitro,
  in vivo, clínico) e a **parte da planta**;
- **arquivos de evidência**, com PMID, DOI e uma justificativa para cada
  resultado, para você conferir;
- **gráficos** de cada etapa, gerados ao fim das etapas `plantas`,
  `bioativos`, `chembl` e `pubmed`, num relatório
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
                estados de cada espécie no Brasil (GBIF) ───► especies_gbif_estados.csv
                                │
 [2 plantas]    sua lista + GBIF + nomes de artigos
                sem não-plantas (Flora, WFO, WCVP, GBIF)
                uma linha por espécie aceita; estados do Brasil ► plantas.csv
                                │
 ── FASE B: QUAIS COMPOSTOS E ATIVIDADES? ─────────────────────────────────
 [3 bioativos]  compostos de cada planta
                (COCONUT, NPASS, Dr. Duke, LOTUS, FooDB;
                SMILES também do PubChem) ──────────────────► especies_com_compostos_bioativos.csv
                                │
 [4 chembl]     atividades MEDIDAS em ensaios (ChEMBL) ─────► compostos_chembl.csv
                                │
 [5 pubmed]     atividades RELATADAS em artigos
                (PubMed + PubChem, julgadas pelo modelo) ────► atividades_plantas.csv
                                                              atividades_compostos.csv
                                                              especies_atividades.csv
                                                              evidencias_pubmed.csv
                                │
 [gráficos]     ao fim das etapas 2 a 5 (e com ./graficos.sh,
                a qualquer momento) ────────────────────────► graficos/relatorio.html
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
PubMed, cada nome conferido, cada resumo lido pelo modelo é gravado num
arquivo `cache_*.jsonl` **no momento em que termina**. Rodar de novo
reaproveita tudo e só faz o que falta. Na prática:
- interromper **nunca** perde mais do que a consulta em andamento;
- **retomar = rodar o mesmo comando de novo**.

**3. A maior parte do tempo vai para a etapa `pubmed`.** As etapas 0 a 4
levam de minutos a poucas horas. A etapa 5 pode levar **dias**, porque o
modelo lê os resumos um a um. É nela que você vai usar o acompanhamento
(seção 10) e a retomada (seção 11).

**4. Plantas e compostos são identificados por nomes e por estrutura.**
- **Plantas**: todos os nomes da mesma espécie (o aceito, sinônimos e
  grafias, venham da sua lista, do GBIF ou de artigos) viram **uma linha**,
  com o nome aceito em `nome_cientifico`. Os outros nomes ficam em
  `nomes_juntados`, e todos os nomes conhecidos da planta ficam em
  `nomes_busca`, usada nas buscas. Nenhum nome é descartado.
- **Compostos**: são unificados pelo **InChIKey**, um código de 27
  caracteres derivado da estrutura química (ex.:
  `REFJWTPEDVJJIY-UHFFFAOYSA-N` = quercetina). O mesmo composto vindo de
  bases diferentes vira uma linha só.

**5. "Atividade" só conta se for demonstrada.** O modelo só aceita um artigo
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
| **Ollama** + modelo `qwen3.5:35b-a3b` | etapa 5 (leitura dos resumos) | sim, para a etapa 5 |
| **Conta gratuita no GBIF** | etapa 1 (download da região e tabela de estados) | sim, na 1ª vez de cada região |
| Chave gratuita do **NCBI** | PubMed/PubChem cerca de 3× mais rápidos | recomendada |
| Chave gratuita do **OpenAlex** | descoberta de plantas em artigos | recomendada |
| **≈ 6 GB** livres em disco | bases baixadas | sim |
| **≈ 6 GB de memória (RAM)** | etapa `plantas`, que lê as listas taxonômicas inteiras (num teste real com 33 mil nomes da lista e 45 mil do GBIF: 4 minutos e ≈ 4 GB) | sim |
| Placa de vídeo (GPU) com ≈ 24 GB (ou memória unificada) | leitura dos resumos 5 a 10× mais rápida | não, mas faz muita diferença |

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
   `tqdm`, `truststore` e `matplotlib`, este para os gráficos). Nada é
   instalado no Python do sistema. Se a mesma pasta for usada no Windows e
   no Linux, cada sistema fica com o seu ambiente (`.venv-win` /
   `.venv-linux`, seção 11.7);
3. tenta instalar o **RDKit** (opcional), que compara os SMILES das
   diferentes bases (coluna `conferencia_smiles`). Se não instalar, o
   pipeline roda igual, só sem essa conferência;
4. cria `config/input.txt` e `config/credenciais.txt` a partir dos modelos,
   **se ainda não existirem** (nunca sobrescreve os seus);
5. confere se o Ollama e o modelo do `input.txt` estão instalados.

No Windows, o `instalar.bat` usa o lançador `py` quando existe, exige
Python 3.10 ou mais recente e avisa se `python` abrir a Microsoft Store
(atalho falso, desligável em *Configurações → Aplicativos → Aliases de
execução de aplicativo*).

> **Linux (Ubuntu/Debian)**: se o instalador avisar que falta o módulo
> `venv`, rode `sudo apt install python3 python3-venv` e de novo
> `./instalar.sh`.

**Instalação manual**, se preferir:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt     # Windows: .venv\Scripts\python -m pip install -r requirements.txt
cp config/input.txt.exemplo config/input.txt            # Windows: copy config\input.txt.exemplo config\input.txt
```

### 4.3 Ollama e o modelo

O modelo roda **no seu computador**: sem custo e sem enviar os resumos para
fora.

1. Instale o Ollama:
   - **Linux**: `curl -fsSL https://ollama.com/install.sh | sh`. Ele vira um
     serviço do sistema, que inicia sozinho. Confira com
     `systemctl status ollama`; se estiver parado,
     `sudo systemctl start ollama`.
   - **Windows / macOS**: baixe em https://ollama.com/download. Ele fica na
     bandeja do sistema e inicia sozinho.
2. Baixe o modelo (≈ 22 GB): `ollama pull qwen3.5:35b-a3b`
3. Se o Ollama não estiver rodando como serviço, deixe um terminal aberto
   com `ollama serve`.

| Modelo | Memória | Velocidade por resumo | Comentário |
|---|---|---|---|
| `qwen3.5:35b-a3b` | ≈ 22 GB | 1–3 s com GPU (só ~3B parâmetros ativos por resposta) | **recomendado** (padrão): segue bem o formato JSON e distingue "testado" de "demonstrado" |
| `gemma4:26b` | ≈ 16 GB | parecida | alternativa do mesmo nível |
| `qwen3.5:122b-a10b` | ≈ 70 GB | ~3× mais lento | o mais criterioso, para quem tem memória sobrando |
| `llama3.1:8b` | ≈ 5 GB | 1–3 s com GPU; 5–30 s só com CPU | para máquinas modestas; erra mais nos casos sutis |
| modelos de 1B a 4B | — | — | não use: erram muito no julgamento |

O Qwen 3.5 "raciocina" antes de responder se deixarmos; o pipeline desliga
isso (`pensar = false`, seção 7), o que deixa cada resposta várias vezes
mais rápida com perda pequena de qualidade numa tarefa de triagem como esta.
Para trocar de modelo, mude `modelo` em `[ollama]` no **seu**
`config/input.txt` (o valor escrito lá vale mais que o padrão).

**GPU no Linux**: com placa NVIDIA e driver instalado (`nvidia-smi`
funciona), o Ollama usa a placa automaticamente. Durante a etapa 5, rode
`ollama ps`: a coluna `PROCESSOR` deve mostrar `GPU`.

### 4.4 Espaço em disco

| Base | Tamanho aproximado |
|---|---|
| Flora e Funga do Brasil | dezenas de MB |
| World Flora Online (WFO) | ≈ 700 MB |
| WCVP (Kew) | ≈ 100 MB compactado; ≈ 1,5 GB de memória ao ser lido |
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
├── painel.sh    / painel.bat   ← lançadores do painel interativo (seção 20-A)
├── painel.py                   ← painel interativo (Streamlit; só lê as planilhas)
├── requirements.txt            ← pacotes Python
├── .venv/                      ← ambiente Python (criado pelo instalador;
│                                  .venv-win / .venv-linux em pasta compartilhada)
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
    ├── *.csv                   ← resultados (inclui especies_gbif_estados.csv)
    ├── bases_baixadas.txt, diagnostico_pubmed.txt
    └── graficos/               ← criada ao fim das etapas 2 a 5 (ou pelo
                                   ./graficos.sh): relatorio.html, imagens e
                                   dados/ (tabela de cada gráfico)
```

**Módulos auxiliares** (usados pelas etapas, não rodam sozinhos):

| Arquivo | Função |
|---|---|
| `config_pipeline.py` | lê e valida o `input.txt` (`./rodar.sh config` mostra o resultado) |
| `credenciais.py` | lê `config/credenciais.txt`; pergunta e abre o arquivo se faltar o login do GBIF |
| `taxonomia.py` | conferência de nomes (Flora e Funga do Brasil, WFO, WCVP, GBIF) |
| `distribuicao.py` | distribuição por estado (Flora e Funga do Brasil; GBIF para o que ela não cobre) |
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
[artigos] [taxonomia] [ollama] [pubmed] [bioativos] [chembl] [banco]  ← parâmetros
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

**c) `pais` (opcional), para o GBIF.** Restringe o levantamento aos
registros de um ou mais países (código de 2 letras: `BR`, `PE`, `CO`…).
Use quando o polígono passa da fronteira: com `pais = BR`, espécies
registradas só nos países vizinhos ficam de fora. Vazio = todos os
registros dentro da área. Mudar o filtro gera um download novo no GBIF.

```ini
pais = BR
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
- Nenhum nome é filtrado ou descartado. Todos os nomes que são a mesma
  espécie (o aceito, sinônimos e grafias variantes) viram **uma linha**,
  com o nome aceito em `nome_cientifico`; os seus nomes originais ficam em
  `nomes_juntados` e em `nomes_busca`, e continuam sendo usados nas buscas.

### 7.3 `[termos_pubmed]`: atividades de interesse (opcional)

**Vazia** = o pipeline procura **qualquer** atividade biológica.
**Preenchida** = a etapa 5 só busca e só aceita as atividades listadas, e
a etapa 4 só liga ensaios a elas. Na etapa 2 elas não filtram nada: só
anotam quais plantas aparecem em artigos sobre cada atividade (coluna
`atividades_artigos`). Com a seção vazia, a anotação usa o filtro geral de
atividade e aparece como "atividade biológica (geral) (N artigos)".

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
| `corrigir_grafia` | `true` | reconhece grafias variantes do mesmo nome (para anotar o nome aceito e juntar duplicatas; a grafia original fica em `nomes_juntados` e `nomes_busca`) |
| `estados_gbif` | `true` | a etapa `gbif` pede ao GBIF, uma vez, a tabela de espécie × estado (download em SQL), usada para as plantas sem estado na Flora e Funga do Brasil |
| `flora_brasil_url`, `wfo_url` | vazio | endereço alternativo de download (vazio = automático) |

**`[bioativos]`: compostos (etapa 3)**

| Chave | Padrão | Função |
|---|---|---|
| `escopo` | `regiao` | `regiao` = só os compostos das plantas de `plantas.csv` (prospecção de uma área); `completo` = todos os compostos das bases químicas, com as plantas de fora da região marcadas em `na_regiao` (construção do banco publicável). Ver 15.1 |
| `reino` | `vegetal` | reinos aceitos, só com `escopo = completo`: `vegetal` confere o gênero nos gêneros do WFO/WCVP; `qualquer` aceita qualquer organismo (bactérias, fungos, metabólitos humanos). Ver 15.1 |
| `usar_<nome>` | — | uma chave por **fonte de compostos** acrescentada em `mods/fonte_<nome>.py` (seções 17-A.4 e 26) |
| `apenas_com_atividade_npass` | `false` | `true` = só compostos com algum registro de atividade no NPASS |
| `incluir_nao_reconhecidos` | `false` | busca também nomes que nenhuma base taxonômica reconheceu |
| `usar_duke` | `true` | Dr. Duke: parte da planta, teor (ppm) e atividades por composto |
| `usar_lotus` | `true` | LOTUS: referência (DOI) de cada par planta × composto |
| `usar_foodb` | `true` | FooDB: alimento e teor. ⚠️ **Uso comercial exige permissão dos autores** (https://foodb.ca) |
| `smiles_pubchem` | `true` | busca no PubChem o SMILES de todos os compostos com InChIKey: para comparar com as bases (`conferencia_smiles`) e completar os que nenhuma base trouxe com estrutura. Em lotes pelo CID e, sem CID, um a um; em cache |
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

**`[banco]`: banco relacional (etapas 6 a 8)**

| Chave | Padrão | Função |
|---|---|---|
| `pubchem` | `true` | normaliza os identificadores pelo PubChem (CID, InChI, SMILES, propriedades, sinônimos). `false` usa só o que já estiver em cache |
| `max_sinonimos` | `25` | sinônimos por composto em `compounds_synonyms.csv` (0 = nenhum do PubChem) |
| `classyfire` | `faltantes` | `faltantes` = consulta a API do ClassyFire só para os compostos sem classe no COCONUT; `todos` = consulta todos (e registra divergências); `nao` = só o COCONUT |
| `classyfire_submeter` | `true` | envia ao ClassyFire as estruturas que ele ainda não classificou e aguarda. Produto natural raro muitas vezes não está na base dele: sem isto, esses compostos ficam sem classe, o que reduz a cobertura da classificação e a informação da análise de espaço químico. É lento, e o que não terminar é recolhido na rodada seguinte |
| `vias_pubchem` | `true` | busca vias metabólicas/de sinalização no PubChem (`compounds_pathways.csv`) |
| `espectros_teoricos` | `true` | m/z teóricos dos adutos mais comuns (RDKit, sem internet) em `compounds_spectra.csv` |
| `espectros_pubchem` | `true` | espectros experimentais compilados no PubChem (`compounds_spectra.csv`) |
| `espectros_<nome>` | — | uma chave por **fonte de espectros** acrescentada em `mods/espectros_<nome>.py` (seções 17-A.4 e 26) |
| `umap` | `true` | projeção UMAP dos fingerprints Morgan na etapa `qualidade` (precisa de `pip install umap-learn`) |
| `umap_max` | `50000` | teto de compostos na projeção; acima disso, amostra aleatória com semente fixa |
| `admet_ai` | `false` | acrescenta previsões do pacote `admet-ai` (rede neural; pesado) às colunas `admetai_*` de `compounds_druglikeness_admet.csv` |
| `idioma_banco` | `en` | idioma dos **nomes** de `banco/` (arquivos, colunas e a chave `compound_uid`). `pt` devolve os nomes em português. As planilhas da raiz seguem em português nos dois casos |
| `enriquecer_apenas_regiao` | `true` | as consultas de **um pedido por composto** (sinônimos e ClassyFire pela API, vias e espectros do PubChem) só para os compostos que ocorrem em alguma planta da região. É o que mantém a etapa viável com `escopo = completo`; os de fora ficam com o PubChem em lote e a classificação do COCONUT |
| `incluir_pubmed` | `true` | inclui os relatos do PubMed (etapa 5) em `compounds_bioactivity.csv` |

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
| `modelo` | `qwen3.5:35b-a3b` | modelo que julga os resumos (alternativas na seção 4.3) |
| `url` | `http://localhost:11434` | endereço do Ollama |
| `timeout_segundos` | `180` | tempo máximo por resumo |
| `pensar` | `false` | modelos com "raciocínio" (Qwen 3.5/3.6, gpt-oss, alguns Gemma) pensam antes de responder: bem mais lento. `false` pede ao Ollama para desligar; modelos sem raciocínio (ex.: llama3.1) não são afetados |
| `paralelo` | `4` | quantos resumos o modelo lê ao mesmo tempo (1 = um de cada vez). Com GPU, 4 costuma dar 2 a 3× mais resumos por hora; o Ollama precisa aceitar pedidos simultâneos (`OLLAMA_NUM_PARALLEL`, seção 17) |

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
| `./rodar.sh --gbif-chave CHAVE` | usa um download do GBIF já feito em vez de pedir um novo (seção 13) |
| `./rodar.sh --sem-graficos` | não gera os gráficos ao fim das etapas (seção 20) |
| `./rodar.sh --input outro.txt` | usa outro arquivo de configuração. O caminho pode ser relativo à pasta onde você está, à raiz do projeto ou a `config/`. A `lista_de_plantas.txt` é procurada na mesma pasta desse arquivo |

`ETAPA` é um destes: `downloads`, `gbif`, `plantas`, `bioativos`, `chembl`,
`pubmed`.

As opções se combinam. Exemplo: `./rodar.sh --a-partir-de bioativos
--pular-downloads`. No Windows, use `rodar.bat` com as mesmas opções.

### 9.2 Comandos auxiliares

| Comando | Efeito |
|---|---|
| `./rodar.sh config` | mostra como o `input.txt` foi entendido; não roda nada |
| `./rodar.sh credenciais` | mostra o sistema e a situação das credenciais; se faltar o login do GBIF, pergunta e abre o arquivo |
| `./rodar.sh diagnostico` | resumo do andamento da etapa 5 → `diagnostico_pubmed.txt` (seção 10.3) |
| `./rodar.sh parcial` | planilhas da etapa 5 com o que o modelo já leu → arquivos `*_parcial.csv` (seção 10.3) |
| `./graficos.sh` | gráficos de todas as etapas já concluídas → `graficos/relatorio.html` (seção 20) |
| `./graficos.sh --parcial` | idem, com a etapa 5 lida dos `*_parcial.csv` |
| `./painel.sh` | painel interativo no navegador (`http://localhost:8501`): filtros, prospecção e fichas (seção 20-A) |

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
ETAPA [pubmed]: Atividades relatadas no PubMed, filtradas pelo modelo
======================================================================
PubChem: consultando 1520 composto(s) (48210 já em cache)...
PubChem (em lote): 100%|██████████| 8/8 [00:21<00:00,  2.6s/it]
Pré-checagem: 2900 planta(s)/composto(s) - uma busca com todas as 7 atividades juntas ...
PubMed esearch:  45%|████▌     | 1302/2890 [09:41<11:48,  2.2it/s]
...
Modelo (qwen3.5:35b-a3b): 19104 par(es) entidade x artigo a classificar (2015 em cache)
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
| `gbif` | chave do pedido e o link `gbif.org/occurrence/download/...` (dá para acompanhar no site); `status: PREPARING / RUNNING / SUCCEEDED` a cada 30 s; no fim, o pedido em SQL dos estados (só na 1ª vez) |
| `plantas` | número de artigos encontrados por base; barra de conferência dos nomes; contagem por fonte e por situação do nome; "N de M plantas com estado(s): … pela Flora, … pelo GBIF" |
| `bioativos` | quantos táxons e pares planta × composto vieram de cada base; "SMILES do PubChem: …"; "Conferência dos SMILES …"; "SMILES: N de M compostos; origem: …" |
| `chembl` | quantos compostos foram achados (exatos e estereoisômeros) e quantos têm atividade |
| `pubmed` | barras do PubChem, das buscas, do download de resumos e, a mais longa, **Classificando** (modelo) |

### 10.3 Acompanhando a etapa 5 sem interromper

A leitura pelo modelo pode levar dias. Duas ferramentas mostram o andamento
**sem atrapalhar a rodada principal**. Abra **outro terminal**, na mesma
pasta:

**`./rodar.sh parcial`** (Windows: `rodar.bat parcial`): gera as planilhas
com o que o modelo **já leu**.
- Não acessa a internet e não lê nenhum artigo novo: usa só os caches.
- Grava em arquivos separados, para não confundir com o resultado final:
  `atividades_plantas_parcial.csv`, `atividades_compostos_parcial.csv`,
  `especies_atividades_parcial.csv`, `evidencias_pubmed_parcial.csv`.
- O que ainda não foi lido aparece como `artigos encontrados; leitura pelo
  modelo pendente`.
- Pode rodar quantas vezes quiser. Os `*_parcial.csv` podem ser apagados
  quando a rodada principal terminar.
- **Para ver em gráficos**: depois do `parcial`, rode
  `./graficos.sh --parcial` (seção 20). O gráfico *Julgamentos do modelo*
  mostra quantos resumos já foram lidos e quantos deram positivo.

**`./rodar.sh diagnostico`**: grava `diagnostico_pubmed.txt` (alguns KB),
um resumo dos caches: quantas buscas foram feitas e quantas vieram vazias,
quantos resumos foram baixados, quantos pares o modelo já julgou e quantos
deram positivo. É o arquivo a mandar para alguém analisar o andamento, no
lugar dos caches, que podem ter centenas de MB.

**Contagens rápidas** (cada linha de um cache = uma consulta concluída):

```bash
wc -l cache_llm_classificacao.jsonl      # resumos já julgados pelo modelo
wc -l cache_pubmed_buscas.jsonl          # buscas no PubMed já feitas
```
No Windows (PowerShell): `(Get-Content cache_llm_classificacao.jsonl).Count`

**O modelo está usando a GPU?** `ollama ps` → a coluna `PROCESSOR` deve
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
| coordenadas ou `pais` de `[regiao]` | `gbif` | um download novo no GBIF (precisa de login) e tudo o que depende das plantas novas |
| `termos_texto`, `[artigos]` | `plantas` | a descoberta em artigos com os termos novos |
| sua lista (`lista_de_plantas.txt` ou `[taxons]`), `[taxonomia]` | `plantas` | só os nomes novos são conferidos (ligar `estados_gbif`: rode antes `--somente gbif`) |
| `[termos_pubmed]` | `plantas` | anotação das atividades nos artigos (etapa 2), ligação dos ensaios (etapa 4) e buscas por atividade (etapa 5) |
| `[bioativos]` | `bioativos` | o cruzamento com as bases (minutos) |
| `[chembl]` | `chembl` | só o que a opção afeta |
| `[pubmed]` | `pubmed` | só as buscas novas (mudar `max_artigos_por_*` refaz as buscas, porque o limite faz parte da consulta) |
| `[ollama] modelo` | `pubmed` | **todos os julgamentos do modelo**: o modelo faz parte da chave do cache (demorado) |

### 11.5 Refazer só uma parte, apagando um cache

Às vezes você quer forçar uma consulta nova: buscar artigos publicados
depois da última rodada, reconferir nomes. Para isso, apague o cache
correspondente (tabela completa na seção 21) e rode a etapa de novo.

| Quero… | Apague | E rode |
|---|---|---|
| buscar artigos publicados desde a última rodada | `cache_pubmed_buscas.jsonl`, `cache_pubchem_vinculos.jsonl`, `cache_pubmed_filtro.jsonl` | `--a-partir-de pubmed` |
| refazer a descoberta de plantas em artigos | `cache_openalex.jsonl` e `cache_pubmed_buscas.jsonl` | `--a-partir-de plantas` |
| reconferir todos os nomes | `cache_taxonomia_*.jsonl` | `--a-partir-de plantas` |
| fazer o modelo reler todos os resumos | `cache_llm_classificacao.jsonl` ⚠️ | `--a-partir-de pubmed` |
| atualizar os dados do ChEMBL | `cache_chembl_*.jsonl` (ou use `--atualizar-bases`) | `--a-partir-de chembl` |
| um download novo do GBIF para a mesma região | `dados_gbif_download/pedidos.json` | `--a-partir-de gbif` |

> ⚠️ **`cache_llm_classificacao.jsonl` guarda dias de trabalho do modelo.**
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
pesquisa realmente nova, sem reaproveitar nada da internet nem do modelo.

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
   instalador. Se a MESMA pasta for usada pelos dois sistemas (disco
   compartilhado, dual boot), cada um fica com o seu ambiente: o
   `instalar.sh` cria `.venv-linux` quando a `.venv` é do Windows, e o
   `instalar.bat` cria `.venv-win` quando ela é do Linux. Os lançadores
   escolhem o certo sozinhos;
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
| WCVP, World Checklist of Vascular Plants (Kew; ≈ 100 MB) | 2 | `dados_wcvp/wcvp.zip` |
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
| Internet | API de downloads do GBIF (inclusive downloads em SQL) |

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
   ocorrências (guardado em cache). Se o GBIF parar de responder, essa
   busca é interrompida depois de 20 falhas seguidas e retomada na próxima
   rodada.
5. Com `estados_gbif = true` (`[taxonomia]`, padrão), faz **um segundo
   pedido, em SQL**, só na primeira vez: uma tabela já agregada com o
   número de registros de cada espécie de planta em cada **estado
   brasileiro** (todo o Brasil, não só a região; registros com coordenada,
   sem problema geoespacial; o estado vem das coordenadas, divisão GADM).
   É usada na etapa `plantas` para as plantas sem estado na Flora e Funga
   do Brasil. O download em SQL é um recurso **experimental** do GBIF: se
   ele falhar (ou faltarem as credenciais), a etapa avisa e segue.

Se o GBIF demorar ou responder "503", a etapa espera até 5 min, confere se
o pedido foi criado mesmo assim (para não abrir pedidos duplicados) e
tenta de novo.

**Reaproveitamento**: a chave de cada pedido fica em
`dados_gbif_download/pedidos.json`. Rodar de novo com a **mesma região**
reaproveita o download, sem gastar cota nem esperar a fila. Para usar um
download que você já fez (por exemplo, sem o filtro de países atual), use
`--gbif-chave` com a chave dele: `./rodar.sh --somente gbif --gbif-chave
0021558-261023074918325` (Windows: `rodar.bat --somente gbif --gbif-chave
0021558-261023074918325`). Se o zip desse download já estiver em
`dados_gbif_download/`, o GBIF nem é consultado.

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

`especies_gbif_estados.csv` (com `estados_gbif = true`): uma linha por
espécie × estado brasileiro, com `speciesKey`, `especie`, `uf` e
`n_registros` (registros georreferenciados de plantas em todo o Brasil, não
só na região). Vem de um segundo pedido, em SQL, feito uma vez e
reaproveitado nas rodadas seguintes; serve à distribuição por estado da
etapa `plantas`.

Também: `dados_gbif_download/` (pedidos, zip e dados extraídos, cache dos
nomes populares).

**Retomada**: se a espera for interrompida, a próxima rodada reaproveita o
mesmo pedido (a chave já foi registrada).

---

## 14. Etapa 2: `plantas`

`mods/montar_lista_plantas.py` → `plantas.csv`

**Objetivo**: montar a **lista final de plantas**, sem duplicatas, antes de
qualquer busca de compostos ou atividades.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivos | `config/lista_de_plantas.txt` (ou `[taxons]`); `especies_gbif.csv` e `especies_gbif_estados.csv` (etapa 1) |
| Bases locais | Flora e Funga do Brasil, WFO e WCVP (etapa 0) |
| Configuração | `[regiao] termos_texto`; `[termos_pubmed]` (só para anotar); `[artigos]`; `[taxonomia]` |
| Internet | PubMed, OpenAlex, API do GBIF |

**Como funciona**, em quatro passos:

**a) Três fontes de nomes**

| Fonte | O que entra | Tratamento |
|---|---|---|
| `lista` | a sua lista | **nunca filtrada**: nenhum nome é descartado. Nomes que são a mesma espécie (sinônimos, grafias) são juntados na linha do nome aceito (passo d) |
| `gbif` | plantas com ocorrência na região (etapa 1) | passam pela conferência (passo b) |
| `artigos` | nomes científicos citados em artigos que mencionam a região | passam pelo filtro (passo c) |

A **descoberta em artigos** busca no PubMed e no OpenAlex os artigos cujo
título ou resumo cita **um termo da região** (`termos_texto`), seja qual
for o tema, até `max_artigos` em cada base. Os nomes científicos citados
(inclusive em itálico e abreviados, como *E. oleracea*) são extraídos do
texto.
- **As atividades não filtram a busca.** Quando um artigo cita um termo de
  uma atividade de `[termos_pubmed]`, as plantas dele recebem a anotação na
  coluna `atividades_artigos` (ex.: `clareadora (3 artigos)`).
- **OpenAlex conferido no texto**: cada trabalho só fica se o título ou o
  resumo citar um termo da região.
- **`contexto_vegetal = true`** exige também uma palavra como *plant*,
  *extract* ou *bark*.

**b) Conferência em quatro bases.** Todo nome, de qualquer fonte, é
conferido em quatro bases. O nome original nunca se perde: ele fica em
`nomes_juntados`/`nomes_busca` da linha da espécie:

| Prioridade | Base | Cobre | Como |
|---|---|---|---|
| 1 | Flora e Funga do Brasil (JBRJ) | flora do Brasil, inclusive briófitas e algas | arquivo local |
| 2 | World Flora Online (WFO) | plantas do mundo: vasculares e briófitas | arquivo local |
| 3 | WCVP (Kew) | plantas vasculares do mundo | arquivo local |
| 4 | GBIF | todos os organismos (diz se o nome é de planta) | API, um nome por vez |

A conferência serve para três coisas:
1. anotar o **nome aceito** (coluna `nome_aceito`) e a **situação** do nome
   como ele está (`aceito`, `sinônimo`, `grafia variante`…);
2. reunir **todos os nomes conhecidos** da planta em `nomes_busca`: o
   original, o aceito, as grafias, as variedades e subespécies, os nomes
   juntados e **os sinônimos que a Flora, o WFO e o WCVP conhecem** para o
   nome aceito, mesmo que nenhuma fonte os tenha citado (até 30 por espécie;
   em média ficam 4 ou 5 nomes por planta). Sinônimos **ambíguos** (o mesmo
   nome apontando para duas espécies, como o homônimo *Schedonorus
   arundinaceus*) ficam de fora. As etapas 3 e 5 procuram compostos e
   artigos por todos esses nomes, então um composto registrado sob um
   sinônimo antigo (ex.: *Inga affinis* no Dr. Duke, para *Inga vera*) não
   se perde;
3. identificar o que **não é planta** (passo c) e as **duplicatas** (passo d).

Regras da conferência:
- **A resposta mais confiável decide.** Um nome encontrado **exatamente**
  em qualquer base vale mais que uma grafia aproximada de outra base. Entre
  respostas do mesmo tipo, vale a prioridade da tabela. A divergência fica
  anotada.
- **Grafia variante só quando é mesmo a mesma palavra.** Só os epítetos são
  comparados (o gênero igual inflaria a semelhança). Contam como grafia do
  mesmo nome:
  - as variantes que o Código de Nomenclatura trata como iguais
    (*artemisiaefolia*/*artemisiifolia*, *glazioui*/*glaziovii*,
    *flavo-virens*/*flavovirens*);
  - outra terminação (*guianense*/*guianensis*);
  - uma letra trocada, a mais, a menos ou duas letras invertidas
    (*speciosas*, *aspiliodies*).

  Diferenças maiores são outra espécie e não contam (*Linum bahiense* ≠ *L.
  bahamense*; *Ilex rugulosa* ≠ *I. rugosa*); o nome parecido aparece só como
  sugestão em `observacoes_taxonomia`. A mesma regra vale para as respostas
  aproximadas do GBIF.
- **Homônimos.** O mesmo nome, de autores diferentes, pode ser sinônimo de
  espécies diferentes (*Schedonorus arundinaceus* é sinônimo de *Lolium
  arundinaceum*, mas um homônimo é sinônimo de *Scolochloa festucacea*). Vale
  o destino de **mesmo epíteto**; se não houver um só, o nome fica como
  `homônimo ambíguo`, e as opções vão para a observação. Nomes "mal
  aplicados" (*misapplied*, no WCVP) não são tratados como sinônimos.
- **Família e classificação.** A família vem da base que identificou a
  espécie (Flora, WFO ou WCVP); o GBIF só a fornece quando as outras não
  têm. Filo, classe, ordem e `speciesKey` vêm do GBIF **só se o GBIF puser a
  planta na mesma família**. Se não puser, quase sempre é um homônimo de
  outro reino (ex.: *Pleroma*, gênero de plantas e de insetos, que o GBIF
  pode classificar em Kinnaridae); esses campos ficam vazios, com aviso.

**c) O que não é planta sai da lista** (só nomes do GBIF e dos artigos; a
sua lista nunca é filtrada). Dois filtros, ambos pelas bases taxonômicas:
1. **O gênero precisa existir** na Flora, no WFO ou no WCVP. Isso elimina,
   sem nenhuma consulta pela internet, os pares de palavras que só
   *parecem* nomes científicos: "This paper", "Esse artigo", "Birth cohort",
   "Desenvolver uma".
2. **O nome precisa ser reconhecido como planta** por ao menos uma das
   quatro bases. Isso elimina outros organismos, inclusive nos gêneros que
   também existem em plantas (*Solenopsis geminata*, uma formiga; o GBIF
   recusa nomes de outros reinos), e expressões como "Eucalyptus
   branches".

Também saem os registros do GBIF ou dos artigos **só de gênero** (ex.:
*Psychotria*, sem espécie). Os nomes que saíram e o motivo ficam em
`plantas_descartados.csv`.

**d) Uma linha por espécie, sem duplicatas.**
- **Só gênero + epíteto em `nome_cientifico`.** Variedades e subespécies
  entram na linha da espécie, e o nome completo delas vai para
  `nomes_busca`. Exemplo: *Erythroxylum coca* var. *ipadu* e *Erythroxylum
  coca* (os dois na sua lista) viram **uma** linha *Erythroxylum coca*, com
  `nomes_busca = Erythroxylum coca; Erythroxylum coca var. ipadu`. O sinal
  de híbrido é mantido (*Citrus × limon*).
- Todos os nomes que levam à **mesma espécie aceita** (o aceito, sinônimos
  e grafias variantes), venham da sua lista, do GBIF ou dos artigos, viram
  **uma linha só**.
- `nome_cientifico` dessa linha é o **nome aceito** (gênero + epíteto),
  mesmo que nenhuma fonte o tenha trazido; nesse caso, `situacao_nome =
  aceito (nas fontes só sinônimo ou grafia variante)`.
- Os outros nomes ficam em `nomes_juntados`; `nomes_busca` tem todos (o
  aceito, os juntados e os sinônimos das bases), e é por ela que as etapas
  seguintes procuram compostos e artigos. Nenhum nome é descartado.

Exemplo: *Lippia candicans*, *L. elegans* e *L. salviaefolia* (sua lista) e
*Lippia origanoides* (GBIF) viram a linha *Lippia origanoides*, com
`nomes_juntados = Lippia candicans; Lippia elegans; Lippia salviaefolia`.
Homônimos ambíguos e nomes não reconhecidos nunca são juntados a outros.

**e) Complementos.** Para as plantas da lista e dos artigos, o GBIF fornece
também o número de ocorrências na área e o nome popular, só como
informação. No fim, a tela mostra em quantas espécies o `speciesKey` foi
preenchido. Com sinônimos juntados, `speciesKey` e classificação vêm do
próprio nome aceito.

**f) Distribuição no Brasil.** Para cada linha (sem internet):
1. **Flora e Funga do Brasil** (o arquivo já baixado), procurando o nome
   da linha, o nome aceito e os sinônimos de `nomes_busca`; espécies somam
   as variedades e subespécies; linhas de gênero recebem a união das
   espécies; um sinônimo que aponta para mais de uma espécie é ignorado.
   Dá `estados_br`, `dominios_br`, `endemismo_br` e `origem_br`.
2. Para as que ficaram sem estado: **GBIF** (`especies_gbif_estados.csv`,
   etapa 1), pela `speciesKey` ou pelo nome, com os registros por estado em
   `registros_gbif_por_uf`.
3. Sem nada: `distribuição desconhecida`. Quando a Flora registra a planta
   só como "Brasil", sem estado, os estados ficam desconhecidos, mas o
   domínio, o endemismo e a origem são mantidos.

A Flora tem prioridade: o GBIF nunca muda os estados de uma planta que ela
cobre. `fonte_distribuicao` diz de onde veio cada distribuição.

**Saídas**

**`plantas.csv`**: uma linha por espécie; primeiro as da sua lista, depois
por número de ocorrências.

| Coluna | Conteúdo |
|---|---|
| `speciesKey` | identificador no GBIF (texto: numérico no backbone antigo, alfanumérico no novo, ex.: `549R6`) |
| `reino`, `filo`, `classe`, `ordem`, `familia` | taxonomia |
| `nome_cientifico` | só **gênero + epíteto**, como está na fonte (o seu, se veio da sua lista); usado como nome da planta em todas as etapas seguintes |
| `nome_aceito` | nome aceito segundo as bases (vazio se nenhuma reconhece o nome) |
| `nome_popular_pt` | nome popular em português |
| `categoria_taxonomica` | `SPECIES` (variedades e subespécies ficam na linha da espécie) |
| `n_ocorrencias_na_area` | registros do GBIF dentro da região |
| `estados_br` | estados brasileiros de ocorrência (siglas: `AM; PA; RR`), segundo a Flora e Funga do Brasil; `distribuição desconhecida` quando a planta não consta da Flora ou ela registra só "Brasil". Linhas de gênero: união das espécies do gênero |
| `dominios_br` | domínios fitogeográficos (Amazônia, Caatinga, Cerrado, Mata Atlântica, Pampa, Pantanal) |
| `endemismo_br` | `endêmica do Brasil` ou `não endêmica` |
| `origem_br` | `nativa` ou `exótica` (cultivada ou naturalizada) |
| `fonte_distribuicao` | de onde veio a distribuição (`Flora e Funga do Brasil` ou `GBIF (registros georreferenciados no Brasil)`) e, se não foi pelo nome da linha, por qual nome |
| `registros_gbif_por_uf` | só quando o estado veio do GBIF: registros por estado (ex.: `AM 12; PA 3`). Poucos registros num estado pedem cautela (identificação errada, planta cultivada) |
| `nomes_juntados` | outros nomes da mesma espécie que foram juntados nesta linha |
| `situacao_nome` | situação do nome em `nome_cientifico`: `aceito`, `aceito (sem status confirmado)`, `sinônimo`, `grafia variante`, `grafia variante de sinônimo`, `homônimo ambíguo`, `gênero` ou `não reconhecido nas bases (mantido: está na sua lista)`. Os nomes da sua lista são pesquisados nas etapas seguintes em qualquer situação |
| `nomes_busca` | **todos** os nomes da planta, separados por `;`: o científico, o aceito, grafias, variedades, nomes juntados e sinônimos das listas taxonômicas. As etapas 3 e 5 buscam por todos |
| `observacoes_taxonomia` | o que cada base disse, divergências, sugestões de grafia, avisos |
| `fonte` | `lista`, `gbif`, `artigos` ou combinações (ex.: `lista; gbif`) |
| `atividades_artigos` | atividades do input citadas nos artigos da descoberta, ex.: `clareadora (3 artigos)` |

**`plantas_conferencia_taxonomica.csv`**: um nome original por linha, para
conferir as decisões. Colunas: `nome`, `fonte`, `situacao`, `nome_aceito`,
`linha_em_plantas_csv` (em que linha de `plantas.csv` ele ficou),
`veredito_flora`, `veredito_wfo`, `veredito_wcvp`, `veredito_gbif`.

**`plantas_descartados.csv`**: os nomes do GBIF e dos artigos que ficaram
fora por não serem plantas. Colunas: `nome`, `fonte`, `motivo`,
`n_artigos`, `exemplo_referencia`. Vale uma olhada: se uma planta de
verdade aparecer aqui (por um erro de grafia no artigo), acrescente o nome
correto à sua lista.

**`plantas_artigos_evidencias.csv`**: uma linha por planta × artigo da
descoberta (só das plantas que ficaram). Colunas: `nome_no_artigo`,
`linha_em_plantas_csv`, `atividades_no_texto`, `base`, `referencia` (PMID
ou id do OpenAlex), `ano`, `titulo`, `doi`.

**Retomada**: caches `cache_taxonomia_*.jsonl` (nomes, uma por base), `cache_gbif_extras.jsonl` (ocorrências e
nomes populares), `cache_openalex.jsonl` e `cache_pubmed_*.jsonl`
(artigos). Com listas muito grandes, a primeira rodada pode levar horas
(seção 22), mas pode ser interrompida e retomada à vontade.

---

## 15. Etapa 3: `bioativos`

`mods/cruzar_especies_bioativos.py` → `especies_com_compostos_bioativos.csv`

**Objetivo**: encontrar os **compostos já registrados** para cada planta.

### 15.1 Dois escopos: prospecção de uma área ou banco publicável

A chave `escopo` em `[bioativos]` decide o que entra nesta etapa — e, por
consequência, no banco das etapas 6 a 8.

| | `escopo = regiao` (padrão) | `escopo = completo` |
|---|---|---|
| O que entra | só os compostos das plantas de `plantas.csv` | os compostos de **todas** as plantas das bases químicas |
| Para quê | prospecção de uma região: quais compostos as plantas da sua área têm | banco publicável: cobertura do espaço químico, sobreposição entre bases e viés de curadoria |
| Plantas de fora da região | não entram | entram, com `na_regiao = não`, `estados_br = fora da região` e sem domínios/endemismo |
| Tamanho da saída | milhares de linhas | centenas de milhares |

Por padrão só entram organismos **vegetais**. No escopo `completo`, o reino de
cada organismo das bases químicas é conferido nos **gêneros do WFO e do WCVP**
(as duas listas mundiais de plantas, já baixadas e consultadas no próprio
computador, sem internet). A Flora e Funga do Brasil fica de fora desse teste
de propósito: ela também cataloga fungos e algas. Sem nenhuma das duas listas a
etapa avisa e volta ao escopo `regiao` — rode a etapa `downloads` para
baixá-las.

Quem quiser um banco de outro reino usa `[bioativos]` `reino = qualquer`, que
dispensa essa conferência e aceita bactérias, fungos e metabólitos humanos. É o
que uma base como o NPAtlas ou o HMDB precisa (seções 17-A.4 e 26).
No escopo `regiao` a chave não tem efeito, porque ali os organismos são casados
contra o `plantas.csv`, que já é só de plantas.

> **O que o escopo `completo` NÃO muda.** A etapa 5 (`pubmed`) continua lendo só
> as plantas e os compostos da região: a leitura dos resumos é a fase mais lenta
> do pipeline e sobre as bases inteiras não terminaria em tempo útil. As
> consultas de um pedido por composto ao PubChem também seguem restritas à
> região (`[banco] enriquecer_apenas_regiao`). E os **gráficos** retratam só a
> região. Quem quiser a triagem de uma planta de fora põe o nome dela na lista
> do `input.txt`: aí ela passa a ser da região.
>
> O escopo `completo` carrega os gêneros do WFO e do WCVP, o que usa alguns GB de
> memória a mais por alguns minutos.

**Entradas**

| Tipo | O quê |
|---|---|
| Arquivo | `plantas.csv` (etapa 2) |
| Bases locais | COCONUT, NPASS, Dr. Duke, LOTUS, FooDB (etapa 0) |
| Configuração | `[bioativos]`; `[termos_pubmed]` (para filtrar as atividades do Dr. Duke) |
| Internet | PubChem: InChIKey dos compostos do Dr. Duke e do FooDB que não o têm e, com `smiles_pubchem = true`, o SMILES de todos os compostos com InChIKey (1ª rodada; depois, cache) |

**Como funciona**

| Base | O que acrescenta |
|---|---|
| **COCONUT** | compostos, organismos de origem, SMILES, InChIKey, classificação química, semelhança com fármacos |
| **NPASS 3.0** | pares composto–espécie, nomes, estruturas e **atividades e alvos medidos** |
| **Dr. Duke** (USDA) | **parte da planta**, **teor (ppm)** e **atividades** atribuídas a cada composto na literatura |
| **LOTUS** | **referência (DOI)** do artigo que relata cada par composto × planta (o COCONUT já inclui os pares do LOTUS, mas sem a referência); também o SMILES, o nome e o CID dos compostos que o COCONUT e o NPASS não têm |
| **FooDB** | para plantas **alimentícias**: o alimento e o **teor** |

**Como os nomes são casados.** A busca usa **só a coluna `nomes_busca`** de
`plantas.csv`, onde a etapa `plantas` põe todos os nomes de cada planta (o
científico, o aceito, sinônimos e grafias). Regras:
- os nomes são comparados sem autor, "cf.", "aff." e "×"
  (*Schedonorus arundinaceus (Schreb.) Dumort.* casa com *Schedonorus
  arundinaceus*), e **com** a variedade ou subespécie, quando houver;
- os compostos são salvos **por espécie**: um composto registrado para uma
  variedade ou subespécie vai para a linha da espécie, esteja a variedade
  em `nomes_busca` ou não. Exemplo: 5 compostos registrados para
  *Erythroxylum coca* var. *ipadu* e 5 para *Erythroxylum coca* dão 10
  linhas *Erythroxylum coca* (um composto registrado nos dois vira uma linha
  só); `especie_normalizada` mostra sob qual nome cada um foi achado;
- sinônimos da mesma espécie já estão numa linha só (etapa 2). Exemplo:
  *Schedonorus arundinaceus* e *Festuca arundinacea*, as duas na sua lista,
  ficam na linha *Lolium arundinaceum*; um composto registrado sob qualquer
  dos três nomes vai para essa linha, uma vez só. Se um nome estiver em mais
  de uma linha (homônimos ambíguos), o composto vai para todas elas;
- o mesmo composto achado por dois nomes da mesma planta (ex.: o científico
  e um sinônimo), ou vindo de várias bases, vira **uma linha**, unificada
  pelo InChIKey (`base = COCONUT; DUKE; LOTUS`). A coluna
  `especie_normalizada` mostra sob que nome(s) ele está nas bases.
- O Dr. Duke só traz o nome do composto (ex.: `CAFFEIC-ACID`). O InChIKey é
  obtido no PubChem, pelo nº CAS ou pelo nome, e guardado em
  `cache_pubchem_duke.jsonl`. O FooDB usa o mesmo mecanismo para os poucos
  compostos sem InChIKey.
- Plantas `não reconhecido` não são buscadas (`incluir_nao_reconhecidos`).
- Gêneros: ver seção 7.2.
- Se uma base complementar (Dr. Duke, LOTUS, FooDB) não puder ser lida, a
  etapa segue sem ela, com aviso.

**Estrutura (SMILES).** Cada fonte tem a sua coluna (`smiles_npass`,
`smiles_coconut`, `smiles_lotus`, `smiles_pubchem`), preenchida pelo
InChIKey para todas as linhas do composto. O PubChem é consultado para
todos os compostos com InChIKey (`smiles_pubchem = true`): em lotes de 200
pelo CID, conferindo que o InChIKey devolvido é o do composto (um CID de
outra forma da molécula é descartado), e, sem CID, um a um pelo InChIKey.
O **SMILES escolhido** (`composto_smiles`) é o mesmo em todas as linhas do
composto, na ordem NPASS > COCONUT > LOTUS > PubChem, pulando os inválidos;
`fonte_smiles` diz de qual veio. Com o RDKit, `conferencia_smiles` compara
as **estruturas** das fontes (não o texto): `mesma molécula`,
`estereoquímica diferente: …`, `estruturas diferentes: …` (as fontes que
concordam ficam juntas, ex.: `NPASS/PubChem x COCONUT`) e
`SMILES inválido: …`. Os compostos sem nenhuma estrutura são, em geral,
do Dr. Duke sem InChIKey (nomes genéricos ou de misturas).

**Estados.** Cada linha recebe os estados da planta (`estados_br`, de
`plantas.csv`) e os do composto (`estados_composto`): a união dos estados
de todas as plantas da lista em que ele ocorre.

**Saída**

`especies_com_compostos_bioativos.csv`: uma linha por **composto ×
planta**, ordenada pelo nome do composto.

| Coluna | Conteúdo |
|---|---|
| `composto_nome` | nome do composto |
| `composto_id` | identificador(es) nas bases (`CNP…` COCONUT, `NPC…` NPASS, `DUKE:…`, `LOTUS:…`, `FOODB:…`) |
| `composto_inchikey` | InChIKey |
| `especie_normalizada` | nome(s) sob o qual o composto está registrado nas bases químicas, normalizado (ex.: `lolium arundinaceum; schedonorus arundinaceus`) |
| `base` | base(s) em que o par foi encontrado |
| `atividade_ou_alvo` | alvos e tipos de medida do NPASS |
| `nome_cientifico`, `reino`, `familia`, `nome_popular_pt`, `fonte` | dados da planta (de `plantas.csv`) |
| `na_regiao` | `sim` = a planta é da sua região/lista; `não` = veio das bases químicas, de fora da região (só com `escopo = completo`; ver 15.1) |
| `estados_br` | estados de ocorrência da planta (de `plantas.csv`); `fora da região` nas plantas de fora |
| `estados_composto` | estados de ocorrência do **composto**: união dos estados de todas as plantas da lista em que ele ocorre; `distribuição desconhecida` se nenhuma delas tem estado conhecido; `fora da região` se ele só ocorre em plantas de fora da região |
| `pubchem_cid` | identificador no PubChem |
| `composto_smiles` | estrutura (SMILES). Prioridade: COCONUT e NPASS; os compostos que eles não têm recebem o do LOTUS e, se ainda faltar, o do PubChem |
| `fonte_smiles` | de onde veio o SMILES: `COCONUT`, `NPASS`, `LOTUS` ou `PubChem` (vazio = sem estrutura; em geral, compostos do Dr. Duke sem InChIKey) |
| `smiles_npass`, `smiles_coconut`, `smiles_lotus`, `smiles_pubchem` | o SMILES que cada fonte dá ao composto, lado a lado (vazio = a fonte não tem estrutura). O PubChem é consultado para todos os compostos com InChIKey. Textos diferentes NÃO indicam erro: a mesma molécula pode ser escrita de várias formas |
| `conferencia_smiles` | compara as **estruturas** das fontes (RDKit): `mesma molécula`, `estereoquímica diferente: …` ou `estruturas diferentes: NPASS/PubChem x COCONUT` (as fontes que concordam ficam juntas; estas são as que valem conferir à mão); `SMILES inválido: FONTE` quando o SMILES de uma fonte não é uma estrutura válida (ele não é usado como `composto_smiles`). Vazia sem o RDKit instalado |
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
**plantas** e dos **compostos** e manter, com o modelo, só os que
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

**6. Julgamento pelo modelo.** Ele lê cada par **entidade × resumo** e
responde em JSON:

- **Positivo**: o texto relata um **resultado experimental** (in vitro, ex
  vivo, in vivo ou clínico) em que a planta (extrato, fração, óleo, resina,
  substância isolada dela) ou o composto **produziu** o efeito. Ex.: "o
  extrato etanólico das folhas inibiu *S. aureus* (CIM 125 µg/mL)".
- **Negativo**: só menção; efeito de outra espécie ou composto; uso
  tradicional sem teste; resultado nulo ou fraco; química sem ensaio
  biológico; revisão ou especulação; estudo só in silico.
- Com `[termos_pubmed]`, só contam as atividades listadas.
- Quando a planta tem sinônimos, o modelo é avisado ("mesma planta, também
  citada como…").

Para cada artigo positivo, o modelo informa também:

| Informação | Valores |
|---|---|
| tipo de estudo | `in vitro`, `ex vivo`, `in vivo`, `clínico` |
| parte da planta (só plantas) | `folha`, `caule`, `casca`, `raiz`, `rizoma`, `tubérculo/bulbo`, `flor`, `fruto`, `semente`, `parte aérea`, `planta inteira`, `exsudato (látex/resina)`, `broto/calo/cultura` ou `não informado` |

A **melhor evidência** é o tipo de estudo mais forte entre os artigos
positivos: **clínico > in vivo > ex vivo > in vitro**.

**Velocidade do modelo.** O tempo por par aparece na barra *Classificando*
(`s/it`). Para conferir se o modelo está na placa de vídeo, rode `ollama ps`
com a etapa em andamento: a coluna `PROCESSOR` deve mostrar `100% GPU` (com
divisão CPU/GPU, o modelo não coube na placa e tudo fica muito mais lento).

**Vários resumos ao mesmo tempo** (`paralelo` em `[ollama]`, padrão 4): o
pipeline manda vários pares ao Ollama de uma vez, e cada resposta vai para
o cache assim que chega. Para isso valer, o Ollama precisa aceitar pedidos
simultâneos:

- **Linux** (Ollama como serviço): `sudo systemctl edit ollama`, acrescente
  ```
  [Service]
  Environment="OLLAMA_NUM_PARALLEL=4"
  ```
  salve e rode `sudo systemctl restart ollama`. (Se você inicia com
  `ollama serve`: `OLLAMA_NUM_PARALLEL=4 ollama serve`.)
- **Windows**: em *Configurações → Sistema → Sobre → Configurações
  avançadas do sistema → Variáveis de Ambiente*, crie a variável de usuário
  `OLLAMA_NUM_PARALLEL` = `4` e reinicie o Ollama (ícone na bandeja → *Quit*,
  depois abra de novo).

Sem isso, os pedidos simplesmente esperam na fila do Ollama: nada quebra, só
não acelera. Cada pedido simultâneo ocupa mais memória da placa; se aparecer
falta de memória ou divisão CPU/GPU no `ollama ps`, use `paralelo = 2`.

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

**Retomada**: todas as fases têm cache (seção 21). Cada julgamento do modelo
é gravado assim que termina, em `cache_llm_classificacao.jsonl`. Buscas que
falharam aparecem como `busca pendente (rode de novo)` e são refeitas na
próxima rodada.

---

## 17-A. Etapas 6 a 8: `normalizacao`, `banco` e `qualidade`

Estas três etapas rodam depois do `pubmed` e montam o **banco relacional** do
projeto. Elas não dependem de nenhuma outra, além das saídas das etapas
anteriores, e o `--retomar` pula cada uma se sua saída já existe.

### 17-A.1 Etapa 6: `normalizacao` → `compostos_normalizados.csv`

`mods/normalizar_compostos.py`. Normaliza os identificadores pelo PubChem,
classifica pelo ClassyFire e deduplica por InChIKey canônico, preservando toda a
rastreabilidade e registrando conflitos.

**Entrada**: `ocorrencias_compostos_bruto.csv` (etapa `bioativos`) — um registro
por base × planta. Se faltar (rodada da v3.16 ou anterior), usa
`especies_com_compostos_bioativos.csv`, com rastreabilidade reduzida.

**Como escolhe o InChIKey canônico de cada ocorrência**:
1. o InChIKey **declarado** pela base, se existe no PubChem;
2. senão, o InChIKey **calculado** (RDKit) do SMILES da própria base, se existe no PubChem;
3. senão, o declarado; 4. senão, o calculado. Sem nenhum, a ocorrência fica
   sem estrutura (entra na rastreabilidade, fora da tabela de compostos).

**Conflitos detectados** (em `normalizacao_conflitos.csv`, com severidade e a
resolução adotada): InChIKey declarado ≠ do SMILES da base; SMILES inválido;
estrutura/fórmula/CID divergentes entre bases; classe ClassyFire do COCONUT ≠
da API; mesmo id ou mesmo nome apontando para estruturas diferentes; variantes
de estereoquímica; sais e formas carregadas.

**Saídas**: `compostos_normalizados.csv` (um composto por InChIKey),
`normalizacao_ocorrencias.csv` (rastreabilidade), `normalizacao_sinonimos.csv`,
`normalizacao_conflitos.csv`, `normalizacao_mapa_inchikey.csv` (de-para dos
InChIKeys de origem para o canônico).

### 17-A.2 Etapa 7: `banco` → pasta `banco/`

`mods/gerar_banco.py`. Monta os CSVs relacionais com esquema e dicionário
públicos e calcula drogabilidade e ADMET básico de todo composto com SMILES.

Monta **12 tabelas CSV** (UTF-8 com BOM) interligadas pelo **InChIKey
canônico**, que no banco se chama **`compound_uid`**; os organismos se ligam
pelo `scientific_name`:

| Tabela | Conteúdo |
|---|---|
| `compounds_identity_master.csv` | identidade química: um composto por InChIKey, com identificadores do PubChem, ClassyFire, NPClassifier e contagens |
| `compounds_sources.csv` | rastreabilidade: cada registro de cada base (o que *aquela* base informa) |
| `compounds_synonyms.csv` | sinônimos e nomes (PubChem e bases) |
| `organisms.csv` | organismos produtores: taxonomia, distribuição e `in_region` |
| `compounds_biological_origin.csv` | composto × organismo |
| `compounds_geographic_distribution.csv` | composto × organismo × UF |
| `compounds_bioactivity.csv` | medidas quantitativas (ChEMBL, NPASS) e relatos qualitativos (PubMed) |
| `compounds_pathways.csv` | vias do PubChem e via biossintética do NPClassifier |
| `compounds_spectra.csv` | metadados de espectro das **fontes registradas**: PubChem (experimentais) e m/z teóricos dos adutos (RDKit). Aceita fontes novas sem alterar o pipeline (17-A.4) |
| `compounds_druglikeness_admet.csv` | drogabilidade e ADMET básico (RDKit): Lipinski, Veber, Ghose, Egan, Muegge, QED, TPSA, BOILED-Egg, alertas PAINS/Brenk |
| `conflicts.csv` | conflitos da etapa `normalizacao` |
| `inchikey_map.csv` | de-para dos InChIKeys de origem |

Mais `dicionario_dados.csv`, `ESQUEMA.md` (com diagrama ER), `datapackage.json`
(Frictionless Data: chaves primárias e estrangeiras) e `LEIA-ME.txt`.

**Por que em inglês.** `banco/` é o produto que vai para um repositório
permanente e para publicação, e por isso **tudo** dentro dela sai em inglês: os
nomes dos arquivos, as colunas, a chave universal, os documentos em prosa
(`SCHEMA.md`, `PROVENANCE_AND_LICENSES.md`, `README.txt`) e a pasta
`banco/qualidade/` (arquivos, cabeçalhos e `QUALITY_REPORT.md`). As planilhas
de trabalho na raiz (`plantas.csv`, `especies_com_compostos_bioativos.csv`...)
seguem em português, e o `dicionario_dados.csv` é bilíngue: traz o nome da
coluna nos dois idiomas (`coluna` e `coluna_pt`) e a descrição nos dois
(`description_en` e `descricao_pt`). Com `[banco] idioma_banco = pt` todo o
conteúdo de `banco/` volta ao português (`compostos.csv`, `inchikey`,
`ESQUEMA.md`, `RELATORIO_QUALIDADE.md`...).

> A prosa do relatório de qualidade (o corpo do `QUALITY_REPORT.md`) é a única
> parte que segue em português nos dois modos: ela é o documento de análise do
> autor. Os nomes dos arquivos, os cabeçalhos das tabelas e as referências
> internas acompanham o idioma do banco.

> Atenção a `compounds_bioactivity.p_activity`: é −log10(molar) da medida
> (pChEMBL quando existe), **não** um p-valor estatístico. A coluna se chamava
> `pvalor` na v3.17.

**FAIR.** O banco segue os princípios FAIR:

- **Findable** — InChIKey como identificador canônico universal; `datapackage.json`
  com `title`, `description`, `keywords`, `version`, `created` e `id`;
  `dicionario_dados.csv` e `ESQUEMA.md`.
- **Accessible** — formato aberto (CSV UTF-8), sem ferramenta proprietária;
  `source_url` resolve cada ocorrência à sua base.
- **Interoperable** — identificadores externos padronizados (PubChem CID, ChEMBL,
  ClassyFire, NPClassifier) e esquema Frictionless com chaves estrangeiras.
- **Reusable** — proveniência por registro (`compounds_sources.csv`, `identification_method`),
  conflitos registrados, e `PROVENIENCIA_E_LICENCAS.md` com a licença do banco
  (**CC-BY-SA-4.0**, compatível com a fonte mais restritiva, o ChEMBL) e os termos
  de cada base de origem. Confirme os termos vigentes de cada fonte na data da coleta.

> O perfil ADMET é calculado por **regras físico-químicas** (RDKit): são
> estimativas para triagem, não medidas. Com `admet_ai = true` no `[banco]` e o
> pacote `admet-ai` instalado, colunas previstas por rede neural são
> acrescentadas com o prefixo `admetai_`.

### 17-A.3 Etapa 8: `qualidade` → pasta `banco/qualidade/`

`mods/analisar_qualidade.py`. Lê a pasta `banco/` (sem rede) e
gera `RELATORIO_QUALIDADE.md` mais planilhas: `completude_por_base.csv`
(completude dos campos por base de origem), `espaco_quimico_*.csv` (distribuição
por ClassyFire e NPClassifier), `taxonomia_*.csv` (cobertura por família, ordem,
classe, reino), `sobreposicao_bases.csv` e `sobreposicao_jaccard.csv` (exclusivos
e compartilhados entre bases) e `vieses_curadoria.csv` (concentração por
base/família/classe e lacunas sistemáticas de estrutura, bioatividade e
distribuição).

### 17-A.4 Fontes novas e extensibilidade

O pipeline tem **dois pontos de extensão**, um por camada. Em nenhum deles é
preciso alterar um arquivo que já existe: o registro varre a pasta `mods/`,
reconhece o módulo pelo nome do arquivo e o chama.

| Camada | Registro | Módulo novo | Chave | Modelo |
|---|---|---|---|---|
| Compostos | `mods/fontes_compostos.py` | `mods/fonte_<nome>.py` | `[bioativos] usar_<nome>` | `mods/fonte_exemplo.py` |
| Espectros | `mods/espectros.py` | `mods/espectros_<nome>.py` | `[banco] espectros_<nome>` | `mods/espectros_exemplo.py` |

A chave do `input.txt` passa a ser aceita assim que o módulo existe — e só
então, para um erro de digitação continuar sendo erro.

**Camada de compostos.** É por aqui que entram bases de pares
organismo–composto: **NPAtlas**, **HMDB** ou uma base própria. As três do
pacote (Dr. Duke, LOTUS e FooDB) já usam essa interface. Atenção: uma base de
organismos que não são plantas também precisa de `escopo = completo` e
`reino = qualquer` (seção 15.1), senão o filtro de reino descarta os
organismos dela antes de a fonte entrar no resultado.

**Camada de espectros.** Vêm no pacote três módulos:

| Módulo | Fonte | Internet | Padrão |
|---|---|---|---|
| `espectros_teoricos.py` | m/z teóricos dos adutos (RDKit) | não | ligada |
| `espectros_pubchem.py` | espectros experimentais compilados no PubChem | sim | ligada |
| `espectros_exemplo.py` | modelo comentado, com registros fictícios | não | **desligada** |

Para acrescentar uma base espectral nova — **GNPS**, **MassBank Europe**,
**MoNA** — basta criar `mods/espectros_<nome>.py` e ligar a chave. O guia
completo das duas camadas, com as interfaces, o uso do cache e do cliente de
rede, como testar sem internet e como conferir que nenhum arquivo existente
mudou, está na **seção 26**.

Para ver quais fontes o pipeline encontrou, sem rodar nada:

```bash
cd mods && python3 -c "import espectros, fontes_compostos as F; print(espectros.resumo()); print(F.resumo())"
```

Durante a etapa `banco`, a tela mostra uma linha por fonte, com quantos
registros cada uma trouxe e quais estão desligadas.

> A tabela de espectros é preenchida **desde a primeira rodada**, pelo PubChem
> e pelo RDKit. Uma fonte nova aprofunda essa camada; ela não cria uma camada
> que faltava.
---

# Parte V: Resultados

## 18. Qual arquivo abrir e como ler

### 18.1 Qual arquivo responde a cada pergunta

| Pergunta | Arquivo |
|---|---|
| Que plantas entraram na lista, e de onde vieram? | `plantas.csv` |
| Que nomes do GBIF e dos artigos foram descartados (não são plantas), e por quê? | `plantas_descartados.csv` |
| Qual é o nome aceito de cada nome? O que cada base disse? Em que linha ele ficou? | `plantas_conferencia_taxonomica.csv` |
| Em que artigos sobre a região cada planta aparece? | `plantas_artigos_evidencias.csv` |
| Em que estados do Brasil cada planta ocorre? É endêmica? | `plantas.csv` (`estados_br`, `endemismo_br`…) |
| Que compostos cada planta tem? Qual a estrutura e as fontes concordam? | `especies_com_compostos_bioativos.csv` (`smiles_*`, `conferencia_smiles`) |
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
| `estados_br`, `dominios_br`, `endemismo_br`, `origem_br` | distribuição no Brasil (de `plantas.csv`) |
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
| `smiles`, `fonte_smiles` | estrutura do composto e a base de onde ela veio (como em `especies_com_compostos_bioativos.csv`) |
| `smiles_npass` … `smiles_pubchem`, `conferencia_smiles` | SMILES de cada fonte e a conferência entre elas (como em `especies_com_compostos_bioativos.csv`) |
| `composto_ids` | identificadores nas bases de compostos |
| `plantas`, `n_plantas` | plantas da lista em que o composto ocorre |
| `estados_composto` | estados em que o composto ocorre: união dos estados dessas plantas (`distribuição desconhecida` se nenhuma tem estado conhecido) |
| `atividades_relatadas_composto` | ex.: `clareadora (PMID 111, 222)` |
| `melhor_evidencia_composto`, `estudos_composto` | como nas plantas |
| `n_artigos_positivos` | artigos positivos distintos |
| `bases` | bases químicas em que o composto foi encontrado nessas plantas (ex.: `COCONUT; DUKE; LOTUS; NPASS`) |
| `atividades_duke` | atividades no Dr. Duke (com `[termos_pubmed]`, só as que casam com as suas) |
| `referencias_lotus` | DOIs por planta, segundo o LOTUS (ex.: `Euterpe oleracea: DOI 10.1/abc; …`; até 5 plantas) |
| `chembl_id`, `correspondencia_chembl`, `atividades_chembl`, `atividades_previstas_chembl` | da etapa 4 |

Esta planilha reúne as **três fontes de atividade** de cada composto:
**PubMed** (artigos lidos pelo modelo), **ChEMBL** (ensaios medidos) e **Dr.
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
| `justificativa_llm` | frase curta do modelo citando o resultado |
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
   modelo faz uma triagem, não uma revisão sistemática.

---

## 19. Mensagens de status nas planilhas

Quando não há atividade, a célula explica o motivo.

**Colunas `atividades_relatadas_planta` e `atividades_relatadas_composto`**

| Mensagem | Significado | O que fazer |
|---|---|---|
| `nenhuma relação causal positiva encontrada…` | houve artigos, mas nenhum demonstrou a atividade | — |
| `nenhum artigo encontrado no PubMed` | as buscas não trouxeram artigos | — |
| `artigos encontrados; leitura pelo modelo pendente` | só nos arquivos `*_parcial.csv`: ainda não lido | esperar a rodada principal |
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
planilhas uma a uma. Funciona com as saídas das versões 3 a 3.10. O script **só lê** os arquivos
que o pipeline já gravou: não acessa a internet, não altera nenhuma planilha nem cache e não
interfere numa rodada em andamento.

### 20.1 Como rodar

**Automático**: a partir da versão 3.7, o próprio pipeline gera os gráficos
ao terminar as etapas `plantas`, `bioativos`, `chembl` e `pubmed` (os da
etapa e os da visão geral) e atualiza `graficos/relatorio.html`, que vai
acumulando as etapas. Um problema nos gráficos nunca interrompe o pipeline:
vira só um aviso. Para desligar: `./rodar.sh --sem-graficos`.

**À mão**, a qualquer momento:

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

- O `matplotlib` é instalado pelo `instalar.sh` / `instalar.bat`; numa
  instalação antiga, o lançador o instala na primeira vez (precisa de
  internet só nesse momento). Sem os lançadores:
  `.venv/bin/python graficos.py` (Windows: `.venv\Scripts\python graficos.py`).
- **Pode rodar a qualquer momento**: etapas sem arquivo de saída são puladas,
  com um aviso na tela e no relatório. Rodar de novo substitui os gráficos
  das etapas escolhidas; as outras continuam no relatório como estavam.
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
| | Situação dos nomes | aceitos, sinônimos, grafias variantes, homônimos ambíguos; em cinza, os não reconhecidos; em laranja, os da sua lista que nenhuma base conhece (mantidos e pesquisados). Na versão 3.3, "aceito (fontes: só sinônimo/grafia)" conta as linhas que receberam o nome aceito embora as fontes só trouxessem sinônimos ou grafias variantes |
| | Vereditos das bases | o que a Flora do Brasil, o WFO, o WCVP (versão 3.1) e o GBIF disseram sobre os nomes: aceito, sinônimo, grafia variante, homônimo ambíguo, não encontrado |
| | Artigos da descoberta por ano | PubMed × OpenAlex ao longo do tempo |
| | Plantas mais citadas nos artigos | as mais estudadas na literatura sobre a região; em **cinza**, os nomes que nenhuma base reconheceu, que ficam fora das etapas 3 e 5 (na versão 3.1 eles já saem da lista: ver os dois gráficos seguintes) |
| | Nomes descartados, por motivo (3.1) | quantos nomes do GBIF e dos artigos ficaram fora de `plantas.csv`: não é planta, não reconhecido, só gênero |
| | Nomes descartados mais citados (3.1) | os descartados que mais aparecem nos artigos: confira se não há uma planta real com erro de grafia, e acrescente o nome correto à sua lista |
| | Atividades citadas nos artigos | quantas plantas aparecem em artigos sobre cada atividade de `[termos_pubmed]`. Com a seção vazia (versão 3.2, "atividade biológica (geral)"), mostra as plantas com mais artigos sobre atividade biológica |
| | Famílias na lista final | riqueza por família, juntando as três fontes |
| | Plantas por estado | quantas plantas ocorrem em cada estado (Flora e Funga do Brasil) e quantas têm distribuição desconhecida |
| **3 bioativos** | Contribuição de cada base | pares e compostos de COCONUT, NPASS, LOTUS, Dr. Duke e FooDB (a tabela traz também a contribuição exclusiva de cada uma) |
| | Conferência dos SMILES entre as fontes | compostos com SMILES em 2+ fontes: mesma molécula, estereoquímica diferente ou estruturas diferentes; a tabela conta quais fontes discordam de quais |
| | Origem da estrutura (SMILES) | quantos compostos têm SMILES e de onde veio: COCONUT, NPASS, LOTUS ou PubChem (3.8 em diante; planilhas antigas aparecem como "origem não registrada") |
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
| **5 pubmed** | Julgamentos do modelo | quantos resumos já foram lidos e a proporção de positivos (vem do cache: útil com a etapa em andamento) |
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

Um gráfico só aparece quando há dados para ele: por exemplo, os gráficos de
nomes descartados só aparecem com as saídas da versão 3.1, *Atividades
citadas nos artigos* exige `[termos_pubmed]` preenchido ou a versão 3.2, e *Partes da planta
(Dr. Duke)* exige `usar_duke = true`.

### 20.4 Cuidados na leitura

- Os gráficos herdam as **limitações das planilhas** (seção 24): contagem de
  artigos mede atenção da pesquisa, não força do efeito; "nenhum artigo"
  não é ausência de atividade.
- As **atividades** da etapa 5 são os rótulos escritos pelo modelo; nomes
  parecidos (`antibacteriana` e `antimicrobiana`) aparecem separados.
- No **modo parcial**, os números da etapa 5 crescem a cada rodada do
  `./rodar.sh parcial`: anote a data do relatório (aparece no topo).
- Cores: a paleta foi escolhida para ser distinguível por pessoas com
  daltonismo, e nenhuma informação depende só da cor (há rótulos e
  legendas em todos os gráficos).

---

## 20-A. Painel interativo (Streamlit)

`painel.py` → abre no navegador, em `http://localhost:8501`

**Objetivo**: explorar os resultados de cada etapa com filtros, cruzar as
etapas e baixar recortes, sem abrir as planilhas uma a uma. O painel **só lê**
os arquivos do pipeline: não altera nenhuma planilha nem cache, não consulta a
internet e pode ficar aberto com o pipeline rodando.

### 20-A.1 Como abrir

| Linux / macOS | Windows | Efeito |
|---|---|---|
| `./painel.sh` | `painel.bat` | abre o painel no navegador |
| `./painel.sh --server.port 8502` | `painel.bat --server.port 8502` | outra porta (se a 8501 estiver ocupada) |

- **Na primeira vez**, o lançador instala o `streamlit` no ambiente do
  pipeline (`.venv`, `.venv-linux` ou `.venv-win`); precisa de internet só
  nesse momento. Sem os lançadores: `.venv/bin/python -m streamlit run painel.py`
  (Windows: `.venv\Scripts\python -m streamlit run painel.py`).
- **Para fechar**: `Ctrl+C` no terminal onde o painel foi aberto.
- **Etapas que ainda não rodaram** aparecem com um aviso; o resto do painel
  funciona normalmente. Depois de uma nova rodada, use **Configurações →
  Recarregar os dados** (ou só atualize a página: arquivos alterados são relidos).
- **Com a etapa 5 em andamento**: rode `./rodar.sh parcial` e ligue
  **Configurações → Modo parcial**, para ler os `*_parcial.csv`.
- **Outra pasta**: em **Configurações → Pasta do projeto** dá para apontar
  para outra rodada (por exemplo, uma cópia de outra região).
- **Com `[bioativos]` `escopo = completo`**: o interruptor **Configurações →
  Só as plantas da região** (ligado por padrão) mantém as páginas mostrando só
  a sua região. Desligue para incluir as plantas de fora. As páginas afetadas
  avisam, numa linha, qual dos dois está valendo. A página **6–8 · Banco**
  nunca filtra: ela mostra o banco publicável como ele está (seção 15.1).
- **Idioma do banco**: o painel lê a pasta `banco/` tanto em inglês (padrão
  desde a v3.18) como em português, sem configuração. Nas páginas, as colunas
  aparecem em português; na página **6–8 · Banco**, cada tabela é mostrada com
  os nomes que ela tem no arquivo.

### 20-A.2 As páginas

| Página | Lê | O que dá para fazer |
|---|---|---|
| **Início** | todos os arquivos de saída | situação de cada etapa (concluída ou não, linhas, data) e o funil plantas → compostos → atividade |
| **1 · GBIF** | `especies_gbif.csv` | filtrar por família, nome e número de registros; espécies e famílias mais registradas; link para o GBIF |
| **2 · Plantas** | `plantas.csv`, `plantas_conferencia_taxonomica.csv`, `plantas_descartados.csv` | filtrar por família, fonte, situação do nome, **estado, domínio, endemismo e origem**; gráficos por estado, plantas restritas a um estado, domínios e endemismo por domínio; conferência dos nomes e nomes descartados |
| **3 · Compostos** | `banco/compostos.csv` e `banco/perfil_admet.csv` (sem o banco: `especies_com_compostos_bioativos.csv`) | filtrar por planta, família, base, via biossintética, superclasse, QED, massa molecular, **Lipinski** e **alertas PAINS**; classes químicas e **espaço químico** (massa × logP, ou NP-likeness × QED); link para o PubChem |
| **4 · ChEMBL** | `banco/bioatividade.csv` (ChEMBL e NPASS) ou `evidencias_chembl.csv`, e `compostos_chembl.csv` | filtrar por atividade, alvo, organismo, tipo de ensaio, medida, correspondência e **pChEMBL mínimo**; potência, alvos e medidas; link para o artigo |
| **5 · PubMed** | `evidencias_pubmed.csv`, `atividades_plantas.csv`, `atividades_compostos.csv` | filtrar por atividade, **evidência mínima** (clínico > in vivo > ex vivo > in vitro), **coleta sustentável** e ano; resumo, plantas, compostos e a lista de artigos com a justificativa do modelo e o link |
| **Prospecção** | as etapas 2 a 5 (e o banco) | **plantas candidatas**: escolha as atividades, a evidência mínima, o pChEMBL mínimo, a coleta e a distribuição; para cada planta, os artigos positivos sobre ela e os compostos dela com atividade (em artigos e em ensaios). Sem nota opaca: você escolhe a ordenação (por exemplo, "menos compostos conhecidos", para química pouco explorada) |
| **Ficha** | tudo | **uma planta**: dados, distribuição, artigos positivos e compostos, com a atividade de cada um. **Um composto**: identidade, perfil ADMET, plantas em que ocorre, ensaios, artigos, vias, espectros, sinônimos e conflitos entre bases |
| **6–8 · Banco e qualidade** | pasta `banco/` (em inglês ou em português) | número de linhas e conteúdo de cada tabela, com o dicionário de dados bilíngue; drogabilidade (filtros de Lipinski, Veber, Ghose, Egan, Muegge, BOILED-Egg, QED, PAINS); conflitos entre bases por tipo e severidade; planilhas e relatório da etapa `qualidade` |

Os filtros ficam na barra lateral e valem para a página inteira. Cada tabela
tem um botão **Baixar esta tabela (CSV)**, que grava exatamente o recorte
filtrado (UTF-8 com BOM, abre no Excel). As tabelas mostram até 20.000 linhas;
o download traz todas.

### 20-A.3 Cuidados

- O painel mostra o que está nas planilhas, com as mesmas limitações
  (seção 24): contagem de artigos mede atenção da pesquisa, não força do
  efeito; o perfil ADMET é **previsão por regra** (RDKit), não medida.
- Na **Prospecção**, os rótulos de atividade do PubMed são os escritos pelo
  modelo (ex.: `antioxidante`), e os do ChEMBL são os do `input.txt`; escolha
  os dois quando forem a mesma atividade com nomes diferentes.
- Um composto conta como "ativo" em ensaio quando tem registro com pChEMBL
  igual ou acima do mínimo escolhido. Por padrão, só ensaios do **próprio**
  composto (sem estereoisômero nem previsão por similaridade).
- Planilhas muito grandes (milhões de linhas) demoram alguns segundos na
  primeira leitura; depois ficam em memória enquanto o painel estiver aberto.
- Com `escopo = completo`, lembre-se de que a etapa 5 (PubMed) só leu as
  plantas da região: na **Prospecção**, uma planta de fora nunca terá artigo
  positivo, mesmo com o interruptor da região desligado.


---

# Parte VI: Referência

## 21. Caches

Cada linha de um arquivo `cache_*.jsonl` é uma consulta concluída. As
chaves incluem a consulta exata (e, quando importa, o modelo e as
atividades), de modo que mudar a configuração não reaproveita resultados
errados: só o que mudou é refeito.

| Cache | Etapa | Guarda | Apague para… |
|---|---|---|---|
| `dados_gbif_download/pedidos.json` | 1 | chave do pedido de cada região e do pedido em SQL dos estados (`SQL|estados_BR…`) | forçar um download novo do GBIF (ou apagar só a linha do SQL e o `especies_gbif_estados.csv` para refazer os estados) |
| `dados_gbif_download/cache_nomes_populares.json` | 1 | nomes populares das espécies da região | atualizar os nomes populares |
| `cache_taxonomia_flora.jsonl`, `cache_taxonomia_wfo.jsonl`, `cache_taxonomia_gbif.jsonl` | 2 | veredito de cada base para cada nome | reconferir nomes (feito sozinho com `--atualizar-bases`) |
| `cache_gbif_extras.jsonl` | 2 | ocorrências e nome popular das plantas da lista e dos artigos | atualizar esses dados |
| `cache_openalex.jsonl` | 2 | buscas no OpenAlex | buscar artigos novos |
| `cache_pubmed_buscas.jsonl` | 2 e 5 | PMIDs de cada busca no PubMed | buscar artigos publicados depois |
| `cache_pubmed_artigos.jsonl` | 2 e 5 | títulos e resumos baixados | (raramente necessário) |
| `cache_pubchem_duke.jsonl` | 3 | InChIKey dos compostos do Dr. Duke e do FooDB | refazer essa identificação |
| `cache_pubchem_smiles.jsonl` | 3 | SMILES do PubChem de cada composto (por InChIKey) | consultar de novo |
| `cache_chembl_*.jsonl` | 4 | moléculas, atividades, estereoisômeros, documentos, similares | atualizar o ChEMBL (feito sozinho com `--atualizar-bases`) |
| `cache_pubchem.jsonl`, `cache_pubchem_cid.jsonl` | 5 | nome e CID de cada composto | atualizar identificadores |
| `cache_pubchem_vinculos.jsonl` | 5 | artigos ligados a cada CID | buscar vínculos novos |
| `cache_pubmed_filtro.jsonl` | 5 | quais artigos ligados tratam de cada atividade | buscar artigos novos |
| `cache_llm_classificacao.jsonl` | 5 | julgamento do modelo para cada par entidade × artigo | ⚠️ **reavaliar tudo** (dias de trabalho; mova em vez de apagar) |

---

## 22. Tempo de execução e escala

| Etapa | Primeira vez | Nas seguintes |
|---|---|---|
| 0 `downloads` | 15–40 min (conexão) | segundos |
| 1 `gbif` | 5 min a ≈ 1 h (fila do GBIF) + nomes populares + o pedido em SQL dos estados (de minutos a algumas horas, conforme a fila) | segundos |
| 2 `plantas` | minutos a horas (leitura do WFO, descoberta em artigos, ≈ 3 consultas ao GBIF por nome fora da etapa 1) | minutos |
| 3 `bioativos` | minutos, mais, na 1ª vez: a identificação dos compostos do Dr. Duke no PubChem e o SMILES do PubChem de todos os compostos (em lotes pelo CID; os sem CID, um a um, ≈ 0,8 s cada: num teste real, 66 mil compostos levaram ≈ 14 h). Tudo fica em cache: interromper não perde o que já foi consultado | minutos |
| 4 `chembl` | minutos a poucas horas (a previsão por similaridade pode levar muitas horas) | minutos |
| 5 `pubmed` | **horas a dias** | só o que falta |

**Listas grandes**: com 30 mil nomes em `lista_de_plantas.txt`, a etapa 2
pode levar de 10 a 20 horas na primeira vez (tudo em cache, pode
interromper).

**O que pesa na etapa 5**

- **Buscas no PubMed**: plantas × atividades, reduzidas pela pré-checagem.
  Com a chave do NCBI, ≈ 8 por segundo; sem ela, ≈ 3.
- **Leituras do modelo**: ≈ nº de pares entidade × artigo (a tela mostra o
  total em "Modelo (…): N par(es) … a classificar"). A 12 s por resumo em
  CPU, 20 mil resumos levam cerca de 2,5 dias; com GPU, 1 a 3 s por resumo.
  Exemplo real: 550 mil pares a 3,1 s cada ≈ 20 dias; com `paralelo = 4` e
  `OLLAMA_NUM_PARALLEL=4`, a expectativa é 2 a 3× menos. Para listas
  grandes, o que mais reduz o tempo é `plantas_pesquisadas = com_compostos`
  e limites menores em `max_artigos_por_planta` / `max_artigos_por_composto`.

**Para controlar o tempo**

- comece com `max_plantas = 300` e `max_compostos = 200`;
- restrinja as atividades em `[termos_pubmed]`;
- use `plantas_pesquisadas = com_compostos`;
- reduza `max_artigos_por_planta` e `max_artigos_por_composto`;
- `busca_composto_por_nome = nunca` (só a via InChIKey);
- use GPU; sem GPU, um modelo menor (`llama3.1:8b`);
- use a chave do NCBI.

---

## 23. Solução de problemas

| Sintoma | Causa provável e solução |
|---|---|
| `./painel.sh`: `streamlit: command not found` ou erro ao instalar | a internet só é necessária na primeira vez; à mão: `.venv/bin/python -m pip install "streamlit>=1.50"` (Windows: `.venv\Scripts\python -m pip install "streamlit>=1.50"`) |
| O painel abre sem dados ("Nenhuma planilha do pipeline nesta pasta") | o `painel.py` precisa estar na pasta do `rodar.sh`; ou indique a pasta em **Configurações → Pasta do projeto** |
| `Port 8501 is already in use` | outro painel já está aberto: use a aba que já existe, ou `./painel.sh --server.port 8502` |
| O painel não mostra o resultado de uma rodada nova | **Configurações → Recarregar os dados** |
| `Problema no arquivo de entrada…` | o erro indica a linha: vírgula decimal, latitude e longitude trocadas, chave com nome errado ou repetida. Rode `./rodar.sh config` |
| A etapa 1 pergunta se você já configurou as credenciais | falta o login do GBIF em `config/credenciais.txt`. Responda **n**, preencha no editor que abrir, salve |
| `Credenciais do GBIF não configuradas…` e o pipeline para | rodando sem terminal, ele não pode perguntar. Preencha o `credenciais.txt` e rode de novo |
| `GBIF recusou o login (HTTP 401)` | usuário ou senha errados (use o **usuário**, não o e-mail) |
| O editor não abriu (Linux sem interface) | o pipeline usa `$EDITOR`, `nano` ou `vi`; se nenhum existir, edite o arquivo à mão |
| `[FALHOU]` na etapa 0 | sem internet ou servidor fora. Rode `./rodar.sh --somente downloads` mais tarde ou faça o download manual (seção 12) |
| `403 Client Error` ao baixar a Flora do Brasil | baixe pelo navegador em https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil e salve como `dados_flora_brasil/flora_brasil_dwca.zip` |
| `CERTIFICATE_VERIFY_FAILED` | o Python não confia no certificado do servidor. Confira se o `truststore` está instalado (`pip install truststore`), que faz o Python usar os certificados do sistema |
| `ERRO: Ollama não está acessível` | inicie o Ollama (Linux: `sudo systemctl start ollama` ou `ollama serve`; Windows/macOS: abra o aplicativo) e rode `--a-partir-de pubmed` |
| `modelo '…' não encontrado no Ollama` | `ollama pull qwen3.5:35b-a3b` (ou o modelo de `[ollama]`) |
| `classificação(ões) falharam (timeout/JSON inválido)` | o modelo demorou demais; rode de novo ou aumente `timeout_segundos` |
| Muitas linhas `busca pendente` | limite de requisições do NCBI; use a chave e rode de novo para completar |
| `! esearch falhou (… too many 500 error responses)` em série | o servidor do NCBI está instável. Depois de 10 falhas seguidas, a etapa pausa 10 min e tenta de novo; depois de 3 pausas sem melhora, encerra a fase de buscas e segue com o que está em cache. Rode de novo mais tarde: só o que faltou é buscado. Situação do NCBI: https://www.ncbi.nlm.nih.gov/ |
| OpenAlex pulado (sem cota) | coloque `OPENALEX_API_KEY`; a descoberta segue só com o PubMed |
| A lista tem "plantas" estranhas (bactérias, palavras) | vêm da descoberta em artigos; estão como `não reconhecido` e não são usadas nas etapas 3 e 5 |
| A etapa 5 está lenta demais | seção 22; confira se o modelo usa a GPU (`ollama ps`) |
| `ATENÇÃO: … está aberto em outro programa (Excel?)` | no Windows, um arquivo aberto no Excel não pode ser substituído. Feche-o: a etapa continua sozinha quando ele é liberado (espera até 10 min) |
| `GBIF não respondeu ao pedido (… HTTP 503)` | servidor do GBIF sobrecarregado. A etapa tenta de novo sozinha; se desistir, rode mais tarde ou use um download já feito: `--somente gbif --gbif-chave CHAVE` |
| `Há download desta MESMA área com outro filtro de países` | o download antigo foi feito com outro `pais`. A etapa pede um novo; para usar o antigo: `--gbif-chave` com a chave mostrada |
| `AVISO: estados do GBIF não obtidos (…)` | o pedido em SQL falhou (recurso experimental do GBIF) ou faltam as credenciais. A distribuição usa só a Flora; tente de novo com `--somente gbif` e depois `--somente plantas` |
| FooDB: `o site recusou o download automático (HTTP 403)` | baixe pelo navegador (https://foodb.ca/downloads, o CSV) e ponha o arquivo em `dados_bioativos/` (qualquer nome começando por `foodb`, `.tar.gz` ou `.tar`); ou `usar_foodb = false` |
| `Conferência dos SMILES …: pulada (RDKit não instalado)` | rode o instalador de novo, ou `.venv/bin/python -m pip install rdkit` (Windows: `.venv\Scripts\python -m pip install rdkit`) |
| `SMILES do PubChem` demora na 1ª rodada | os compostos sem CID são consultados um a um (podem ser muitas horas); tudo fica em cache, e uma rodada interrompida continua de onde parou. Para pular: `smiles_pubchem = false` em `[bioativos]` |
| `TypeError: Invalid value for dtype 'str'` na etapa `bioativos` | versão 3.11 com pandas 3: corrigido na 3.12. As consultas já feitas ao PubChem estão no cache; rode `--somente bioativos` de novo |
| Linux: `Permission denied` em `./rodar.sh` | `chmod +x rodar.sh instalar.sh`, ou `bash rodar.sh` |
| Linux: `externally-managed-environment` | use o `./instalar.sh` (cria o `.venv`); se faltar o venv: `sudo apt install python3-venv` |
| Linux: `bash\r: No such file or directory` | o arquivo foi salvo com quebras de linha do Windows: `sed -i 's/\r$//' rodar.sh instalar.sh` |
| Linux: o pipeline parou ao fechar o terminal | use `tmux` ou `nohup` (seção 10.4) |
| `ERRO: matplotlib não encontrado` | rode o instalador de novo, ou pelo `./graficos.sh` / `graficos.bat`, que o instala; à mão: `.venv/bin/python -m pip install matplotlib` (Windows: `.venv\Scripts\python -m pip install matplotlib`) |
| `./graficos.sh` falha ao instalar o matplotlib | a internet só é necessária na primeira vez; atrás de proxy, instale à mão com o comando acima |
| `AVISO: gráficos da etapa ... não gerados - falta o matplotlib` | instalação anterior à 3.7: rode o `instalar.sh` / `instalar.bat` de novo (não apaga nada) |
| `Permission denied` em `./graficos.sh` | `chmod +x graficos.sh`, ou `bash graficos.sh` |
| Um gráfico esperado não aparece | a etapa dele não terminou ou a coluna está vazia: o aviso aparece na tela e no topo da etapa, no relatório |
| O relatório abre sem as imagens | o `relatorio.html` procura as imagens na mesma pasta: copie a pasta `graficos/` inteira, não só o HTML |
| `erro ao gerar os gráficos desta etapa` no relatório | em geral, uma planilha foi aberta e salva noutro formato (ex.: no Excel, com `;`). Rode a etapa de novo para regravá-la; as outras etapas não são afetadas |

---

## 24. Limitações e cuidados na interpretação

- **O modelo faz triagem, não revisão sistemática.** Ele pode errar,
  sobretudo com resumos ambíguos. Confirme os resultados importantes no
  artigo (coluna `link`).
- **Só resumos são lidos**, não o texto completo. Tipo de estudo e parte da
  planta podem ficar como `não informado`.
- **Atividade do composto ≠ atividade da planta.** Para compostos muito
  estudados (ex.: quercetina), os artigos tratam do composto em geral. A
  coluna `atividades_relatadas_planta` é a que liga a atividade à espécie.
- **Ausência de evidência não é evidência de ausência.** "Nenhum artigo
  encontrado" pode significar só que a planta é pouco estudada.
- **As bases taxonômicas discordam.** A prioridade (Flora > WFO > WCVP > GBIF)
  decide o nome aceito; todas as versões ficam em `nomes_busca` e as
  divergências em `observacoes_taxonomia`.
- **A descoberta em artigos é textual.** Uma planta citada num artigo sobre
  a região não ocorre necessariamente lá; confira
  `n_ocorrencias_na_area`.
- **Registros do GBIF** incluem plantas cultivadas e erros de
  identificação. Na distribuição, um estado sustentado por poucos registros
  (`registros_gbif_por_uf`) pede cautela.
- **Estados de um composto** (`estados_composto`) são os estados das plantas
  da lista em que ele foi registrado, não os locais onde o composto foi
  medido: os estudos químicos podem ter usado material de outra região.
- **SMILES diferentes não significam erro.** A mesma molécula pode ser
  escrita de várias formas; compare pela coluna `conferencia_smiles`, que
  compara as estruturas. "Estruturas diferentes" aponta os casos a conferir.
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
| Flora e Funga do Brasil (JBRJ) | nomes (lista oficial do Brasil); distribuição por estado, domínios, endemismo | https://floradobrasil.jbrj.gov.br |
| World Flora Online | nomes (lista mundial) | https://www.worldfloraonline.org |
| WCVP (Kew) | nomes de plantas vasculares | https://powo.science.kew.org · dados: https://sftp.kew.org/pub/data-repositories/WCVP/ |
| COCONUT 2.0 | produtos naturais e organismos | https://coconut.naturalproducts.net |
| NPASS 3.0 | pares espécie–composto, atividades, alvos | https://bidd.group/NPASS |
| Dr. Duke's Phytochemical and Ethnobotanical Databases (USDA) | parte da planta, teor, atividades | https://phytochem.nal.usda.gov |
| LOTUS | pares composto–organismo com DOI | https://lotus.naturalproducts.net · dados: https://zenodo.org/records/19360665 |
| FooDB | compostos de alimentos e teores (uso comercial exige permissão) | https://foodb.ca |
| ChEMBL | atividades medidas em ensaios | https://www.ebi.ac.uk/chembl |
| PubChem | InChIKey, CID, nomes, SMILES, artigos ligados | https://pubchem.ncbi.nlm.nih.gov |
| GADM | divisão em estados usada pelo GBIF na tabela de estados | https://gadm.org |
| RDKit (opcional) | comparação das estruturas (SMILES) entre as fontes | https://www.rdkit.org |
| PubMed | resumos de artigos | https://pubmed.ncbi.nlm.nih.gov |
| OpenAlex | artigos (descoberta de plantas) | https://openalex.org |
| Ollama + modelo (Qwen 3.5 por padrão) | julgamento dos resumos | https://ollama.com |

Ao publicar resultados:
- **GBIF**: cite o **DOI de cada download** (o da região e, se usado, o da
  tabela de estados). Eles aparecem no site do GBIF, em *Downloads* da sua
  conta; as chaves estão em `dados_gbif_download/pedidos.json`.
- **Demais bases**: cite a publicação de referência indicada no site de
  cada uma e a versão usada (COCONUT: `dados_bioativos/coconut_versao.txt`;
  LOTUS: `dados_bioativos/lotus_versao.txt`; ChEMBL: nome do arquivo
  baixado).

---

## 26. Como acrescentar uma fonte de dados ao pipeline

Guia para quem vai ligar uma base nova ao banco — por exemplo o **GNPS**, o
**MassBank Europe** ou o **MoNA** na camada espectral, ou o **NPAtlas** e o
**HMDB** na de compostos.

O pipeline tem dois pontos de extensão, um por camada. Em nenhum dos dois é
preciso alterar um arquivo que já existe: você **cria um módulo** em `mods/`,
e o registro da camada o descobre pelo nome.

| Camada | Registro | Módulo novo | Chave no `input.txt` | Modelo |
|---|---|---|---|---|
| **Compostos** (`compounds_sources.csv`) | `mods/fontes_compostos.py` | `mods/fonte_<nome>.py` | `[bioativos] usar_<nome>` | `mods/fonte_exemplo.py` |
| **Espectros** (`compounds_spectra.csv`) | `mods/espectros.py` | `mods/espectros_<nome>.py` | `[banco] espectros_<nome>` | `mods/espectros_exemplo.py` |

Os dois funcionam igual: o registro varre a pasta `mods/`, reconhece o módulo
pelo nome do arquivo e o chama. A chave do `input.txt` passa a ser aceita
assim que o módulo existe — e só então, para um erro de digitação continuar
sendo erro.

A 26.1 é a camada de compostos; a 26.2, a de espectros.

### 26.1 Camada de compostos: NPAtlas, HMDB, uma base sua

```bash
cp mods/fonte_exemplo.py mods/fonte_npatlas.py
```

```
[bioativos]
usar_npatlas = true
```

#### Antes de tudo: o reino e o escopo

É aqui que quase todo mundo tropeça. Uma base de organismos que **não são
plantas** — bactérias e fungos no NPAtlas, metabólitos humanos no HMDB — só
tem efeito com as duas chaves abaixo:

```
[bioativos]
escopo = completo     # sem isto, só entram organismos que estão no plantas.csv
reino = qualquer      # sem isto, o filtro de reino descarta o que não é planta
```

Com o padrão (`reino = vegetal`), o pipeline confere o gênero de cada
organismo nos gêneros do WFO e do WCVP e descarta o que não é planta **antes**
de a sua fonte entrar no resultado. Isso não é um defeito: é o recorte
declarado deste pipeline. `reino = qualquer` o dispensa.

#### A interface de uma fonte de compostos

```python
FONTE = {
    "nome":    "npatlas",        # vira a chave [bioativos] usar_npatlas
    "rotulo":  "NPAtlas",        # como aparece na tela
    "colunas": ["id_npatlas"],   # colunas extras que a fonte acrescenta ([] se nenhuma)
    "padrao":  False,            # ligada quando a chave não está no input.txt
}

def baixar() -> None:
    """Garante os arquivos em dados_bioativos/. Pode ficar vazia (base por API)."""

def cruzar(casar, especies, generos) -> pandas.DataFrame:
    ...
```

**`casar` é vetorizado** — este é o ponto que mais engana. Ele recebe uma
`Series` com os nomes dos organismos e devolve, para cada um, a chave da
planta-alvo ou `""`. Não chame um nome por vez:

```python
df = pd.DataFrame(registros, columns=["organismo", "composto_id",
                                      "composto_nome", "composto_inchikey"])
df["especie_normalizada"] = casar(df["organismo"], especies, generos)
df = df[df["especie_normalizada"] != ""]        # "" = fora do recorte
```

É dentro de `casar()` que o pipeline aplica o recorte da região e o filtro de
reino. Não filtre por conta própria: passe todos os organismos e descarte as
linhas que voltarem vazias.

**O retorno** é um DataFrame com, no mínimo, `especie_normalizada`, `base`,
`composto_id`, `composto_nome`, `composto_inchikey` e `atividade_ou_alvo`,
mais as colunas declaradas em `FONTE["colunas"]`. O `composto_inchikey` pode
ficar vazio: a etapa `normalizacao` completa pelo PubChem. Um DataFrame vazio
é resposta válida.

Uma exceção dentro de `baixar()` ou de `cruzar()` vira aviso e a etapa segue
sem a base — como já acontece com o Dr. Duke, o LOTUS e o FooDB.

### 26.2 Camada de espectros

#### O caminho mais curto

```bash
cp mods/espectros_exemplo.py mods/espectros_gnps.py
```

Abra o arquivo novo, troque o que está marcado com `TROQUE` no dicionário
`FONTE`, escreva a função `coletar()` e ligue a fonte no `config/input.txt`:

```
[banco]
espectros_gnps = true
```

Confira que o registro reconheceu a fonte, sem rodar o pipeline:

```bash
cd mods && python3 -c "import espectros; print(espectros.resumo())"
```

Rode só a etapa do banco:

```bash
./rodar.sh --somente banco
```

A tela mostra uma linha por fonte, com quantos registros cada uma trouxe.

---

#### A interface de uma fonte de espectros

##### O dicionário `FONTE`

```python
FONTE = {
    "nome":   "gnps",          # vira a chave [banco] espectros_gnps
    "rotulo": "GNPS (MS/MS)",  # como aparece na tela e na coluna `source`
    "rede":   True,            # usa internet?
    "padrao": True,            # ligada quando a chave não está no input.txt
    "ordem":  30,              # ordem de coleta (menor primeiro)
}
```

`nome` e `rotulo` são obrigatórios. Um módulo sem `FONTE` ou sem `coletar()` é
ignorado pelo registro, o que permite ter módulos auxiliares com o mesmo
prefixo.

##### A função `coletar()`

```python
def coletar(compostos, contexto) -> list[dict]:
```

**`compostos`** é um DataFrame com uma linha por composto do banco. Colunas
úteis: `inchikey` (a chave), `pubchem_cid`, `smiles_isomerico`,
`formula_molecular`, `massa_molecular`. Ele **já vem recortado** para a região
quando `[banco] enriquecer_apenas_regiao = true` — não filtre nada por conta
própria.

**`contexto`** é um dicionário com:

| Chave | O que é |
|---|---|
| `admet` | DataFrame do perfil ADMET: massas, carga formal, descritores do RDKit |
| `iks_regiao` | conjunto de InChIKeys da região, ou `None` quando não há recorte |
| `cfg` | a seção `[banco]` do `input.txt`, já convertida |

**O retorno** é uma lista de dicionários, um por registro espectral. Só
`inchikey` é obrigatório, e ele tem de existir em `compounds_identity_master`.
O `spectrum_id` é atribuído pelo registro, não por você.

| Campo | Conteúdo |
|---|---|
| `inchikey` | InChIKey canônico (obrigatório) |
| `origem` | `experimental` ou `teórico` |
| `tipo` | `Mass Spectrometry`, `NMR Spectra`, `IR Spectra`, `UV Spectra`... |
| `subtipo` | `MS-MS`, `GC-MS`, `1D NMR`, `[M+H]+`... |
| `valor` | número — só em dado calculado, como um m/z teórico |
| `descricao` | picos, instrumento, condições (texto) |
| `fonte` | depositante; se você não puser, entra o `rotulo` da fonte |
| `id_fonte` | identificador do espectro na origem (por exemplo o SPLASH) |
| `url` | link para o registro |

> O banco guarda **metadados** de espectro, não o espectro inteiro. É o que
> mantém os CSVs leves e consultáveis. Se a sua fonte traz os picos, ponha um
> resumo em `descricao` e o link em `url`.

### 26.3 Fontes que usam internet

Use sempre o cliente e o cache de `mods/quimio.py`. Eles já tratam limite de
requisições, repetição com espera e servidor fora do ar — e é isso que faz uma
rodada de dias sobreviver a uma instabilidade de uma hora.

```python
import quimio as Q

CACHE = "cache_gnps_espectros.jsonl"

def coletar(compostos, contexto):
    cache = Q.Cache(CACHE)
    faltam = [ik for ik in compostos["inchikey"] if f"e|{ik}" not in cache]
    if faltam:
        cli = Q.Cliente("GNPS", intervalo=0.25)      # segundos entre pedidos
        for ik in faltam:
            r = cli.pedir("GET", f"https://.../spectra?inchikey={ik}")
            if r is None:
                if cli.desistiu:                     # fora do ar: usa o cache
                    break
                continue
            cache.gravar(f"e|{ik}", interpretar(r.json()))
    cache.fechar()
    return [registro for ik in compostos["inchikey"]
            for registro in (cache.get(f"e|{ik}") or [])]
```

Três regras que valem para qualquer fonte nova:

1. **Cache por consulta, em `cache_<nome>_*.jsonl`.** A chave do cache precisa
   conter a consulta exata. Assim a segunda rodada não repete nada, e mudar a
   configuração não reaproveita resultado errado.
2. **Nunca derrube a etapa.** Uma exceção na sua fonte vira aviso e as outras
   seguem — o registro garante isso, mas não conte com ele para erro de
   programação: trate o que você souber tratar.
3. **Respeite o recorte.** Se a sua fonte custa um pedido por composto, ela só
   recebe os compostos da região quando `enriquecer_apenas_regiao = true`.
   Sobre as bases inteiras, um pedido por composto não termina em tempo útil.

### 26.4 Testar sem internet

O jeito mais rápido de validar a interface inteira é uma fonte que não sai da
máquina. Crie o módulo, devolva um registro fictício por composto e rode a
etapa `banco`: se o número de registros espectrais subiu e os
`spectrum_id` continuam únicos e em ordem, o caminho está certo.

```python
FONTE = {"nome": "teste", "rotulo": "Fonte de teste", "rede": False,
         "padrao": True, "ordem": 90}

def coletar(compostos, contexto):
    return [{"inchikey": c["inchikey"], "origem": "experimental",
             "tipo": "Mass Spectrometry", "subtipo": "MS-MS",
             "descricao": "registro de teste"} for _, c in compostos.iterrows()]
```

É o que faz o `mods/espectros_exemplo.py`, que vem no pacote **desligado**
(`"padrao": False`). Para vê-lo em ação:

```
[banco]
espectros_exemplo = true
```

Depois do teste, apague o módulo e a chave — um banco publicado não deve ter
registro fictício.

### 26.5 Conferir que nada mais foi tocado

Esta é a verificação que torna a extensão demonstrável. Antes de criar o
módulo novo, guarde as somas de verificação dos arquivos centrais; depois,
confira:

```bash
md5sum mods/cruzar_especies_bioativos.py mods/gerar_banco.py \
       mods/esquema_banco.py mods/config_pipeline.py > antes.md5
# crie o módulo da fonte, ligue a chave e rode a etapa
#   compostos: ./rodar.sh --somente bioativos
#   espectros: ./rodar.sh --somente banco
md5sum -c antes.md5
```

As quatro têm de sair `OK`. Se alguma mudou, a fonte está encostando em algo que
deveria ser indiferente a ela — e aí o certo é consertar o ponto de extensão,
não o módulo da fonte.

### 26.6 O que entra no esquema publicado

Uma fonte nova **não** muda o esquema: ela preenche a tabela de espectros, que
já existe com as colunas acima, documentadas em `banco/data_dictionary.csv`,
`banco/SCHEMA.md` e `banco/datapackage.json`.

O que vale atualizar à mão, ao publicar, é a **proveniência**: acrescente a
base nova em `FONTES_META`, em `mods/esquema_banco.py`, com título, endereço e
licença. É de lá que sai o `PROVENANCE_AND_LICENSES.md` do banco. Confirme os
termos vigentes de cada fonte na data da coleta: eles mudam entre versões, e a
licença do agregado é limitada pela fonte mais restritiva.

---

## 27. Histórico de mudanças

### Versão 3.20 (atual): `banco/` inteiramente em inglês e ClassyFire por padrão

| Antes | Agora |
|---|---|
| As tabelas de `banco/` saíam em inglês, mas os documentos em prosa e a pasta `banco/qualidade/` ficavam em português | **tudo** em `banco/` acompanha `[banco] idioma_banco`: `SCHEMA.md`, `PROVENANCE_AND_LICENSES.md`, `README.txt`, `data_dictionary.csv` e, em `qualidade/`, os 17 CSVs, os 5 gráficos e o `QUALITY_REPORT.md`, com os cabeçalhos traduzidos. Os valores de `conflict_type` e `severity` também (`unparseable_smiles`, `high`...). Com `idioma_banco = pt` tudo volta ao português |
| `espaco_quimico_umap.csv` usava `inchikey` e `nome_preferido` | `chemical_space_umap.csv`, com `compound_uid` e `preferred_name`, alinhado às demais tabelas |
| O guia de extensão era um arquivo à parte (`EXTENSAO.md`) | virou a **seção 26** deste README, com a numeração interna corrigida e os nomes novos dos metadados do banco. Um documento a menos para manter em sincronia |
| `classyfire_submeter` vinha `false` | vem **`true`**. Produto natural raro muitas vezes não está na base do ClassyFire; sem submeter, esses compostos ficavam sem classe, o que reduzia a cobertura da classificação estrutural e a informação da análise de espaço químico. É mais lento, e o que não terminar numa rodada é recolhido na seguinte |

> A prosa do `QUALITY_REPORT.md` segue em português nos dois modos: ela é o
> documento de análise do autor. Nomes de arquivo, cabeçalhos e referências
> internas acompanham o idioma. A pasta continua se chamando `qualidade/`, para
> não quebrar a detecção de etapa do painel e do `--retomar`.

### Versão 3.19: UMAP, reino configurável e fontes de compostos extensíveis

| Antes | Agora |
|---|---|
| A distribuição do espaço químico era só por ClassyFire e NPClassifier | ganhou a **projeção UMAP** dos fingerprints Morgan (raio 2, 2048 bits, distância de Jaccard), em `banco/qualidade/espaco_quimico_umap.csv` e `g_espaco_quimico_umap.png`, colorida pela superclasse ClassyFire. Semente fixa, portanto reproduzível. Chaves `[banco] umap` e `umap_max`; precisa de `pip install umap-learn` e, sem ele, a etapa avisa e segue |
| O filtro de reino vegetal era fixo no código | virou **`[bioativos] reino`**: `vegetal` (padrão) confere o gênero no WFO/WCVP, `qualquer` aceita bactérias, fungos e metabólitos humanos. É o que permite a uma base como o NPAtlas ou o HMDB ser ligada sem alterar o pipeline |
| As bases de compostos eram uma lista fixa em `cruzar_especies_bioativos.py` | viraram **ponto de extensão**: `mods/fontes_compostos.py` descobre as fontes em `mods/fonte_<nome>.py` e a chave `[bioativos] usar_<nome>` passa a ser aceita sozinha. Dr. Duke, LOTUS e FooDB seguem funcionando como antes; modelo comentado em `mods/fonte_exemplo.py` |

> As três mudanças juntas sustentam a demonstração de extensibilidade: ligar uma base de outro reino (NPAtlas, HMDB) passou a ser criar um módulo em `mods/fonte_<nome>.py` e escrever duas linhas no `input.txt`, sem alterar nenhum arquivo do pipeline. O guia das duas camadas está na seção 26.

### Versão 3.18: escopo do banco e esquema em inglês

| Antes | Agora |
|---|---|
| A etapa `bioativos` só enxergava os compostos das plantas da região: o banco nunca podia cobrir o espaço químico das bases | nova chave **`[bioativos]` `escopo`**. Com `escopo = completo` as bases químicas entram inteiras e a região passa a ser **anotação** (coluna `na_regiao`) em vez de filtro. O padrão segue `regiao`, e o `especies_com_compostos_bioativos.csv` continua igual nele (seção 15.1) |
| — | filtro de **reino vegetal** nos dois escopos: o organismo de cada base química só entra se o gênero estiver nos **gêneros do WFO ou do WCVP**, conferidos no próprio computador. A Flora e Funga do Brasil fica de fora do teste, porque também cataloga fungos e algas |
| — | as etapas caras ficam **restritas à região** mesmo com `escopo = completo`: a `pubmed` sempre (a leitura dos resumos não terminaria em tempo útil sobre as bases inteiras) e as consultas de um pedido por composto ao PubChem conforme **`[banco]` `enriquecer_apenas_regiao`** (padrão `true`). Os gráficos também retratam só a região |
| As 12 tabelas de `banco/` saíam com nomes em português | saem em **inglês** por padrão (`compounds_identity_master.csv`, `compound_uid`, `scientific_name`...), que é o que o repositório permanente e a publicação pedem. **`[banco]` `idioma_banco = pt`** volta aos nomes em português; as planilhas de trabalho da raiz seguem em português nos dois casos; o `dicionario_dados.csv` virou **bilíngue** (`coluna`/`coluna_pt`, `description_en`/`descricao_pt`) |
| A coluna de potência se chamava `pvalor` | `p_activity`, para não ser lida como p-valor estatístico: é −log10(molar) da medida |
| — | `organisms.csv` e `compounds_biological_origin.csv` ganharam `in_region` (`yes`/`no`) |

| A camada espectral do banco era código dentro da etapa `banco` | virou **ponto de extensão**: `mods/espectros.py` descobre as fontes em `mods/espectros_<nome>.py`, e o PubChem e os m/z teóricos do RDKit passaram a ser duas fontes registradas. Acrescentar o GNPS, o MassBank ou o MoNA é criar um módulo — nenhum arquivo existente muda, e a chave `[banco] espectros_<nome>` passa a ser aceita sozinha. Guia na seção 26, modelo comentado em `mods/espectros_exemplo.py` (seção 17-A.4) |
| Resultados só em planilhas e no relatório de gráficos | **painel interativo** `painel.py` (Streamlit), com os lançadores `painel.sh` / `painel.bat`: uma página por etapa, com filtros e download do recorte; **Prospecção** (plantas candidatas cruzando atividade na planta, compostos ativos em artigos e ensaios, evidência, coleta e distribuição); **Ficha** de planta e de composto; banco, ADMET, conflitos e qualidade (seção 20-A). Lê o banco em inglês ou em português, respeita o interruptor *Só as plantas da região* e funciona com etapas faltando e com o modo parcial da etapa 5 |

> As planilhas da v3.17 continuam servindo: sem a coluna `na_regiao`, tudo se
> comporta como `escopo = regiao`. Para passar ao escopo completo, rode
> `--a-partir-de bioativos`.
>
> O painel não altera nenhuma planilha e não acessa a internet (só na primeira
> vez, para instalar o `streamlit` no ambiente do pipeline). Nenhum script de
> `mods/` depende dele.

### Versão 3.17: banco relacional, InChIKey canônico, ADMET e qualidade

Três etapas novas depois do `pubmed`, que transformam os CSVs "largos" das
etapas anteriores num **banco relacional** normalizado e documentado:

| Etapa | Script | O que faz |
|---|---|---|
| 6 `normalizacao` | `normalizar_compostos.py` | normaliza os identificadores pelo **PubChem** e classifica a estrutura pelo **ClassyFire**; deduplica tudo por **InChIKey canônico**, preservando a rastreabilidade de cada ocorrência e **detectando e registrando conflitos** entre bases |
| 7 `banco` | `gerar_banco.py` | monta **12 CSVs relacionais interligados por InChIKey** (identidade química, fontes, sinônimos, origem biológica, distribuição, bioatividade, vias, espectros, ADMET, conflitos), com **dicionário de dados**, `ESQUEMA.md` e `datapackage.json`; calcula **drogabilidade e ADMET básico** (RDKit) de todo composto com SMILES |
| 8 `qualidade` | `analisar_qualidade.py` | analisa **completude por base, espaço químico (ClassyFire), cobertura taxonômica, sobreposição entre bases (Jaccard) e vieses de curadoria** |

Outras mudanças:

| Antes | Agora |
|---|---|
| A etapa `bioativos` só gravava `especies_com_compostos_bioativos.csv` | grava também `ocorrencias_compostos_bruto.csv`: **um registro por base × planta**, antes da consolidação, com o que *aquela* base informa (é a entrada da rastreabilidade da etapa `normalizacao`) |
| RDKit era opcional só para conferir SMILES | continua opcional, mas agora é **recomendado**: sem ele não há recálculo de InChIKey, perfil ADMET nem detecção de conflitos de estrutura (o pipeline avisa e segue) |
| `input.txt` sem seção `[banco]` | nova seção **`[banco]`** controla PubChem, ClassyFire, vias, espectros e ADMET-AI (seção 7.4) |

> O banco fica na pasta **`banco/`** e segue o padrão *Frictionless Data*
> (`datapackage.json` com chaves primárias e estrangeiras). Valide com
> `pip install frictionless && frictionless validate banco/datapackage.json`.

O banco é **FAIR**: InChIKey como identificador canônico, metadados de descoberta
e esquema legível por máquina no `datapackage.json`, identificadores externos
padronizados, proveniência por registro em `compounds_sources.csv` e, em
`PROVENIENCIA_E_LICENCAS.md`, a licença do banco (**CC-BY-SA-4.0**) e os termos de
cada base de origem.

### Versão 3.16: Qwen como modelo padrão

| Antes | Agora |
|---|---|
| Modelo padrão `llama3.1:8b` | padrão `qwen3.5:35b-a3b` (MoE: julga melhor e, com só ~3B parâmetros ativos, é rápido na GPU); alternativas e memória necessária na seção 4.3. Quem já tem `modelo = …` no `input.txt` continua com o que escreveu |
| Textos falavam em "Llama" | falam em "modelo" ou "Ollama", qualquer que seja o modelo escolhido; o status das planilhas parciais virou `leitura pelo modelo pendente` (os gráficos reconhecem também o texto antigo) |
| Aviso de modelo pequeno só para modelos de 1B | vale para modelos de 1B a 4B |

> **Ao trocar de modelo**, o cache de julgamentos (`cache_llm_classificacao.jsonl`)
> não é reaproveitado, porque o modelo faz parte da chave: os resumos são
> lidos de novo pelo modelo novo. Os resumos e buscas já baixados continuam valendo.

### Versão 3.15: modelos com raciocínio

| Antes | Agora |
|---|---|
| Modelos que "raciocinam" antes de responder (Qwen 3.5/3.6, gpt-oss...) ficariam muito lentos e podiam estourar o limite da resposta | opção `pensar` em `[ollama]` (padrão `false`): o pipeline pede ao Ollama para desligar o raciocínio; se o Ollama for antigo e recusar a opção, a chamada é refeita sem ela |

### Versão 3.14: modelo em paralelo

| Antes | Agora |
|---|---|
| O modelo lia um par entidade × resumo de cada vez, e a GPU ficava ociosa entre um pedido e outro | opção `paralelo` em `[ollama]` (padrão 4): vários pedidos simultâneos ao Ollama, cada resposta gravada no cache assim que chega (Ctrl+C não perde as já respondidas). Requer `OLLAMA_NUM_PARALLEL` no Ollama (seção 17) |
| Sem teto para o tamanho da resposta; o modelo podia ser descarregado entre pedidos | `num_predict = 512` (o JSON pedido é bem menor) e `keep_alive = 30m`. As classificações já em cache continuam valendo (o prompt não mudou) |

### Versão 3.13: NCBI e PubChem instáveis

| Antes | Agora |
|---|---|
| Com o NCBI devolvendo erro 500 em série, cada busca da etapa `pubmed` gastava ≈ 45 s em novas tentativas antes de falhar, e a etapa seguia assim por horas (estimativas de centenas de horas) | depois de 10 falhas seguidas, pausa de 10 min; depois de 3 pausas sem melhora, a fase é encerrada e a etapa segue com o que já está em cache. Vale para as buscas, o download de resumos, os vínculos e o filtro por atividade (NCBI) e as consultas ao PubChem |
| As mensagens de erro mostravam a chave do NCBI (`api_key=…`) | a chave aparece como `api_key=***` |

### Versão 3.12: correção para o pandas 3

| Antes | Agora |
|---|---|
| Na etapa `bioativos`, depois das consultas ao PubChem, a etapa caía com `TypeError: Invalid value for dtype 'str'` quando o cache tinha algum valor que não era texto (pandas 3, cujas colunas de texto recusam outros tipos) | o cache só aceita texto como SMILES; as colunas de SMILES e a tabela consolidada usam tipo genérico, e as atribuições não dependem mais do índice. Testado com pandas 3.0.5 e 3.1.1 |

### Versão 3.11: depuração e README revisado

| Antes | Agora |
|---|---|
| Sem credenciais do GBIF, o pedido em SQL dos estados (opcional) derrubava a etapa `gbif` inteira | vira só um aviso; a etapa termina normalmente |
| O pedido em SQL repetia 4 tentativas, com pausas de até 3 min, quando o GBIF não respondia | 2 tentativas: é opcional e é refeito na próxima rodada |
| Um SMILES inválido de uma fonte podia virar o `composto_smiles` (quando era a única com estrutura, ou a primeira na ordem) | com o RDKit, o SMILES de cada fonte é validado: o inválido é pulado em favor da próxima fonte válida e marcado em `conferencia_smiles` (`SMILES inválido: LOTUS`) |
| Mensagens do `graficos.py` mostravam só comandos do Linux | mostram `rodar.bat` / `graficos.bat` no Windows |
| README com trechos de versões anteriores (nomes "intactos", modelo na etapa `plantas`, exemplo de sinônimos em duas linhas) | revisado: distribuição por estado, SMILES por fonte, gráficos automáticos, novas mensagens em *Solução de problemas*, limitações e bases (GADM, RDKit) |

### Versão 3.10: estados também pelo GBIF

| Antes | Agora |
|---|---|
| Plantas sem estado na Flora e Funga do Brasil ficavam com `distribuição desconhecida` | a etapa `gbif` pede ao GBIF, uma vez, uma tabela espécie × estado (download em SQL, já agregado: registros georreferenciados de plantas no Brasil, estado pelas coordenadas, divisão GADM) → `especies_gbif_estados.csv`. A etapa `plantas` a usa só para as plantas sem estado na Flora, pela `speciesKey` ou pelo nome; a Flora continua com prioridade |
| — | coluna `registros_gbif_por_uf` (ex.: `AM 12; PA 3`) quando o estado veio do GBIF |
| — | opção `estados_gbif` em `[taxonomia]` (padrão `true`). O download em SQL é um recurso experimental do GBIF: se falhar, a etapa avisa e segue só com a Flora |

### Versão 3.9: distribuição por estado

| Antes | Agora |
|---|---|
| Sem informação de onde, no Brasil, cada planta ocorre | `plantas.csv` ganha `estados_br`, `dominios_br`, `endemismo_br`, `origem_br` e `fonte_distribuicao`, da Flora e Funga do Brasil já baixada (sem internet). Procura pelo nome da linha, pelo nome aceito e pelos sinônimos de `nomes_busca`; sem nada na Flora, `distribuição desconhecida` |
| — | `estados_composto` (união dos estados das plantas em que o composto ocorre) em `especies_com_compostos_bioativos.csv` e `atividades_compostos.csv`; `estados_br` e afins em `atividades_plantas.csv` |
| — | gráfico *Plantas por estado* e os números "com estado(s) conhecido(s)" e "endêmicas do Brasil" na etapa `plantas` |

### Versão 3.8: SMILES de mais compostos

| Antes | Agora |
|---|---|
| SMILES só do COCONUT e do NPASS (cerca de 82% dos compostos) | os compostos que eles não têm recebem o SMILES do LOTUS (arquivo já baixado) e, se ainda faltar, o do PubChem (só os que têm InChIKey; `smiles_pubchem` em `[bioativos]`). COCONUT e NPASS continuam com prioridade. Nos dados de teste reais, a cobertura estimada sobe para cerca de 92%; os que ficam sem estrutura são, em geral, compostos do Dr. Duke sem InChIKey (nomes genéricos ou de misturas) |
| Não se sabia de onde vinha cada SMILES | coluna nova `fonte_smiles` em `especies_com_compostos_bioativos.csv` e em `atividades_compostos.csv` |
| `atividades_compostos.csv` sem a estrutura | colunas `smiles` e `fonte_smiles` |
| Só um SMILES por composto | uma coluna por fonte (`smiles_npass`, `smiles_coconut`, `smiles_lotus`, `smiles_pubchem`, esta para todos os compostos com InChIKey) e `conferencia_smiles`, que compara as estruturas das quatro com o RDKit (opcional, instalado pelo instalador) e aponta só as divergências reais, dizendo quais fontes concordam |
| O SMILES escolhido de um composto podia variar de uma planta para outra (vindo de bases diferentes) | o mesmo em todas as linhas do composto, na ordem NPASS > COCONUT > LOTUS > PubChem |
| O LOTUS só trazia a referência (DOI) | traz também o nome comum e o CID do PubChem dos compostos que só ele registra |
| — | gráfico novo na etapa `bioativos`: *Origem da estrutura (SMILES)*, e o número-chave "compostos com SMILES" |

### Versão 3.7: gráficos ao fim das etapas

| Antes | Agora |
|---|---|
| Os gráficos só eram gerados rodando `./graficos.sh` à parte | o pipeline gera os gráficos ao terminar as etapas `plantas`, `bioativos`, `chembl` e `pubmed` (a etapa e a visão geral) e atualiza `graficos/relatorio.html`; `--sem-graficos` desliga |
| Rodar `./graficos.sh --etapas X` deixava no relatório só a etapa X | o relatório acumula: as etapas não refeitas continuam nele, com os gráficos anteriores (`graficos/dados/_relatorio.json`) |
| O `matplotlib` era instalado pelo `graficos.sh` na primeira vez | entra no `requirements.txt` e é instalado pelo `instalar.sh` / `instalar.bat` |
| `graficos.sh` / `graficos.bat` só conheciam a `.venv` | reconhecem também a `.venv-linux` / `.venv-win` (pasta compartilhada entre sistemas) |

### Versão 3.6: Windows e Linux

| Antes | Agora |
|---|---|
| No Windows, um CSV aberto no Excel durante a gravação derrubava a etapa (`PermissionError`) | a etapa avisa ("feche o arquivo") e continua sozinha quando ele é liberado |
| Pastas com arquivos somente leitura (comum no Windows) não eram apagadas ao atualizar uma base | apagadas mesmo assim; se algum arquivo estiver aberto, a mensagem diz qual pasta |
| Mensagens mandavam usar `GBIF_DOWNLOAD_KEY=... ./rodar.sh`, sintaxe que não existe no Windows | opção `--gbif-chave`, igual nos dois sistemas; as mensagens mostram `rodar.bat` ou `./rodar.sh` conforme o sistema |
| Com `--gbif-chave` e o zip já baixado, a etapa ainda esperava o GBIF responder | usa o zip local direto |
| Com o GBIF fora do ar, nomes populares, ocorrências e conferência de nomes esperavam por cada uma de milhares de consultas (horas) | depois de várias falhas seguidas, a etapa para de consultar e segue; o que faltou é buscado na próxima rodada |
| Uma falha de rede ao buscar o nome popular ficava gravada no cache como "sem nome popular" | falhas não vão para o cache |
| `instalar.bat` não conferia a versão do Python, caía no atalho falso da Microsoft Store e dizia "Pronto" mesmo com erro no `pip` | usa o lançador `py` quando existe, exige Python 3.10+, explica o atalho da Store e para com mensagem clara se o `pip` falhar |
| A mesma pasta usada no Windows e no Linux: o `.venv` de um sistema estragava o do outro | `.venv-win` / `.venv-linux` quando necessário |
| Saída redirecionada para arquivo no Windows (`> log.txt`) podia quebrar com nomes como "(1→2)" | a saída é sempre UTF-8, e um caractere impossível vira "?" em vez de erro |

### Versão 3.5: GBIF lento e FooDB

| Antes | Agora |
|---|---|
| Se o GBIF demorasse mais de 60 s para aceitar o pedido de download (comum com polígonos grandes), a etapa `gbif` parava com erro | espera até 5 min; sem resposta, confere nos pedidos recentes da sua conta se o pedido foi criado mesmo assim (evita pedidos duplicados) e tenta de novo até 4 vezes |
| O GBIF sobrecarregado (HTTP 503 "Backend fetch failed" ou 429) interrompia a etapa | tratado como lentidão: confere se o pedido foi criado e tenta de novo |
| Um pedido da mesma área escrito com outra precisão de coordenadas não era reconhecido | a região é comparada pelas coordenadas; se só houver download da mesma área com outro filtro de países, a etapa avisa e mostra a chave |
| Com o GBIF fora do ar, o pedido anterior da região era ignorado e um novo era aberto | o pedido anterior é reaproveitado; se o arquivo dele já estiver em `dados_gbif_download/`, nem consulta o GBIF |
| O FooDB recusava o download automático (HTTP 403) sem dizer o que fazer | o download imita um navegador; se ainda for recusado, a mensagem diz onde salvar o arquivo baixado à mão (`dados_bioativos/foodb_csv.tar.gz`) |

### Gráficos (para as versões 3 a 3.4)

| Mudança | Detalhe |
|---|---|
| Gráficos dos resultados | `graficos.py`, com os lançadores `graficos.sh` / `graficos.bat`: cerca de 40 gráficos, da visão geral à etapa 5, num relatório `graficos/relatorio.html`, com a tabela de cada gráfico em `graficos/dados/` (seção 20) |
| Nomes não reconhecidos em destaque | no gráfico *Plantas mais citadas nos artigos*, os nomes `não reconhecido` aparecem em cinza, com legenda; a tabela do gráfico traz a coluna `situacao_nome` |
| Compatível com a versão 3.1 | lê as colunas novas (`nome_aceito`, `linha_em_plantas_csv`), o WCVP nos vereditos, as situações novas (`sinônimo`, `grafia variante`, `homônimo ambíguo`, nomes da lista mantidos) e o `plantas_descartados.csv`, com dois gráficos novos. As saídas da versão 3 continuam sendo lidas |
| Compatível com a versão 3.2 | com `[termos_pubmed]` vazia, a anotação "atividade biológica (geral)" vira o gráfico das plantas com mais artigos sobre atividade biológica |
| Compatível com a versão 3.3 | a situação nova "aceito (nas fontes só sinônimo ou grafia variante)" aparece no gráfico *Situação dos nomes*; o relatório passa a mostrar quantas linhas reúnem vários nomes (`nomes_juntados`) |
| Versão 3.4 | sem mudança de formato: os gráficos leem as saídas como estão; os nomes de compostos corrigidos e completados pela 3.4 aparecem nos rankings (nomes IUPAC longos são abreviados com "…") |
| Pipeline inalterado | os gráficos só leem as planilhas e o cache do modelo; nenhum script de `mods/` mudou. O `matplotlib` é instalado no `.venv` pelo próprio `graficos.sh` |

### Versão 3.4: depuração

| Antes | Agora |
|---|---|
| Ao juntar sinônimos, `speciesKey`, filo, classe, ordem e nome popular vinham do primeiro nome do GBIF encontrado, às vezes um sinônimo com chave própria | vêm da linha do GBIF do próprio nome aceito, quando ela existe |
| Nomes de compostos com caracteres corrompidos na origem (COCONUT), como "( inverted exclamation markA)-Acuminatin" | corrigidos: "(±)-Acuminatin", "6′-Hydroxy…", "(1→2)" |
| Cerca de 15% dos pares sem nome de composto | o nome passa de uma base para outra pelo InChIKey; sem nome comum no COCONUT, usa o nome IUPAC |
| CID e SMILES de uma base (ex.: NPASS) não chegavam às linhas de outra (ex.: COCONUT) com o mesmo composto | passam de uma base para outra pelo InChIKey |

### Versão 3.3: uma linha por espécie aceita

| Antes | Agora |
|---|---|
| Cada nome da sua lista tinha a própria linha, mesmo quando dois nomes eram a mesma espécie (ex.: *Lippia origanoides* em 12 linhas), e os compostos se repetiam no cruzamento | todos os nomes da mesma espécie aceita (lista, GBIF e artigos) viram uma linha, com o nome aceito em `nome_cientifico`; os demais vão para `nomes_juntados` e `nomes_busca` |
| O sinal de híbrido colado ao epíteto, como a Flora escreve (*Citrus ×limon*), era perdido, e o próprio nome aceito aparecia como "sinônimo" | reconhecido em todas as formas (`×limon`, `× limon`, `x limon`) e escrito como *Citrus × limon* |

### Versão 3.2: correções de colunas vazias

| Antes | Agora |
|---|---|
| `atividades_artigos` (em `plantas.csv`) ficava 100% vazia quando `[termos_pubmed]` estava vazia | sem atividades-foco, cada planta citada em artigos da região é anotada com a atividade biológica geral (mesmos termos do filtro geral da etapa 5) e o nº de artigos |
| `pubchem_cid` (em `especies_com_compostos_bioativos.csv`) saía vazia: só eram aceitos CIDs escritos só com dígitos | o CID do NPASS é lido em qualquer formato (`5280343.0`, `CID:5280343`, listas), também na tabela de estrutura; o que faltar é completado com o cache do PubChem da etapa 5 (`cache_pubchem_cid.jsonl`). A etapa mostra quantos CIDs leu e, se nenhum, as colunas e exemplos de valores do arquivo |
| Um `especies_gbif.csv` gerado pela v3 (sem nenhuma `speciesKey`) continuava sendo usado e deixava `speciesKey` vazio nas plantas vindas do GBIF | a etapa `plantas` detecta o arquivo antigo e o refaz a partir do download do GBIF já baixado (sem novo pedido); com `--retomar`, as etapas `gbif` e `plantas` são refeitas automaticamente nesse caso |

### Versão 3.1: nova etapa `plantas`

| Antes | Agora |
|---|---|
| Os nomes eram trocados pelo nome aceito, inclusive os da sua lista | **nenhum nome é trocado**; os da sua lista ficam exatamente como estão. O nome aceito vai para a coluna nova `nome_aceito` |
| A correção de grafia às vezes trocava a espécie (*Linum bahiense* → *L. bahamense*; *Solenopsis geminata* → *S. minuta*; "Eucalyptus branches" → *E. burgessiana*) | só os epítetos são comparados, e só contam como a mesma palavra as variantes do Código de Nomenclatura, outra terminação ou uma letra de diferença; o resto vira sugestão. Vale também para o GBIF |
| Homônimos levavam à espécie errada (*Schedonorus arundinaceus* → *Scolochloa festucacea*) | vale o destino de mesmo epíteto; se não houver um só, o nome fica como `homônimo ambíguo` |
| Uma grafia aproximada da Flora vencia uma resposta exata do WFO ou do GBIF | a resposta exata de qualquer base vale mais |
| Família de homônimo de outro reino (*Pleroma* em Kinnaridae) | família da Flora/WFO; classificação e `speciesKey` do GBIF só se a família coincidir |
| Cerca de 17 mil "nomes" dos artigos eram pares de palavras ou outros organismos | o gênero precisa existir na Flora, no WFO ou no WCVP, e o nome precisa ser reconhecido como planta por uma das quatro bases; os descartados e o motivo vão para `plantas_descartados.csv` |
| Duplicatas da mesma espécie com nomes diferentes | nomes do GBIF e dos artigos entram na linha do nome da sua lista (ou, entre si, viram uma linha só); os outros nomes vão para a coluna nova `nomes_juntados`. Cada espécie da sua lista mantém a própria linha |
| Três bases taxonômicas | quatro: entra o WCVP (Kew), lista mundial de plantas vasculares |
| `speciesKey` vazio na maioria das linhas | o backbone novo do GBIF usa chaves alfanuméricas (ex.: `549R6`), que eram descartadas ao serem convertidas em número; agora são guardadas como texto |
| Variedades e subespécies em linhas próprias, e na etapa `bioativos` um sinônimo levava o composto a uma só linha | uma linha por espécie (gênero + epíteto), com as variedades em `nomes_busca`; a etapa `bioativos` busca só por `nomes_busca`, salva os compostos por espécie, e um nome presente em várias linhas leva o composto a todas |
| Polígono passando da fronteira trazia espécies só dos países vizinhos | opção `pais` em `[regiao]` (ex.: `pais = BR`) |
| Sinônimos só entravam na busca se alguma fonte os citasse | `nomes_busca` recebe também os sinônimos (não ambíguos) que a Flora, o WFO e o WCVP conhecem para cada espécie |
| Registros do GBIF só de gênero viravam linhas | ficam de fora, em `plantas_descartados.csv` |

Mudanças de colunas em `plantas.csv`: entram `nome_aceito` e
`nomes_juntados`; sai `nome_original` (os nomes originais estão em
`nome_cientifico` e `nomes_juntados`). As etapas seguintes já foram
ajustadas.

**O `input.txt` da versão 3 continua valendo**, sem mudança: as chaves novas
(`pais` em `[regiao]`; `usar_wcvp` e `wcvp_url` em `[taxonomia]`) têm valor
padrão. Para usar a versão nova, rode a etapa `downloads` (baixa o WCVP) e
refaça a partir de `plantas` (ou de `gbif`, se acrescentar `pais`):
`./rodar.sh --somente downloads` e `./rodar.sh --a-partir-de plantas
--pular-downloads`.

Os caches da conferência de nomes feitos com as regras antigas não são
reaproveitados: na primeira rodada, os nomes são reconferidos nas listas
locais (minutos) e só as respostas aproximadas antigas do GBIF são
consultadas de novo. Depois, rode a partir da etapa `plantas`
(`--a-partir-de plantas`).

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
| Etapa 5 mais rápida | PubChem em lotes; pré-checagem com todas as atividades juntas; plantas lidas pelo modelo antes dos compostos |
| Acompanhamento | `./rodar.sh parcial` (sem internet, em arquivos `*_parcial.csv`) e `./rodar.sh diagnostico` |
| Robustez | gravação atômica das planilhas e das extrações; falhas de rede não viram "nenhum artigo"; cache dos nomes populares do GBIF; espera do GBIF tolerante a falhas passageiras |

### Versão 2

Região como círculo, retângulo ou polígono; todo o controle num só
`input.txt` validado; só plantas e só registros de presença no GBIF; lista
do usuário mais plantas de artigos; nomes conferidos em três bases; busca
por todos os nomes da planta; COCONUT completo; etapa de downloads
separada; ChEMBL pelo InChIKey com estereoisômeros; PubMed julgado pelo
modelo, com tipo de estudo e parte da planta; planilhas por planta, por
composto e combinada.
