"""
config_pipeline.py

Módulo compartilhado (não é executado diretamente) que lê o
config/input.txt, arquivo de configuração do pipeline:

  [coordenadas]    região geográfica
  [taxons]         gêneros/espécies do usuário
  [termos_pubmed]  atividades de interesse (opcional)
  [artigos] [ollama] [pubmed] [bioativos] [chembl] [banco]   parâmetros (opcionais)

O caminho pode ser trocado pela variável de ambiente PIPELINE_INPUT
(main.py --input faz isso).

Estrutura de pastas do projeto:
  README.md
  config/   input.txt, lista_de_plantas.txt, credenciais do GBIF
  mods/     scripts .py
  (raiz)    bases baixadas (dados_*), caches (cache_*.jsonl) e resultados (*.csv)
Ao ser importado, este módulo muda o diretório de trabalho para a raiz do
projeto: os scripts podem ser chamados de qualquer pasta.

Funções principais:
  ler_input()                 -> {"pontos", "raio_km", "taxons",
                                  "termos_pubmed", "config"}
  geometria_da_regiao()       -> {"wkt", "tipo", "descricao", "bbox"}
  carregar_config_ollama()    -> modelo/url/timeout do modelo local
  carregar_config_pubmed()    -> limites da busca no PubMed
  carregar_config_bioativos() -> opções do cruzamento COCONUT/NPASS

Execute `python mods/config_pipeline.py` para conferir o que está sendo lido.
"""

import math
import os
import sys
import time
import re
from pathlib import Path

# Sistema operacional: só muda as dicas de comando mostradas na tela
NO_WINDOWS = os.name == "nt"
COMANDO = r"mods\rodar.bat" if NO_WINDOWS else "mods/rodar.sh"   # lançador (rodado da raiz do projeto)

# Saída de texto que nunca derruba uma etapa: no Windows, com a saída
# redirecionada para arquivo (> log.txt) e sem PYTHONUTF8, a codificação é a
# cp1252, que não tem "→", "′" etc. (nomes de compostos). Caractere que não
# couber vira "?" em vez de UnicodeEncodeError.
for _fluxo in (sys.stdout, sys.stderr):
    try:
        if not _fluxo.isatty():
            _fluxo.reconfigure(encoding="utf-8", errors="replace")
        else:
            _fluxo.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

import caminhos as _C  # noqa: E402

PASTA_MODS = _C.MODS
PASTA = _C.RAIZ                           # raiz do projeto
PASTA_CONFIG = _C.CONFIG
if _C.layout_antigo() and not os.environ.get("PIPELINE_SEM_CONFERIR_PASTAS"):
    sys.exit("A pasta do projeto ainda está no formato antigo (caches, planilhas e bases soltos na "
             "raiz: " + ", ".join(_C.layout_antigo()[:5]) + " ...).\nOrganize-a uma vez com:  "
             + (r"mods\organizar_pasta.bat" if NO_WINDOWS else "mods/organizar_pasta.sh"))
_C.criar_pastas()
# a pasta de trabalho é resultados/: as planilhas são gravadas lá pelo nome;
# caches (cache/) e bases (dados/) usam os caminhos do caminhos.py
os.chdir(_C.RESULTADOS)

# credenciais (config/credenciais.txt) -> variáveis de ambiente, para todos os módulos
import credenciais as _credenciais  # noqa: E402
_credenciais.carregar()

