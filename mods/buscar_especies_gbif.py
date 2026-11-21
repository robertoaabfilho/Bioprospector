"""
buscar_especies_gbif.py  -  ETAPA 1 ("gbif")

Levanta no GBIF a lista COMPLETA de espécies de PLANTAS (reino Plantae)
com registros de ocorrência dentro da região definida em input.txt
(seção [coordenadas]).

Usa a Occurrence Download API no formato SPECIES_LIST (download
assíncrono, sem teto de paginação), que exige conta gratuita no GBIF.
As credenciais ficam em config/credenciais.txt (o mesmo arquivo em Windows,
Linux e macOS). Se faltarem quando um download novo for necessário, o
pipeline pergunta e abre o arquivo para você preencher.

Reaproveitamento automático: a chave de cada pedido fica registrada em
dados/gbif_download/pedidos.json. Se a mesma região for pedida de novo,
o download anterior é reutilizado sem gastar nova cota. Para forçar uma
chave específica: --gbif-chave 0001234-... (ou a variável GBIF_DOWNLOAD_KEY)

Saída: especies_gbif.csv
    speciesKey, reino, filo, classe, ordem, familia, nome_cientifico,
    nome_popular_pt, categoria_taxonomica, n_ocorrencias_na_area
"""

import json
import os

import caminhos as _C
import re
import time

import pandas as pd
import requests

import credenciais
from config_pipeline import COMANDO, carregar_config_taxonomia, extrair_zip, gravar_csv, geometria_da_regiao, ler_input, trocar

KINGDOM_KEY_PLANTAE = 6

BUSCAR_NOMES_POPULARES = True
MAX_CONSULTAS_NOME_POPULAR = 1500  # as de maior nº de ocorrências primeiro

PASTA_DADOS = _C.dados("gbif_download")
ARQUIVO_PEDIDOS = os.path.join(PASTA_DADOS, "pedidos.json")
SAIDA = "especies_gbif.csv"
CACHE_VERNACULAR = os.path.join(PASTA_DADOS, "cache_nomes_populares.json")

URL_PEDIDO = "https://api.gbif.org/v1/occurrence/download/request"
URL_STATUS = "https://api.gbif.org/v1/occurrence/download/{}"
URL_VERNACULAR = "https://api.gbif.org/v1/species/{}/vernacularNames"
HEADERS = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0"}

COLUNAS_SAIDA = ["speciesKey", "reino", "filo", "classe", "ordem", "familia",
                 "nome_cientifico", "nome_popular_pt", "categoria_taxonomica",
                 "n_ocorrencias_na_area"]


# ---------------------------------------------------------------------------
def obter_credenciais():
    """Usuário, senha e e-mail do GBIF, de config/credenciais.txt (ou de
    variáveis de ambiente). Se faltarem, pergunta e abre o arquivo para
    preenchimento (credenciais.garantir_gbif)."""
    credenciais.garantir_gbif()
    return (os.environ["GBIF_USER"].strip(), os.environ["GBIF_PWD"].strip(),
            os.environ.get("GBIF_EMAIL", "").strip())


def montar_predicate(wkt: str, paises=()) -> dict:
    filtro_pais = [{"type": "in", "key": "COUNTRY", "values": list(paises)}] if paises else []
    return {"type": "and", "predicates": filtro_pais + [
        {"type": "within", "geometry": wkt},
        {"type": "equals", "key": "KINGDOM_KEY", "value": str(KINGDOM_KEY_PLANTAE)},
        {"type": "equals", "key": "HAS_COORDINATE", "value": "true"},
        {"type": "equals", "key": "HAS_GEOSPATIAL_ISSUE", "value": "false"},
        {"type": "equals", "key": "OCCURRENCE_STATUS", "value": "PRESENT"},
    ]}


