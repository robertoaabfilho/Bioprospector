# Como acrescentar uma fonte de dados ao pipeline

Guia para quem vai ligar uma base nova ao banco — por exemplo o **GNPS**, o
**MassBank Europe** ou o **MoNA** na camada espectral.

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

A seção 2 é a camada de compostos; a seção 3, a de espectros.

---

## 2. Camada de compostos: NPAtlas, HMDB, uma base sua

```bash
cp mods/fonte_exemplo.py mods/fonte_npatlas.py
```

```
[bioativos]
usar_npatlas = true
```

### 2.1 Antes de tudo: o reino e o escopo

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

### 2.2 A interface

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

---

## 3. Camada de espectros

### 3.1 O caminho mais curto

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

### 3.2 A interface

#### O dicionário `FONTE`

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

#### A função `coletar()`

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

---

## 4. Fontes que usam internet

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

---

## 5. Testar sem internet

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

---

## 6. Conferir que nada mais foi tocado

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

---

## 7. O que entra no esquema publicado

Uma fonte nova **não** muda o esquema: ela preenche a tabela de espectros, que
já existe com as colunas acima, documentadas em `banco/dicionario_dados.csv`,
`banco/ESQUEMA.md` e `banco/datapackage.json`.

O que vale atualizar à mão, ao publicar, é a **proveniência**: acrescente a
base nova em `FONTES_META`, em `mods/esquema_banco.py`, com título, endereço e
licença. É de lá que sai o `PROVENIENCIA_E_LICENCAS.md` do banco. Confirme os
termos vigentes de cada fonte na data da coleta: eles mudam entre versões, e a
licença do agregado é limitada pela fonte mais restritiva.