# Parâmetros técnicos aceitos no input.txt, com os valores padrão usados
# quando a seção ou a chave não aparecem.
PADROES_CONFIG = {
    # gráficos (graficos.py) ao fim das etapas 2 a 5: desligado por padrão
    # (o painel mostra os resultados; para exportar figuras, use o botão do
    # painel ou mods/graficos.sh)
    "graficos": {"automatico": False},
    "ollama": {"modelo": "qwen3.5:35b-a3b", "url": "http://localhost:11434",
               "timeout_segundos": 180, "paralelo": 4, "pensar": False},
    "pubmed": {"max_artigos_por_planta": 20, "max_artigos_por_composto": 10,
               "max_compostos": 0, "excluir_revisoes": True,
               "busca_composto_por_nome": "complemento",
               "plantas_pesquisadas": "todas", "max_plantas": 0,
               "incluir_nao_reconhecidos": False,
               "ncbi_api_key": "", "email": ""},
    "artigos": {"ativar": True, "usar_pubmed": True, "usar_openalex": True,
                "max_artigos": 10000, "contexto_vegetal": False,
                "openalex_api_key": "", "email": "",
                # obsoletas (aceitas e ignoradas, para não quebrar input.txt antigos):
                "max_artigos_por_atividade": 0,
                "termos_regiao": "", "incluir_plantas_listadas": False,
                "filtro_ocorrencia": "", "estados": "", "dominios": "", "flora_brasil_url": ""},
    "taxonomia": {"usar_flora_brasil": True, "usar_wfo": True, "usar_wcvp": True, "usar_gbif": True,
                  "corrigir_grafia": True, "flora_brasil_url": "", "wfo_url": "", "wcvp_url": "",
                  "estados_gbif": True},
    "bioativos": {"apenas_com_atividade_npass": False, "incluir_nao_reconhecidos": False,
                  "coconut_url": "", "usar_duke": True, "duke_url": "",
                  "usar_lotus": True, "lotus_url": "", "usar_foodb": True, "foodb_url": "",
                  "smiles_pubchem": True, "escopo": "regiao", "reino": "vegetal"},
    "chembl": {"ativar": True, "pchembl_minimo": 5.0, "estereoisomeros": True,
               "prever_por_similaridade": False, "similaridade_minima": 85,
               "estruturas_url": ""},
    # v3.17: etapas "normalizacao", "banco" e "qualidade"
    "banco": {"pubchem": True, "max_sinonimos": 25, "classyfire": "faltantes",
              "classyfire_submeter": True, "vias_pubchem": True, "espectros_pubchem": True,
              "admet_ai": False, "incluir_pubmed": True,
              "enriquecer_apenas_regiao": True, "idioma_banco": "en",
              # fontes de espectros: uma chave por fonte de mods/espectros_*.py
              # (espectros_pubchem acima; as novas entram sem mexer aqui)
              "espectros_teoricos": True,
              "umap": True, "umap_max": 50000},
}

def apagar_pasta(pasta: str):
    """shutil.rmtree que também funciona no Windows com arquivos somente
    leitura e com arquivos presos por um instante (antivírus, indexador)."""
    import shutil
    import stat

    def _liberar(funcao, caminho, _erro):
        try:
            os.chmod(caminho, stat.S_IWRITE)
            funcao(caminho)
        except OSError:
            pass
    for _ in range(5):
        if not os.path.exists(pasta):
            return
        if sys.version_info >= (3, 12):
            shutil.rmtree(pasta, onexc=_liberar)
        else:
            shutil.rmtree(pasta, onerror=_liberar)
        if os.path.exists(pasta):
            time.sleep(1)
    if os.path.exists(pasta):
        raise OSError(f"não foi possível apagar {pasta}: algum arquivo dela está aberto "
                      "em outro programa. Feche-o e rode de novo.")


def trocar(origem: str, destino: str, espera_max: int = 600):
    """os.replace com novas tentativas. No Windows, um arquivo aberto em outro
    programa (ex.: o CSV aberto no Excel) não pode ser substituído: avisa e
    espera até ele ser fechado (no máximo espera_max segundos)."""
    avisado, inicio = False, time.time()
    while True:
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if time.time() - inicio > espera_max:
                raise PermissionError(
                    f"{destino} continua aberto em outro programa (Excel?). O resultado novo "
                    f"ficou em {origem}: feche o arquivo e renomeie-o, ou rode a etapa de novo.")
            if not avisado and time.time() - inicio > 3:
                print(f"\n  ATENÇÃO: {destino} está aberto em outro programa (Excel?) e não "
                      "pode ser substituído. Feche-o - o pipeline continua sozinho "
                      "assim que o arquivo for liberado.", flush=True)
                avisado = True
            time.sleep(2)