def _ler_pedidos() -> dict:
    if os.path.exists(ARQUIVO_PEDIDOS):
        try:
            with open(ARQUIVO_PEDIDOS, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            print(f"AVISO: {ARQUIVO_PEDIDOS} ilegível - ignorado.")
    return {}


def _registrar_pedido(wkt: str, chave: str):
    pedidos = _ler_pedidos()
    pedidos[wkt] = chave
    with open(ARQUIVO_PEDIDOS + ".parcial", "w", encoding="utf-8") as f:
        json.dump(pedidos, f, indent=2, ensure_ascii=False)
    trocar(ARQUIVO_PEDIDOS + ".parcial", ARQUIVO_PEDIDOS)


def status_download(chave: str) -> dict:
    r = requests.get(URL_STATUS.format(chave), headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


URL_PEDIDOS_USUARIO = "https://api.gbif.org/v1/occurrence/download/user/{}"
TENTATIVAS_PEDIDO = 4


def _pedido_ja_criado(usuario, senha, predicate, desde: float, sql: str | None = None) -> str | None:
    """Depois de um pedido sem resposta (tempo esgotado), o GBIF muitas vezes
    o criou mesmo assim. Procura, entre os pedidos recentes do usuário, um
    com o MESMO filtro, criado a partir de `desde` (horário local, em s)."""
    try:
        r = requests.get(URL_PEDIDOS_USUARIO.format(usuario), auth=(usuario, senha),
                         headers=HEADERS, params={"limit": 20}, timeout=(30, 120))
        r.raise_for_status()
        pedidos = r.json().get("results", [])
    except (requests.RequestException, ValueError):
        return None
    alvo = json.dumps(predicate, sort_keys=True)
    for p in pedidos:
        req = p.get("request") or {}
        criado = pd.to_datetime(p.get("created"), errors="coerce", utc=True)
        recente = pd.notna(criado) and criado.timestamp() >= desde - 120
        if sql:
            igual = req.get("format") == "SQL_TSV_ZIP" and \
                " ".join(str(req.get("sql") or "").split()) == " ".join(sql.split())
        else:
            igual = req.get("format") == "SPECIES_LIST" and \
                json.dumps(req.get("predicate"), sort_keys=True) == alvo
        if recente and igual and \
                p.get("status") not in ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED"):
            return p.get("key")
    return None


def solicitar_download(usuario, senha, email, predicate, sql: str | None = None,
                       tentativas: int = TENTATIVAS_PEDIDO) -> str:
    corpo = {"creator": usuario, "notificationAddresses": [email] if email else [],
             "sendNotification": bool(email)}
    corpo.update({"format": "SQL_TSV_ZIP", "sql": sql} if sql else
                 {"format": "SPECIES_LIST", "predicate": predicate})
    inicio = time.time()
    for tentativa in range(1, tentativas + 1):
        try:
            # polígonos grandes deixam o GBIF lento para aceitar o pedido
            r = requests.post(URL_PEDIDO, json=corpo, auth=(usuario, senha),
                              headers=HEADERS, timeout=(30, 300))
            if r.status_code == 429 or r.status_code >= 500:
                # GBIF sobrecarregado ("503 Backend fetch failed"): passageiro
                raise requests.ConnectionError(f"HTTP {r.status_code}")
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            print(f"  GBIF não respondeu ao pedido ({e.__class__.__name__}: {e}); "
                  "conferindo se ele foi criado mesmo assim...")
            chave = _pedido_ja_criado(usuario, senha, predicate, inicio, sql)
            if chave:
                print(f"  O pedido foi criado: {chave}")
                return chave
            if tentativa == tentativas:
                raise RuntimeError(
                    f"GBIF indisponível: o pedido de download falhou {tentativas} "
                    "vezes (sobrecarga ou lentidão do servidor do GBIF). Rode a etapa de "
                    "novo mais tarde. Se você já tem um download desta região, use-o: "
                    f"{COMANDO} --a-partir-de gbif --gbif-chave <chave>") from e
            espera = 60 * tentativa
            print(f"  ainda não aparece; nova tentativa em {espera} s "
                  f"({tentativa + 1}/{tentativas})")
            time.sleep(espera)
            chave = _pedido_ja_criado(usuario, senha, predicate, inicio, sql)
            if chave:
                print(f"  O pedido foi criado: {chave}")
                return chave
    if r.status_code == 401:
        raise RuntimeError(f"GBIF recusou o login (HTTP 401) para o usuário "
                           f"'{usuario}'. Confira usuário/senha do gbif.org.")
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GBIF recusou o pedido (HTTP {r.status_code}): {r.text}")
    chave = r.text.strip().strip('"')
    print(f"Pedido submetido. Chave: {chave}")
    print(f"Acompanhe em: https://www.gbif.org/occurrence/download/{chave}")
    return chave


def aguardar_download(chave: str, intervalo=30, tentativas_max=240) -> dict:
    falhas = 0
    for tentativa in range(1, tentativas_max + 1):
        try:
            info = status_download(chave)
            falhas = 0
        except requests.RequestException as e:   # falha passageira: continua esperando
            falhas += 1
            if falhas >= 10:
                raise RuntimeError(f"GBIF inacessível ({e}). A chave {chave} está registrada: "
                                   "rode de novo mais tarde, que o download será reaproveitado.")
            print(f"  [{tentativa}] sem resposta do GBIF ({e.__class__.__name__}) - tentando de novo")
            time.sleep(intervalo)
            continue
        status = info.get("status")
        print(f"  [{tentativa}] status: {status}")
        if status == "SUCCEEDED":
            return info
        if status in ("FAILED", "KILLED", "CANCELLED", "FILE_ERASED"):
            raise RuntimeError(f"Download {chave} terminou com status '{status}'.")
        time.sleep(intervalo)
    raise TimeoutError(f"Tempo de espera excedido. Confira "
                       f"https://www.gbif.org/occurrence/download/{chave} e, se "
                       f"estiver pronto, rode de novo (a chave foi registrada e "
                       f"será reaproveitada automaticamente).")


def chave_regiao(wkt: str, paises=()) -> str:
    """Identificador do pedido: a área e, se houver, o filtro de países (sem
    filtro, igual ao das versões anteriores - pedidos antigos continuam valendo)."""
    return wkt + (f"|COUNTRY={','.join(sorted(paises))}" if paises else "")


def _forma_regiao(regiao: str) -> tuple:
    """(coordenadas arredondadas, filtro de países) de uma chave de pedidos.json:
    a mesma área escrita com outra precisão ou espaçamento é a mesma região."""
    area, _, filtro = regiao.partition("|")
    numeros = tuple(round(float(n), 4) for n in re.findall(r"-?\d+(?:\.\d+)?", area))
    return numeros, filtro.strip()


def _pedido_registrado(wkt: str, paises=()) -> tuple[str | None, list]:
    """(chave do pedido desta região e filtro, [(filtro, chave) de pedidos da
    MESMA área com OUTRO filtro de países])."""
    area, filtro = _forma_regiao(chave_regiao(wkt, paises))
    exata, outros = None, []
    for regiao, chave in _ler_pedidos().items():
        try:
            a, f = _forma_regiao(regiao)
        except ValueError:
            continue
        if a != area:
            continue
        if f == filtro:
            exata = chave
        else:
            outros.append((f or "sem filtro de país", chave))
    return exata, outros


def obter_chave(wkt: str, paises=()) -> str:
    chave_env = os.environ.get("GBIF_DOWNLOAD_KEY", "").strip()
    if chave_env:
        print(f"Usando a chave informada em GBIF_DOWNLOAD_KEY: {chave_env}")
        return chave_env

    regiao = chave_regiao(wkt, paises)
    chave_anterior, outros_filtros = _pedido_registrado(wkt, paises)
    if not chave_anterior and outros_filtros:
        print("Há download desta MESMA área com outro filtro de países: "
              + "; ".join(f"{c} ({f})" for f, c in outros_filtros))
        print("  Um pedido novo será feito, com o filtro atual. Para usar um desses, "
              f"rode: {COMANDO} --a-partir-de gbif --gbif-chave <chave>")
    if chave_anterior:
        if os.path.exists(os.path.join(PASTA_DADOS, f"{chave_anterior}.zip")):
            print(f"Reaproveitando o download já baixado desta mesma região: {chave_anterior}")
            return chave_anterior
        try:
            status = status_download(chave_anterior).get("status")
        except requests.RequestException:
            # GBIF lento/fora do ar: não abre um pedido novo (que também
            # dependeria dele); a espera pelo pedido anterior tenta de novo
            print(f"GBIF sem resposta ao conferir o pedido anterior {chave_anterior} - "
                  "ele será reaproveitado.")
            return chave_anterior
        if status in ("SUCCEEDED", "RUNNING", "PREPARING", "SUSPENDED"):
            print(f"Reaproveitando o pedido anterior para esta mesma região: "
                  f"{chave_anterior} (status {status})")
            return chave_anterior

    usuario, senha, email = obter_credenciais()
    chave = solicitar_download(usuario, senha, email, montar_predicate(wkt, paises))
    _registrar_pedido(regiao, chave)
    return chave


def baixar_e_extrair(chave: str, info: dict) -> str:
    link = info.get("downloadLink") or f"https://api.gbif.org/v1/occurrence/download/request/{chave}.zip"
    zip_path = os.path.join(PASTA_DADOS, f"{chave}.zip")
    if not os.path.exists(zip_path):
        print(f"Baixando: {link}")
        tmp = zip_path + ".parcial"
        with requests.get(link, headers=HEADERS, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(chunk_size=1 << 20):
                    f.write(bloco)
        trocar(tmp, zip_path)

    pasta = os.path.join(PASTA_DADOS, chave)
    if not os.path.exists(pasta):
        extrair_zip(zip_path, pasta)

    ignorar = {"citations.txt", "rights.txt", "metadata.xml"}
    candidatos = [f for f in os.listdir(pasta) if f.lower().endswith((".csv", ".tsv", ".txt"))
                  and f.lower() not in ignorar]
    if not candidatos:
        raise FileNotFoundError(f"Arquivo de dados não encontrado em {pasta}.")
    return os.path.join(pasta, sorted(candidatos)[0])


def _col(df: pd.DataFrame, *nomes) -> str | None:
    mapa = {c.lower(): c for c in df.columns}
    for nome in nomes:
        if nome.lower() in mapa:
            return mapa[nome.lower()]
    return None


def chave_texto(valor) -> str:
    """Chave do GBIF como texto: "549R6" (backbone novo) ou "2874875" (antigo,
    mesmo que tenha sido lida como número, ex.: 2874875.0)."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    return texto[:-2] if re.fullmatch(r"\d+\.0", texto) else texto


def buscar_nome_popular_pt(chave_taxon) -> str | None:
    """Nomes populares em português ("" = o GBIF não tem nenhum). None = falha
    de rede ou do servidor: não vai para o cache, é tentado de novo depois."""
    try:
        r = requests.get(URL_VERNACULAR.format(chave_texto(chave_taxon)), headers=HEADERS,
                         params={"limit": 200}, timeout=(10, 30))
        if r.status_code == 429 or r.status_code >= 500:
            return None
        if r.status_code != 200:
            return ""
        nomes = []
        for item in r.json().get("results", []):
            nome = (item.get("vernacularName") or "").strip()
            if item.get("language") in ("por", "pt") and nome and nome not in nomes:
                nomes.append(nome)
        return "; ".join(nomes)
    except (requests.RequestException, ValueError):
        return None


MAX_FALHAS_SEGUIDAS = 20     # GBIF fora do ar: para de consultar nomes populares


def processar_species_list(caminho: str) -> pd.DataFrame:
    df = pd.read_csv(caminho, sep="\t", dtype=str, on_bad_lines="skip",
                     quoting=3, low_memory=False)
    if df.shape[1] < 2:
        df = pd.read_csv(caminho, sep=",", dtype=str, on_bad_lines="skip", low_memory=False)

    c_species = _col(df, "species")
    c_species_key = _col(df, "speciesKey")
    c_n = _col(df, "numberOfOccurrences", "occurrenceCount", "count")
    if not c_species or not c_species_key:
        raise RuntimeError(f"Colunas 'species'/'speciesKey' ausentes no arquivo "
                           f"do GBIF. Colunas recebidas: {list(df.columns)}")

    df = df[df[c_species].notna() & (df[c_species].str.strip() != "")].copy()
    df["_n"] = pd.to_numeric(df[c_n], errors="coerce").fillna(0) if c_n else 0

    def primeiro(c):
        return c if c else None

    agregacao = {"_n": "sum"}
    mapa_cols = {"reino": _col(df, "kingdom"), "filo": _col(df, "phylum"),
                 "classe": _col(df, "class"), "ordem": _col(df, "order"),
                 "familia": _col(df, "family"), "nome_cientifico": c_species}
    for c in mapa_cols.values():
        if primeiro(c):
            agregacao[c] = "first"

    # várias linhas (sinônimos, subespécies) podem apontar para a mesma
    # espécie aceita - agrega por speciesKey somando as ocorrências
    agrupado = df.groupby(c_species_key, as_index=False).agg(agregacao)

    saida = pd.DataFrame({
        # o backbone novo do GBIF usa chaves ALFANUMÉRICAS (ex.: "549R6"); o
        # antigo, números. Guardada como texto, vale para os dois
        "speciesKey": agrupado[c_species_key].map(chave_texto),
        **{novo: (agrupado[orig] if orig else None) for novo, orig in mapa_cols.items()},
    })
    saida["reino"] = saida["reino"].fillna("Plantae")
    saida["nome_popular_pt"] = ""
    saida["categoria_taxonomica"] = "SPECIES"
    saida["n_ocorrencias_na_area"] = agrupado["_n"].astype(int)
    saida = saida[COLUNAS_SAIDA].sort_values("n_ocorrencias_na_area", ascending=False)
    return saida.reset_index(drop=True)


def preencher_nomes_populares(especies: pd.DataFrame, consultar: bool = True) -> pd.DataFrame:
    """nome_popular_pt das espécies com mais ocorrências (cache em
    CACHE_VERNACULAR). consultar=False usa só o que já está em cache."""
    if not BUSCAR_NOMES_POPULARES or especies.empty:
        return especies
    alvo = especies.head(MAX_CONSULTAS_NOME_POPULAR)
    cache = {}
    if os.path.exists(CACHE_VERNACULAR):
        try:
            with open(CACHE_VERNACULAR, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
    novos = sum(1 for k in alvo["speciesKey"] if chave_texto(k) and chave_texto(k) not in cache)
    if consultar:
        print(f"Nomes populares em português: {len(alvo)} espécies com mais "
              f"ocorrências ({len(alvo) - novos} já em cache, {novos} a consultar)...")
    consultados, falhas_seguidas = 0, 0
    for idx in alvo.index:
        k = chave_texto(especies.at[idx, "speciesKey"])
        if not k:
            continue
        if k not in cache:
            if not consultar:
                continue
            nome = buscar_nome_popular_pt(k)
            consultados += 1
            if nome is None:
                falhas_seguidas += 1
                if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                    print(f"  GBIF sem resposta em {MAX_FALHAS_SEGUIDAS} consultas seguidas - "
                          "nomes populares interrompidos (os que faltam são buscados na "
                          "próxima rodada da etapa 'gbif').")
                    consultar = False
                time.sleep(0.05)
                continue
            falhas_seguidas = 0
            cache[k] = nome
            time.sleep(0.05)
            if consultados % 200 == 0:
                print(f"  ... {consultados}/{novos}")
                with open(CACHE_VERNACULAR, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
        especies.at[idx, "nome_popular_pt"] = cache[k]
    if consultados:
        with open(CACHE_VERNACULAR, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return especies


def saida_sem_chaves(caminho: str = SAIDA) -> bool:
    """True se especies_gbif.csv existe, tem linhas e NENHUMA speciesKey: é
    o sintoma do arquivo gravado pela v3, que convertia as chaves para
    número e perdia as do backbone novo do GBIF (alfanuméricas, ex.: 549R6)."""
    if not os.path.exists(caminho):
        return False
    try:
        df = pd.read_csv(caminho, dtype=str, usecols=["speciesKey"])
    except (ValueError, OSError):
        return False
    return len(df) > 0 and df["speciesKey"].fillna("").str.strip().eq("").all()


def _arquivo_local_do_download(wkt: str | None = None, paises=()) -> str | None:
    """Arquivo de dados de um download do GBIF JÁ baixado (sem internet): o
    pedido registrado para a região ou, se não houver, o mais recente."""
    if not os.path.isdir(PASTA_DADOS):
        return None
    chaves = []
    if wkt:
        chave = _ler_pedidos().get(chave_regiao(wkt, paises))
        if chave:
            chaves.append(chave)
    zips = sorted((f for f in os.listdir(PASTA_DADOS) if f.endswith(".zip")),
                  key=lambda f: os.path.getmtime(os.path.join(PASTA_DADOS, f)), reverse=True)
    chaves += [z[:-4] for z in zips if z[:-4] not in chaves]
    for chave in chaves:
        if os.path.exists(os.path.join(PASTA_DADOS, f"{chave}.zip")) or \
                os.path.isdir(os.path.join(PASTA_DADOS, chave)):
            try:
                return baixar_e_extrair(chave, {})   # já baixado: só extrai/acha o arquivo
            except (OSError, FileNotFoundError, requests.RequestException):
                continue
    return None


def refazer_saida_sem_chaves(wkt: str | None = None, paises=()) -> bool:
    """Se especies_gbif.csv está sem speciesKey (gravado pela v3), refaz o
    arquivo a partir do download do GBIF já baixado - sem novo pedido. Os
    nomes populares vêm só do cache. Devolve True se refez."""
    if not saida_sem_chaves():
        return False
    print(f"AVISO: {SAIDA} está sem speciesKey (gerado pela v3, que perdia as chaves "
          "alfanuméricas do backbone novo do GBIF).")
    caminho = _arquivo_local_do_download(wkt, paises)
    if not caminho:
        print(f"  Download do GBIF não encontrado em {PASTA_DADOS}/ - rode a etapa 'gbif' "
              "de novo para corrigir.")
        return False
    especies = preencher_nomes_populares(processar_species_list(caminho), consultar=False)
    gravar_csv(especies, SAIDA)
    print(f"  Refeito a partir de {caminho}: {len(especies)} espécies, "
          f"{(especies['speciesKey'].fillna('') != '').sum()} com speciesKey.")
    return True


# ---------------------------------------------------------------------------
# Estados brasileiros de cada espécie (download em SQL do GBIF, já agregado)
# ---------------------------------------------------------------------------
SAIDA_ESTADOS = "especies_gbif_estados.csv"
CHAVE_PEDIDO_ESTADOS = "SQL|estados_BR|plantas|v1"
SQL_ESTADOS = (
    "SELECT specieskey, species, level1gid, level1name, COUNT(*) AS n_registros "
    "FROM occurrence "
    "WHERE countrycode = 'BR' AND kingdom = 'Plantae' AND hascoordinate = TRUE "
    "AND hasgeospatialissues = FALSE AND occurrencestatus = 'PRESENT' "
    "AND specieskey IS NOT NULL AND level1gid IS NOT NULL "
    "GROUP BY specieskey, species, level1gid, level1name")
UF_POR_NOME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO"}


def _uf(nome) -> str | None:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFD", str(nome or ""))
                if unicodedata.category(c) != "Mn").lower().strip()
    return UF_POR_NOME.get(t)


def processar_estados(caminho: str) -> pd.DataFrame:
    df = pd.read_csv(caminho, sep="\t", dtype=str, quoting=3, on_bad_lines="skip")
    df.columns = [c.lower() for c in df.columns]
    df["uf"] = df["level1name"].map(_uf)
    df = df.dropna(subset=["uf", "specieskey"])
    df["n_registros"] = pd.to_numeric(df["n_registros"], errors="coerce").fillna(0).astype(int)
    saida = (df.groupby(["specieskey", "uf"], as_index=False)
             .agg(especie=("species", "first"), n_registros=("n_registros", "sum")))
    saida["speciesKey"] = saida["specieskey"].map(chave_texto)
    return saida[["speciesKey", "especie", "uf", "n_registros"]]


def levantar_estados() -> None:
    """Pede ao GBIF (download em SQL, uma vez) quantos registros
    georreferenciados cada espécie de planta tem em cada estado brasileiro.
    Usado na etapa "plantas" para as plantas sem estado na Flora e Funga do
    Brasil. Recurso experimental do GBIF: qualquer falha aqui só gera aviso."""
    pedidos = _ler_pedidos()
    chave = pedidos.get(CHAVE_PEDIDO_ESTADOS)
    if chave and os.path.exists(SAIDA_ESTADOS) and \
            os.path.exists(os.path.join(PASTA_DADOS, f"{chave}.zip")):
        print(f"Estados do GBIF: já levantados ({SAIDA_ESTADOS}, download {chave})")
        return
    print("\nEstados brasileiros das espécies (download em SQL do GBIF, só na primeira vez)...")
    try:
        if chave and not os.path.exists(os.path.join(PASTA_DADOS, f"{chave}.zip")):
            try:
                status = status_download(chave).get("status")
            except requests.RequestException:
                status = "RUNNING"            # GBIF lento: espera pelo mesmo pedido
            if status not in ("SUCCEEDED", "RUNNING", "PREPARING", "SUSPENDED"):
                chave = None
        if not chave:
            try:
                usuario, senha, email = obter_credenciais()
            except SystemExit as e:        # sem credenciais: esta parte é opcional
                raise RuntimeError("credenciais do GBIF não configuradas "
                                   "(config/credenciais.txt)") from e
            chave = solicitar_download(usuario, senha, email, None, sql=SQL_ESTADOS, tentativas=2)
            _registrar_pedido(CHAVE_PEDIDO_ESTADOS, chave)
        info = {} if os.path.exists(os.path.join(PASTA_DADOS, f"{chave}.zip")) \
            else aguardar_download(chave)
        caminho = baixar_e_extrair(chave, info)
        estados = processar_estados(caminho)
        gravar_csv(estados, SAIDA_ESTADOS)
        print(f"  {estados['speciesKey'].nunique()} espécies com registro em algum estado; "
              f"{len(estados)} pares espécie x estado em {SAIDA_ESTADOS}")
    except (RuntimeError, OSError, requests.RequestException, KeyError, ValueError,
            TimeoutError) as e:
        print(f"  AVISO: estados do GBIF não obtidos ({e}). A etapa segue; a distribuição por "
              "estado usa só a Flora e Funga do Brasil. Para tentar de novo: "
              f"{COMANDO} --somente gbif")


def main():
    os.makedirs(PASTA_DADOS, exist_ok=True)
    dados = ler_input()
    geo = geometria_da_regiao(dados)
    print(f"Região: {geo['descricao']}")
    print(f"WKT: {geo['wkt']}")
    if dados.get("paises"):
        print(f"Só registros dos países: {', '.join(dados['paises'])}")
    print("Reino: Plantae\n")

    chave = obter_chave(geo["wkt"], dados.get("paises") or ())
    if os.path.exists(os.path.join(PASTA_DADOS, f"{chave}.zip")):
        info = {}                 # já baixado: não depende do GBIF estar no ar
    else:
        print("\nAguardando o GBIF processar o download...")
        info = aguardar_download(chave)
    caminho = baixar_e_extrair(chave, info)
    print(f"Arquivo de dados: {caminho}")

    especies = processar_species_list(caminho)
    print(f"\n{len(especies)} espécies de plantas na região.")

    especies = preencher_nomes_populares(especies)

    gravar_csv(especies, SAIDA)
    print(f"\nConcluído: {len(especies)} espécies salvas em {SAIDA}")
    if carregar_config_taxonomia().get("estados_gbif", True):
        levantar_estados()
    if not especies.empty:
        print("\nFamílias mais representadas:")
        print(especies["familia"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
