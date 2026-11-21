"""
espectros_exemplo.py  -  MODELO de fonte espectral (desligada por padrão)

Copie este arquivo para mods/espectros_<nome>.py, troque o que está marcado
com "TROQUE" e ligue a fonte no input.txt:

    [banco]
    espectros_<nome> = true

Nenhum outro arquivo do pipeline precisa ser alterado: o registro em
espectros.py descobre o módulo pelo nome. O guia completo, com o que cada
coluna significa e como testar sem rede, está na seção 26 do README.

Para conferir que a fonte foi reconhecida, sem rodar o pipeline:

    cd mods && python3 -c "import espectros; print(espectros.resumo())"

Esta fonte de exemplo devolve UM registro fictício por composto, só para o
desenvolvedor ver o caminho inteiro funcionando. Ela fica DESLIGADA por
padrão ("padrao": False) para não sujar o banco de ninguém.
"""

FONTE = {
    "nome": "exemplo",                      # TROQUE: vira [banco] espectros_<nome>
    "rotulo": "Fonte de exemplo (fictícia)",  # TROQUE: como aparece na tela
    "rede": False,                          # TROQUE: True se consultar a internet
    "padrao": False,                        # TROQUE: True para vir ligada
    "ordem": 90,                            # ordem de coleta (menor primeiro)
}

# Com rede, use sempre o cliente e o cache do quimio.py: eles já tratam
# limite de requisições, repetição e servidor fora do ar.
#
#   import quimio as Q
#   CACHE = "cache_<nome>_espectros.jsonl"
#
#   cache = Q.Cache(CACHE)
#   cli = Q.Cliente("<Nome>", intervalo=0.25)   # segundos entre pedidos
#   ...
#   r = cli.pedir("GET", f"https://exemplo.org/api/spectra?inchikey={ik}")
#   if r is None and cli.desistiu:              # desistiu: use só o cache
#       break
#   cache.gravar(f"e|{ik}", registros)
#   cache.fechar()


def coletar(compostos, contexto: dict) -> list:
    """Registros espectrais dos compostos recebidos.

    compostos: DataFrame com uma linha por composto. Colunas úteis:
        inchikey           InChIKey canônico (a chave do banco)
        pubchem_cid        CID, quando existe
        smiles_isomerico   estrutura
        formula_molecular  fórmula
    Já vem recortado para a região quando [banco] enriquecer_apenas_regiao
    = true, então não é preciso filtrar nada aqui.

    contexto: {"admet": DataFrame do perfil ADMET (massas, carga formal),
               "iks_regiao": set de InChIKeys da região ou None,
               "cfg": seção [banco] do input.txt}

    Devolve: lista de dicionários. Colunas de dados_espectrais (todas
    opcionais, menos inchikey; o id_espectro é atribuído pelo registro):
        inchikey   obrigatório, tem de existir em compostos.csv
        origem     "experimental" ou "teórico"
        tipo       "Mass Spectrometry", "NMR Spectra", "IR Spectra"...
        subtipo    "MS-MS", "GC-MS", "1D NMR", "[M+H]+"...
        valor      número (use só em dado calculado, como um m/z teórico)
        descricao  picos, instrumento, condições (texto)
        fonte      depositante; se você não puser, entra o rótulo da fonte
        id_fonte   identificador do espectro na origem (ex.: SPLASH)
        url        link para o registro
    """
    if compostos is None or compostos.empty:
        return []
    linhas = []
    for _, c in compostos.iterrows():
        linhas.append({
            "inchikey": c["inchikey"],
            "origem": "experimental",
            "tipo": "Mass Spectrometry",
            "subtipo": "MS-MS",
            "descricao": "registro fictício, só para demonstrar a interface",
            "id_fonte": f"EXEMPLO-{c['inchikey'][:14]}",
            "url": None,
        })
    return linhas