def extrair_zip(arquivo_zip: str, pasta: str):
    """Extrai um .zip numa pasta temporária e só então a renomeia para o nome
    final: uma extração interrompida (Ctrl+C, falta de espaço) não deixa uma
    pasta incompleta que as rodadas seguintes tomariam por pronta."""
    import zipfile
    tmp = pasta.rstrip("/\\") + ".parcial"
    apagar_pasta(tmp)
    with zipfile.ZipFile(arquivo_zip) as z:
        z.extractall(tmp)
    apagar_pasta(pasta)
    trocar(tmp, pasta, espera_max=60)


def gravar_csv(df, caminho, **kw):
    """to_csv atômico: grava num arquivo temporário e renomeia. Uma gravação
    interrompida não deixa um CSV truncado que o --retomar tomaria por pronto."""
    tmp = str(caminho) + ".parcial"
    kw.setdefault("index", False)
    kw.setdefault("encoding", "utf-8-sig")
    df.to_csv(tmp, **kw)
    trocar(tmp, str(caminho))


ROTULOS_SECAO_COORD = {"coordenadas", "coordenada", "regiao", "região",
                       "area", "área", "area_geografica"}
ROTULOS_SECAO_TAXONS = {"taxons", "táxons", "taxa", "especies", "espécies",
                        "generos", "gêneros", "plantas", "lista"}
ROTULOS_SECAO_TERMOS = {"termos_pubmed", "termos", "atividades",
                        "atividades_pubmed", "termos_busca"}
# chaves com valores restritos a uma lista
ESCOLHAS = {
    ("pubmed", "busca_composto_por_nome"): {"complemento", "sempre", "nunca"},
    ("pubmed", "plantas_pesquisadas"): {"todas", "com_compostos"},
    ("artigos", "filtro_ocorrencia"): {"", "regiao", "brasil", "nenhum"},  # obsoleta
    ("banco", "classyfire"): {"faltantes", "todos", "nao", "não"},
    ("bioativos", "escopo"): {"regiao", "região", "completo"},
    ("bioativos", "reino"): {"vegetal", "qualquer"},
    ("banco", "idioma_banco"): {"en", "pt", "ingles", "inglês", "portugues", "português"},
}
VERDADEIRO = {"true", "sim", "s", "yes", "1", "verdadeiro"}
FALSO = {"false", "nao", "não", "n", "no", "0", "falso"}

RE_NUMERO = re.compile(r"[-+]?\d+(?:\.\d+)?")
RE_RAIO = re.compile(r"^\s*raio(?:_km)?\s*[=:]\s*([-+]?\d+(?:\.\d+)?)\s*$", re.I)
RE_PAIS = re.compile(r"^\s*pa[ií]s(?:es)?\s*[=:]\s*(.*)$", re.I)
RE_TERMOS_REGIAO = re.compile(r"^\s*termos(?:_texto|_regiao)?\s*[=:]\s*(.*)$", re.I)
TERMOS_REGIAO_PADRAO = ["amazon*", "Amazonas", "Amazônia"]
# Lista de plantas em arquivo próprio, na mesma pasta do input.txt. Se existir
# e tiver nomes, SUBSTITUI a seção [taxons] do input.txt.
ARQUIVO_LISTA = "lista_de_plantas.txt"
_AVISOS = {}   # avisos mostrados uma vez só por execução


# =============================================================================
# input.txt
# =============================================================================
def _codificacao(caminho) -> str:
    """UTF-8 (com ou sem BOM) ou, se o arquivo foi salvo como ANSI/Latin-1
    (ex.: Bloco de Notas antigo no Windows), cp1252. Quebras de linha do
    Windows (CRLF) e do Linux (LF) são aceitas igualmente."""
    dados = Path(caminho).read_bytes()
    try:
        dados.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def caminho_input() -> Path:
    caminho = Path(os.environ.get("PIPELINE_INPUT", "config/input.txt"))
    caminho = caminho if caminho.is_absolute() else PASTA / caminho
    antigo = PASTA / "input.txt"
    if not caminho.exists() and caminho == PASTA_CONFIG / "input.txt" and antigo.exists():
        if not _AVISOS.get("input_antigo"):
            _AVISOS["input_antigo"] = True
            print("AVISO: usando input.txt da raiz do projeto. Mova-o para a pasta config/ "
                  "(junto com lista_de_plantas.txt e as credenciais do GBIF).")
        return antigo
    return caminho


