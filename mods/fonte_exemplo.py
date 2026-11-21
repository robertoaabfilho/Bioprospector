"""
fonte_exemplo.py  -  MODELO de fonte de compostos (desligada por padrão)

Use este arquivo para ligar ao banco uma base de pares organismo-composto que
ainda não vem no pacote: NPAtlas, HMDB, uma base própria do seu laboratório.

    cp mods/fonte_exemplo.py mods/fonte_npatlas.py

Troque o que está marcado com "TROQUE", escreva baixar() e cruzar(), e ligue
no input.txt:

    [bioativos]
    usar_npatlas = true

Nenhum arquivo já existente do pipeline precisa ser alterado. O guia completo
está na seção 26 do README; o modelo da camada de espectros é
espectros_exemplo.py.

ATENÇÃO AO REINO
----------------
Se a sua base traz organismos que NÃO são plantas (bactérias e fungos no
NPAtlas, metabólitos humanos no HMDB), ela só terá efeito com:

    [bioativos]
    escopo = completo        # sem isto, só entram organismos do plantas.csv
    reino = qualquer         # sem isto, o filtro de reino descarta não-plantas

Com o padrão (`reino = vegetal`), o pipeline confere o gênero de cada
organismo nos gêneros do WFO e do WCVP e descarta o que não é planta - antes
de a sua fonte ser consultada.

Para conferir que a fonte foi reconhecida, sem rodar o pipeline:

    cd mods && python3 -c "import fontes_compostos as F; print(F.resumo())"
"""

import pandas as pd

FONTE = {
    "nome": "exemplo",                   # TROQUE: vira [bioativos] usar_<nome>
    "rotulo": "Base de exemplo (fictícia)",  # TROQUE: como aparece na tela
    "colunas": ["id_exemplo"],           # TROQUE: colunas extras ([] se nenhuma)
    "padrao": False,                     # TROQUE: True para vir ligada
}

# Sigla da base, que vai para a coluna `base` de cada linha e para
# compounds_sources.source_db. Use maiúsculas, sem espaço.
BASE = "EXEMPLO"


def baixar() -> None:
    """Garante os arquivos da base em dados/bioativos/.

    Chamada antes de cruzar(). Use requests + o cache do pipeline, ou deixe
    vazia se a sua base for consultada por API dentro de cruzar().
    Uma exceção aqui vira aviso: a etapa segue sem esta base.
    """
    return None


def cruzar(casar, especies: dict, generos: dict) -> pd.DataFrame:
    """Pares organismo-composto desta base, no formato da etapa bioativos.

    casar(nomes, especies, generos) -> pandas.Series
        VETORIZADO: recebe uma Series com os nomes dos organismos da sua base
        e devolve, para cada um, a chave da planta-alvo ou "" quando o
        organismo não entra. É aqui que o pipeline aplica o recorte da região
        e o filtro de reino, então NÃO filtre por conta própria: passe todos
        os organismos e descarte as linhas que vierem "".
    especies, generos
        Índices das plantas-alvo. Repasse-os a casar() como estão.

    Devolve um DataFrame com, no mínimo:
        especie_normalizada  o que casar() devolveu
        base                 a sigla desta base
        composto_id          identificador do composto nesta base
        composto_nome        nome do composto nesta base
        composto_inchikey    InChIKey, se a base tiver (pode ficar vazio;
                             o pipeline completa pelo PubChem depois)
        atividade_ou_alvo    atividade ou alvo, se houver (pode ficar vazio)
    mais as colunas declaradas em FONTE["colunas"].

    Um DataFrame vazio é resposta válida (base sem correspondência).
    """
    colunas = ["especie_normalizada", "base", "composto_id", "composto_nome",
               "composto_inchikey", "atividade_ou_alvo"] + FONTE["colunas"]

    # --- TROQUE daqui para baixo: leia a sua base e monte as linhas ---------
    # (organismo, id do composto, nome do composto, InChIKey)
    registros = [
        # ("Streptomyces griseus", "EX-1", "Estreptomicina", "UCSJYZPVAKXKNQ-HZYVHMACSA-N"),
    ]
    if not registros:
        return pd.DataFrame(columns=colunas)

    df = pd.DataFrame(registros, columns=["organismo", "composto_id",
                                          "composto_nome", "composto_inchikey"])
    # uma chamada só, com a coluna inteira: casar() é vetorizado
    df["especie_normalizada"] = casar(df["organismo"], especies, generos)
    df = df[df["especie_normalizada"] != ""]      # "" = fora do recorte
    df = df.assign(base=BASE, atividade_ou_alvo="", id_exemplo=df["composto_id"])
    # -----------------------------------------------------------------------

    return df.reindex(columns=colunas)