def ler_input(caminho: Path | str | None = None) -> dict:
    """Lê o input.txt e devolve {"pontos": [(lat, lon), ...],
    "raio_km": float | None, "taxons": [str, ...],
    "termos_pubmed": {rotulo: [termos em inglês], ...}  (vazio = busca geral),
    "config": {"ollama": {...}, "pubmed": {...}, "bioativos": {...}}}
    (seções técnicas já convertidas e completadas com os valores padrão).

    Formato esperado: seções [coordenadas] e [taxons]. Linhas fora de
    seção são classificadas pelo conteúdo (só números -> coordenadas;
    com letras -> táxons), para tolerar arquivos sem cabeçalho."""
    caminho = Path(caminho) if caminho else caminho_input()
    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo de entrada não encontrado: {caminho}\n"
            "Crie um input.txt com as seções [coordenadas] e [taxons] "
            "(veja o modelo que acompanha o pipeline)."
        )

    numeros, taxons_brutos, raio_km, termos_regiao = [], [], None, None
    paises = []
    linhas_chaves = {}   # (seção, chave) -> linha, para acusar chaves repetidas
    termos_pubmed = {}
    config = {nome: dict(padrao) for nome, padrao in PADROES_CONFIG.items()}
    secao = None
    with open(caminho, encoding=_codificacao(caminho)) as f:
        for n_linha, linha in enumerate(f, start=1):
            linha = linha.split("#", 1)[0].strip()
            if not linha:
                continue
            cabecalho = re.fullmatch(r"\[(.+)\]", linha)
            if cabecalho:
                nome = cabecalho.group(1).strip().lower()
                if nome in ROTULOS_SECAO_COORD:
                    secao = "coord"
                elif nome in ROTULOS_SECAO_TAXONS:
                    secao = "taxons"
                elif nome in ROTULOS_SECAO_TERMOS:
                    secao = "termos"
                elif nome in PADROES_CONFIG:
                    secao = "config:" + nome
                else:
                    raise ValueError(
                        f"{caminho.name}, linha {n_linha}: seção desconhecida "
                        f"[{nome}]. Seções válidas: [coordenadas], [taxons], "
                        "[termos_pubmed], " + ", ".join(f"[{n}]" for n in PADROES_CONFIG) + ".")
                continue

            if secao and secao.startswith("config:"):
                chave_lida = linha.split("=", 1)[0].strip()
                anterior = linhas_chaves.get((secao, chave_lida))
                if anterior and "=" in linha:
                    raise ValueError(
                        f"{caminho.name}, linha {n_linha}: a chave '{chave_lida}' aparece "
                        f"duas vezes em [{secao[7:]}] (também na linha {anterior}). Só a "
                        "última valeria - apague uma delas.")
                linhas_chaves[(secao, chave_lida)] = n_linha
                _ler_linha_config(linha, config[secao[7:]], secao[7:],
                                  caminho.name, n_linha)
                continue

            if secao == "termos":
                _ler_linha_termos(linha, termos_pubmed, caminho.name, n_linha)
                continue

            m_termos = RE_TERMOS_REGIAO.match(linha)
            if m_termos and secao in ("coord", None):
                termos_regiao = [t.strip() for t in m_termos.group(1).split(",") if t.strip()]
                continue

            m_pais = RE_PAIS.match(linha)
            if m_pais and secao in ("coord", None):
                paises = [p.strip().upper() for p in re.split(r"[,;\s]+", m_pais.group(1)) if p.strip()]
                invalidos = [p for p in paises if not re.fullmatch(r"[A-Z]{2}", p)]
                if invalidos:
                    raise ValueError(
                        f"{caminho.name}, linha {n_linha}: país(es) {', '.join(invalidos)} - use o "
                        "código de 2 letras (ISO 3166), ex.: pais = BR")
                continue

            m_raio = RE_RAIO.match(linha)
            if m_raio:
                raio_km = float(m_raio.group(1))
                continue

            tem_letra = bool(re.search(r"[A-Za-zÀ-ÿ]", linha))
            if secao == "coord" or (secao is None and not tem_letra):
                if tem_letra:
                    raise ValueError(
                        f"{caminho.name}, linha {n_linha}: esperava coordenadas "
                        f"'latitude, longitude' e encontrei: {linha!r}")
                if re.search(r"\d,\d", linha) and "." not in linha:
                    raise ValueError(
                        f"{caminho.name}, linha {n_linha}: parece haver vírgula "
                        f"como separador decimal em {linha!r}. Use PONTO para "
                        "decimais e vírgula só entre latitude e longitude "
                        "(ex.: -3.35, -64.71).")
                numeros.extend(float(x) for x in RE_NUMERO.findall(linha))
            else:
                taxons_brutos.append(linha)

    if len(numeros) % 2:
        raise ValueError(f"{caminho.name}: número ímpar de valores nas "
                         "coordenadas - cada ponto precisa de latitude E longitude.")
    pontos = [(numeros[i], numeros[i + 1]) for i in range(0, len(numeros), 2)]
    if not pontos:
        raise ValueError(f"{caminho.name}: nenhuma coordenada encontrada na "
                         "seção [coordenadas].")
    for lat, lon in pontos:
        if abs(lat) > 90 and abs(lon) <= 90:
            raise ValueError(f"Ponto ({lat}, {lon}): latitude fora de -90..90. "
                             "Parece que latitude e longitude estão invertidas "
                             "- a ordem é 'latitude, longitude'.")
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Ponto ({lat}, {lon}) fora dos limites válidos "
                             "(latitude -90..90, longitude -180..180).")
    if raio_km is not None and raio_km <= 0:
        raise ValueError("raio_km precisa ser maior que zero.")

    # lista_de_plantas.txt (se existir) substitui a seção [taxons]
    fonte_taxons = f"{caminho.name} [taxons]"
    arquivo_lista = caminho.parent / ARQUIVO_LISTA
    if arquivo_lista.exists():
        with open(arquivo_lista, encoding=_codificacao(arquivo_lista)) as f:
            do_arquivo = [l.strip() for l in f
                          if l.strip() and not l.lstrip().startswith("#")]
        if do_arquivo:
            if taxons_brutos and not _AVISOS.get("lista"):
                _AVISOS["lista"] = True
                print(f"AVISO: {ARQUIVO_LISTA} encontrado - ele SUBSTITUI a seção "
                      f"[taxons] do {caminho.name}, que será ignorada.")
            taxons_brutos = do_arquivo
            fonte_taxons = ARQUIVO_LISTA

    # duplicatas LITERAIS: mesmo texto, ignorando maiúsculas/minúsculas e
    # espaços extras. Nenhuma correção de grafia ou sinonímia é feita aqui.
    taxons, vistos, repetidos = [], set(), []
    for item in re.split(r"[,;\n]", ",".join(taxons_brutos)):
        nome = re.sub(r"\s+", " ", item).strip()
        if not nome:
            continue
        if nome.lower() in vistos:
            repetidos.append(nome)
            continue
        vistos.add(nome.lower())
        taxons.append(nome)

    # termos de texto da região: [regiao] > [artigos] termos_regiao (antigo) > padrão
    if not termos_regiao:
        antigos = [t.strip() for t in str(config["artigos"]["termos_regiao"]).split(",") if t.strip()]
        termos_regiao = antigos or list(TERMOS_REGIAO_PADRAO)

    return {"pontos": pontos, "raio_km": raio_km, "taxons": taxons, "paises": paises,
            "taxons_repetidos": repetidos, "fonte_taxons": fonte_taxons,
            "termos_regiao": termos_regiao,
            "termos_pubmed": termos_pubmed, "config": config}


# chaves de fontes acrescentadas depois: [banco] espectros_<nome> para
# mods/espectros_<nome>.py e [bioativos] usar_<nome> para mods/fonte_<nome>.py
PREFIXOS_FONTE = {"banco": ("espectros_", "espectros_"),
                  "bioativos": ("usar_", "fonte_")}


def chave_de_fonte_espectral(secao: str, chave: str) -> bool:
    """A chave é de uma fonte acrescentada em mods/ e por isso não está na
    lista de padrões? Só é aceita se o módulo da fonte existir de fato, para um
    erro de digitação continuar sendo erro. Ver a seção 26 do README."""
    par = PREFIXOS_FONTE.get(secao)
    if not par or not chave.startswith(par[0]):
        return False
    nome = chave[len(par[0]):]
    if not nome.isidentifier():
        return False
    return os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       f"{par[1]}{nome}.py"))


def _ler_linha_config(linha: str, destino: dict, secao: str, arquivo: str, n_linha: int):
    """'chave = valor' numa seção técnica, convertido para o tipo do padrão."""
    if "=" not in linha:
        raise ValueError(f"{arquivo}, linha {n_linha}: na seção [{secao}] use "
                         f"'chave = valor'; encontrei {linha!r}.")
    chave, valor = (x.strip() for x in linha.split("=", 1))
    padroes = PADROES_CONFIG[secao]
    if chave not in padroes and chave_de_fonte_espectral(secao, chave):
        # fonte de espectros nova (mods/espectros_<nome>.py): a chave
        # [banco] espectros_<nome> é aceita sem que este arquivo precise
        # ser alterado. Ver a seção 26 do README.
        destino[chave] = valor.lower() in VERDADEIRO
        if valor.lower() not in VERDADEIRO | FALSO:
            raise ValueError(f"{arquivo}, linha {n_linha}: valor inválido para "
                             f"'{chave}' em [{secao}]: {valor!r} (use true ou false).")
        return
    if chave not in padroes:
        raise ValueError(f"{arquivo}, linha {n_linha}: chave '{chave}' não existe "
                         f"em [{secao}]. Chaves válidas: {', '.join(padroes)}"
                         + {"banco": ", espectros_<nome> (fontes de espectros)",
                            "bioativos": ", usar_<nome> (fontes de compostos)"}
                         .get(secao, "") + ".")
    padrao = padroes[chave]
    try:
        if isinstance(padrao, bool):
            if valor.lower() not in VERDADEIRO | FALSO:
                raise ValueError("use true ou false")
            destino[chave] = valor.lower() in VERDADEIRO
        elif isinstance(padrao, int):
            destino[chave] = int(valor)
        elif isinstance(padrao, float):
            destino[chave] = float(valor)
        else:
            opcoes = ESCOLHAS.get((secao, chave))
            if opcoes and valor.lower() not in opcoes:
                raise ValueError("use " + " ou ".join(sorted(opcoes)))
            destino[chave] = valor.lower() if opcoes else valor
    except ValueError as e:
        raise ValueError(f"{arquivo}, linha {n_linha}: valor inválido para "
                         f"'{chave}' em [{secao}]: {valor!r} ({e}).")


def _ler_linha_termos(linha: str, destino: dict, arquivo: str, n_linha: int):
    """Uma linha da seção [termos_pubmed]:
         rótulo = termo1, termo2, ...   -> uma atividade com sinônimos
         termo1, termo2                 -> cada termo é uma atividade
    Termos podem ter truncamento (larvicid*) ou tag do PubMed
    ("Anti-Bacterial Agents"[mh])."""
    def separar(texto):
        return [re.sub(r"\s+", " ", t).strip() for t in re.split(r"[,;]", texto) if t.strip()]

    if "=" in linha:
        rotulo, termos = (x.strip() for x in linha.split("=", 1))
        termos = separar(termos)
        if not rotulo or not termos:
            raise ValueError(f"{arquivo}, linha {n_linha}: use 'rótulo = termo1, "
                             f"termo2' em [termos_pubmed]; encontrei {linha!r}.")
        grupos = [(rotulo.lower(), termos)]
    else:
        grupos = [(re.sub(r'\[[^\]]*\]|"', "", t).strip().lower(), [t])
                  for t in separar(linha)]

    for rotulo, termos in grupos:
        lista = destino.setdefault(rotulo, [])
        for t in termos:
            if t.lower() not in (x.lower() for x in lista):
                lista.append(t)


def _area_assinada(vertices_lonlat: list) -> float:
    soma = 0.0
    for (x1, y1), (x2, y2) in zip(vertices_lonlat, vertices_lonlat[1:] + vertices_lonlat[:1]):
        soma += x1 * y2 - x2 * y1
    return soma / 2


def geometria_da_regiao(dados_input: dict | None = None) -> dict:
    """Converte os pontos do input em um polígono WKT aceito pelo GBIF
    (ordem lon/lat, anti-horário, fechado)."""
    dados_input = dados_input or ler_input()
    pontos = dados_input["pontos"]

    if len(pontos) == 1:
        lat0, lon0 = pontos[0]
        raio = dados_input.get("raio_km") or 10.0
        dlat = raio / 111.32
        dlon = raio / (111.32 * max(math.cos(math.radians(lat0)), 1e-6))
        vertices = [(lon0 + dlon * math.cos(2 * math.pi * k / 36),
                     lat0 + dlat * math.sin(2 * math.pi * k / 36)) for k in range(36)]
        tipo = "circulo"
        descricao = f"círculo de {raio:g} km ao redor de ({lat0}, {lon0})"
    elif len(pontos) == 2:
        lats = sorted(p[0] for p in pontos)
        lons = sorted(p[1] for p in pontos)
        if lats[0] == lats[1] or lons[0] == lons[1]:
            raise ValueError("Os 2 pontos precisam ter latitudes E longitudes "
                             "diferentes para formar um retângulo.")
        vertices = [(lons[0], lats[0]), (lons[1], lats[0]),
                    (lons[1], lats[1]), (lons[0], lats[1])]
        tipo = "retangulo"
        descricao = f"retângulo lat {lats[0]}..{lats[1]}, lon {lons[0]}..{lons[1]}"
    else:
        vertices = [(lon, lat) for lat, lon in pontos]
        if vertices[0] == vertices[-1]:
            vertices = vertices[:-1]
        if len(vertices) < 3:
            raise ValueError("O polígono precisa de pelo menos 3 vértices distintos.")
        tipo = "poligono"
        descricao = f"polígono com {len(vertices)} vértices"

    area = _area_assinada(vertices)
    if abs(area) < 1e-12:
        raise ValueError("Os pontos informados não formam uma área (estão alinhados).")
    if area < 0:  # GBIF exige orientação anti-horária
        vertices = vertices[::-1]

    fechado = vertices + [vertices[0]]
    wkt = "POLYGON((" + ", ".join(f"{lon:.6f} {lat:.6f}" for lon, lat in fechado) + "))"
    lons = [v[0] for v in vertices]
    lats = [v[1] for v in vertices]
    return {"wkt": wkt, "tipo": tipo, "descricao": descricao,
            "bbox": {"min_lat": min(lats), "max_lat": max(lats),
                     "min_lon": min(lons), "max_lon": max(lons)}}


# =============================================================================
# Parâmetros técnicos (seções [artigos], [ollama], [pubmed], [bioativos], [chembl])
# =============================================================================
def _secao(nome: str) -> dict:
    return dict(ler_input()["config"][nome])


def carregar_config_graficos() -> dict:
    return _secao("graficos")


def carregar_config_ollama() -> dict:
    return _secao("ollama")


def carregar_config_pubmed() -> dict:
    cfg = _secao("pubmed")
    cfg["ncbi_api_key"] = cfg["ncbi_api_key"] or os.environ.get("NCBI_API_KEY", "")
    cfg["email"] = cfg["email"] or os.environ.get("NCBI_EMAIL", "") or os.environ.get("GBIF_EMAIL", "")
    return cfg


def carregar_config_artigos() -> dict:
    cfg = _secao("artigos")
    cfg["email"] = (cfg["email"] or _secao("pubmed")["email"]
                    or os.environ.get("NCBI_EMAIL", "") or os.environ.get("GBIF_EMAIL", ""))
    cfg["termos_regiao"] = ler_input()["termos_regiao"]
    cfg["openalex_api_key"] = cfg["openalex_api_key"] or os.environ.get("OPENALEX_API_KEY", "")
    return cfg


def carregar_config_taxonomia() -> dict:
    return _secao("taxonomia")


def carregar_config_bioativos() -> dict:
    return _secao("bioativos")


def carregar_config_chembl() -> dict:
    cfg = _secao("chembl")
    if not 70 <= cfg["similaridade_minima"] <= 100:
        raise ValueError("input.txt, [chembl]: similaridade_minima precisa estar "
                         "entre 70 e 100 (limite da API do ChEMBL).")
    return cfg


def carregar_config_bioativos_escopo() -> str:
    """\"regiao\" (só as plantas de plantas.csv) ou \"completo\" (todas as
    plantas das bases químicas, com as da região marcadas em na_regiao)."""
    e = str(_secao("bioativos").get("escopo") or "regiao").strip().lower()
    return "completo" if e == "completo" else "regiao"


def carregar_config_bioativos_reino() -> str:
    """\"vegetal\" (padrão) ou \"qualquer\": que reinos entram no banco."""
    r = str(_secao("bioativos").get("reino") or "vegetal").strip().lower()
    return "qualquer" if r == "qualquer" else "vegetal"


def carregar_config_banco() -> dict:
    cfg = _secao("banco")
    if cfg["classyfire"] == "não":
        cfg["classyfire"] = "nao"
    idioma = str(cfg.get("idioma_banco") or "en").strip().lower()
    cfg["idioma_banco"] = "pt" if idioma.startswith("p") else "en"
    return cfg


if __name__ == "__main__":
    dados = ler_input()
    geo = geometria_da_regiao(dados)
    print(f"Arquivo de entrada: {caminho_input()}")
    print(f"Pontos: {dados['pontos']}")
    print(f"Região: {geo['descricao']}")
    print(f"País(es) (filtro do GBIF): {', '.join(dados['paises']) or '(nenhum - todos os registros da área)'}")
    print(f"Termos de texto da região (artigos): {', '.join(dados['termos_regiao'])}")
    print(f"WKT (GBIF): {geo['wkt']}")
    amostra = ", ".join(dados["taxons"][:30]) + (" ..." if len(dados["taxons"]) > 30 else "")
    print(f"\n{len(dados['taxons'])} táxon(s) do usuário (de {dados['fonte_taxons']}): {amostra}")
    if dados["termos_pubmed"]:
        print("\nBusca no PubMed RESTRITA a estas atividades:")
        for rotulo, termos in dados["termos_pubmed"].items():
            print(f"  - {rotulo}: {', '.join(termos)}")
    else:
        print("\nBusca no PubMed geral (nenhum termo em [termos_pubmed]).")
    print("\nOllama:", carregar_config_ollama())
    pub = carregar_config_pubmed()
    pub["ncbi_api_key"] = "***" if pub["ncbi_api_key"] else ""
    print("PubMed:", pub)
    print("Bioativos:", carregar_config_bioativos())
    print("ChEMBL:", carregar_config_chembl())
    print("Taxonomia:", carregar_config_taxonomia())
    print("Banco (normalizacao/banco/qualidade):", carregar_config_banco())
    art = carregar_config_artigos()
    art["openalex_api_key"] = "***" if art["openalex_api_key"] else ""
    print("Artigos:", art)
