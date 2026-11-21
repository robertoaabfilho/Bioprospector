"""
painel.py - painel interativo (Streamlit) dos resultados do pipeline

Lê as planilhas que o pipeline já gravou (resultados/), etapa por etapa, e o
banco relacional (resultados/banco/, etapas 6 a 8), quando existe. Pode ficar
aberto com o pipeline rodando. Também roda o pipeline, inicia o Ollama e mostra
a GPU (página "Rodar o pipeline").

Uso: o ícone "Painel do pipeline" (para criá-lo: mods/painel.sh atalho;
Windows: mods\\painel.bat atalho) ou, da pasta do projeto, mods/painel.sh
(Windows: mods\\painel.bat). Para fechar: Configurações -> Fechar o painel.

Páginas:
  Início               situação de cada etapa e o funil plantas -> compostos -> atividade
  1 · GBIF             plantas com registro na região
  2 · Plantas          lista final, distribuição no Brasil, conferência e descartes
  3 · Compostos        compostos, classes químicas, drogabilidade (ADMET)
  4 · ChEMBL           atividades medidas em ensaios
  5 · PubMed           atividades demonstradas em artigos (plantas, compostos, artigos)
  Prospecção           filtros cruzados entre as etapas -> plantas candidatas
  Ficha                tudo sobre uma planta ou um composto
  6-8 · Banco          tabelas do banco relacional, conflitos e qualidade
  Rodar o pipeline     etapas, interromper, registro; Ollama; GPU (nvidia-smi)

Requer pandas (já instalado pelo pipeline) e streamlit (o painel.sh /
painel.bat instala no ambiente do pipeline na primeira vez).
"""

import datetime
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

PASTA_MODS = Path(__file__).resolve().parent          # mods/ (este arquivo)
PASTA_PADRAO = PASTA_MODS.parent                       # raiz do projeto

# A pasta banco/ sai em INGLÊS desde a v3.18 ([banco] idioma_banco). O painel
# aceita os dois idiomas: resolve o nome do arquivo e traduz as colunas de volta
# para português, que é como o resto deste arquivo trabalha. O mapa vem de
# mods/esquema_banco.py, para não haver duas listas de nomes para manter.
sys.path.insert(0, str(PASTA_MODS))
try:
    import esquema_banco as ESQ
except Exception:                      # painel fora da pasta do pipeline
    ESQ = None

TABELAS_EN = dict(getattr(ESQ, "TABELAS_EN", {}) or {})
COLUNAS_EN = {pt: en for pt, (en, _) in (getattr(ESQ, "COLUNAS_EN", {}) or {}).items()}
EN_PARA_PT = {}
for _pt, _en in COLUNAS_EN.items():
    EN_PARA_PT.setdefault(_en, _pt)
VALORES_EN = dict(getattr(ESQ, "VALORES_EN", {}) or {})
SEP = r"\s*;\s*"
DESCONHECIDA = "distribuição desconhecida"

# --- aparência (mesma paleta do graficos.py: validada para daltonismo) -------
AZUL, LARANJA, VERDE, AMARELO = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
ROSA, VERDE2, ROXO, VERMELHO = "#e87ba4", "#008300", "#6250d6", "#e34948"
SERIE = [AZUL, LARANJA, VERDE, AMARELO, ROSA, VERDE2, ROXO, VERMELHO]
CINZA = "#b9b8b2"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB",
       "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]
DOMINIOS = ["Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"]
# evidência: da mais forte à mais fraca
EVIDENCIAS = ["clínico", "in vivo", "ex vivo", "in vitro", "não informado"]
NIVEL = {e: i for i, e in enumerate(EVIDENCIAS)}
COR_EVIDENCIA = {"clínico": "#0d366b", "in vivo": "#1c5cab", "ex vivo": "#3987e5",
                 "in vitro": "#86b6ef", "não informado": CINZA}
# partes da planta: coleta que não mata a planta x coleta destrutiva
SUSTENTAVEL = {"folha", "fruto", "semente", "flor", "exsudato (látex/resina)", "parte aérea"}
DESTRUTIVA = {"raiz", "casca", "caule", "rizoma", "tubérculo/bulbo", "planta inteira"}

# arquivos de cada etapa (main.py: ETAPAS)
ETAPAS = [
    ("0", "downloads", "bases_baixadas.txt", "Bases de dados baixadas"),
    ("1", "gbif", "especies_gbif.csv", "Plantas com registro na região (GBIF)"),
    ("2", "plantas", "plantas.csv", "Lista final de plantas, nomes conferidos e distribuição"),
    ("3", "bioativos", "especies_com_compostos_bioativos.csv", "Compostos de cada planta"),
    ("4", "chembl", "compostos_chembl.csv", "Atividades medidas no ChEMBL"),
    ("5", "pubmed", "atividades_plantas.csv", "Atividades demonstradas em artigos (PubMed)"),
    ("6", "normalizacao", "compostos_normalizados.csv", "Compostos deduplicados por InChIKey"),
    ("7", "banco", "banco/compostos.csv", "Banco relacional (pasta banco/)"),
    ("8", "qualidade", "banco/qualidade/", "Qualidade e cobertura do banco"),
]
ARQUIVOS_PARCIAIS = {"atividades_plantas.csv", "atividades_compostos.csv",
                     "especies_atividades.csv", "evidencias_pubmed.csv"}
# Etapa 5 em andamento x concluída. O pipeline não grava marcador de etapa, então
# o painel compara datas: os caches abaixo só a etapa 5 grava (um item por vez,
# enquanto roda), e o especies_atividades.csv é o último arquivo que ela grava ao
# terminar. Cache mais novo que ele = a etapa está rodando (ou foi interrompida).
CACHES_ETAPA5 = ["cache_llm_classificacao.jsonl", "cache_pubmed_filtro.jsonl",
                 "cache_pubchem_vinculos.jsonl", "cache_pubchem.jsonl"]
FINAL_ETAPA5 = "especies_atividades.csv"
FOLGA_SEG = 5
# saídas das etapas 6 a 8: só valem depois da etapa 5 concluída
SAIDAS_POS_PUBMED = {"compostos_normalizados.csv", "banco_compostos.csv"}

st.set_page_config(page_title="Painel do pipeline", page_icon="🌿", layout="wide")


# =============================================================================
# Leitura (com cache: um arquivo só é relido quando muda no disco)
# =============================================================================
def pasta() -> Path:
    """Raiz do projeto (a que tem config/, mods/, resultados/...)."""
    return Path(st.session_state.get("pasta", str(PASTA_PADRAO)))


def res() -> Path:
    """Planilhas do pipeline: resultados/ (no formato antigo, a própria raiz)."""
    r = pasta() / "resultados"
    return r if r.is_dir() else pasta()


def pasta_cache() -> Path:
    c = pasta() / "cache"
    return c if c.is_dir() else pasta()


def pasta_mods() -> Path:
    return pasta() / "mods"


def pasta_logs() -> Path:
    p = res() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def tabela_do_banco(nome: str) -> str | None:
    """"banco/compostos.csv" -> "compostos" (só para as 12 tabelas do esquema)."""
    if nome.startswith("banco/") and nome.endswith(".csv"):
        t = nome[len("banco/"):-len(".csv")]
        if t in TABELAS_EN:
            return t
    return None


def caminho(nome: str) -> Path | None:
    est = estado_etapa5()
    if est["estado"] == "andamento":
        if nome in ARQUIVOS_PARCIAIS:
            # a cópia que o painel tirou dos *_parcial.csv (nunca um arquivo a meio
            # caminho de ser gravado); as planilhas finais, se existirem, são de uma
            # rodada anterior e ficam de lado
            p = pasta_copia_parcial() / nome.replace(".csv", "_parcial.csv")
            return p if p.exists() else None
        if nome.startswith("banco/") or nome in SAIDAS_POS_PUBMED:
            return None          # banco e qualidade: só com a etapa 5 concluída
    p = res() / nome
    if p.exists():
        return p
    # banco gravado em inglês (padrão desde a v3.18)
    t = tabela_do_banco(nome)
    if t:
        p_en = res() / f"banco/{TABELAS_EN[t]}.csv"
        if p_en.exists():
            return p_en
    return None


@st.cache_data(show_spinner="Lendo planilha...", max_entries=40)
def _ler(caminho_str: str, mtime: float, colunas: tuple | None,
         tabela: str | None = None) -> pd.DataFrame:
    quero = set(colunas) if colunas else None
    if quero:     # o cabeçalho pode estar em português ou em inglês
        quero |= {COLUNAS_EN[c] for c in colunas if c in COLUNAS_EN}
    kw = dict(dtype=str, keep_default_na=False, na_values=[""],
              usecols=(lambda c: c in quero) if quero else None)
    try:
        df = pd.read_csv(caminho_str, encoding="utf-8-sig", **kw)
    except UnicodeDecodeError:          # planilha regravada pelo Excel
        df = pd.read_csv(caminho_str, encoding="latin-1", **kw)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()
    if tabela != "__sem_traducao__":
        df = para_portugues(df, tabela)
    for c in colunas or ():
        if c not in df.columns:
            df[c] = None
    return df


def para_portugues(df: pd.DataFrame, tabela: str | None) -> pd.DataFrame:
    """Nomes (e os poucos valores que são rótulos) do banco em inglês de volta
    para português. Sem efeito num arquivo já em português."""
    if not len(df.columns) or not EN_PARA_PT:
        return df
    volta = dict(EN_PARA_PT)
    if tabela == "mapa_inchikey":        # aqui compound_uid é o canônico
        volta["compound_uid"] = "inchikey_canonico"
    df = df.rename(columns={c: volta[c] for c in df.columns if c in volta})
    for coluna, mapa in VALORES_EN.items():
        if coluna in df.columns:
            para_pt = {v: k for k, v in mapa.items()}
            df = df.assign(**{coluna: df[coluna].map(lambda v: para_pt.get(v, v))})
    return df


def ler(nome: str, colunas=None, traduzir: bool = True) -> pd.DataFrame | None:
    """CSV do projeto (só as colunas pedidas); None se o arquivo não existe.
    traduzir=False devolve o cabeçalho como está no arquivo (a página do Banco
    mostra o banco publicável com os nomes dele)."""
    p = caminho(nome)
    if p is None:
        return None
    return _ler(str(p), p.stat().st_mtime, tuple(colunas) if colunas else None,
                tabela_do_banco(nome) if traduzir else "__sem_traducao__")


@st.cache_data(max_entries=40)
def _contar_linhas(caminho_str: str, mtime: float) -> int:
    with open(caminho_str, "rb") as f:
        return max(0, sum(1 for _ in f) - 1)


def linhas(nome: str) -> int | None:
    p = caminho(nome)
    return _contar_linhas(str(p), p.stat().st_mtime) if p else None


def tem_banco() -> bool:
    return caminho("banco/compostos.csv") is not None


# =============================================================================
# Etapa 5 em andamento: resultados parciais automáticos
# =============================================================================
def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def estado_etapa5() -> dict:
    """{'estado': 'andamento' | 'concluida' | 'nao_iniciada', 't_cache', 't_final'}"""
    tempos = [t for t in (_mtime(pasta_cache() / c) for c in CACHES_ETAPA5) if t]
    t_cache = max(tempos) if tempos else None
    t_final = _mtime(res() / FINAL_ETAPA5)
    if t_final and (t_cache is None or t_cache <= t_final + FOLGA_SEG):
        estado = "concluida"
    elif t_cache:
        estado = "andamento"
    else:
        estado = "nao_iniciada"
    return {"estado": estado, "t_cache": t_cache, "t_final": t_final}


def pasta_copia_parcial() -> Path:
    """Pasta temporária (fora do projeto) com a cópia dos *_parcial.csv que o
    painel lê. Uma por pasta de projeto."""
    h = hashlib.sha1(str(pasta().resolve()).encode("utf-8")).hexdigest()[:12]
    d = Path(tempfile.gettempdir()) / "painel_pipeline" / h
    d.mkdir(parents=True, exist_ok=True)
    return d


@st.cache_resource
def _geradores() -> dict:
    """Processos 'consultar_atividades_pubmed.py --parcial' em curso, por pasta
    (compartilhado entre as abas do navegador: nunca dois ao mesmo tempo)."""
    # "na_abertura": pastas que já tiveram a geração da abertura do painel
    return {"trava": threading.Lock(), "por_pasta": {}, "na_abertura": set()}


def _gerador() -> dict | None:
    return _geradores()["por_pasta"].get(str(pasta()))


def _copiar_parciais():
    """Copia os *_parcial.csv da raiz para a pasta do painel (cópia + replace:
    quem estiver lendo nunca pega um arquivo pela metade)."""
    destino = pasta_copia_parcial()
    for nome in ARQUIVOS_PARCIAIS:
        orig = res() / nome.replace(".csv", "_parcial.csv")
        dest = destino / orig.name
        t_o, t_d = _mtime(orig), _mtime(dest)
        if t_o and (t_d is None or t_o > t_d):
            tmp = dest.with_suffix(".tmp")
            shutil.copy2(orig, tmp)
            os.replace(tmp, dest)


def _log_gerador() -> Path:
    return pasta_copia_parcial() / "parcial.log"


def _arq_pid() -> Path:
    return pasta_copia_parcial() / "gerando.pid"


def _vivo(pid: int) -> bool:
    """O processo ainda existe? (sem pacotes extras, em Windows e Linux/macOS)"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        codigo = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(codigo))
        k.CloseHandle(h)
        return bool(ok) and codigo.value == 259          # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def geracao_externa() -> float | None:
    """Início de uma geração de parciais disparada por OUTRO painel (ou por este,
    antes de ser reiniciado) que ainda está rodando; None se não há."""
    try:
        pid, inicio = _arq_pid().read_text().split()
        pid, inicio = int(pid), float(inicio)
    except (OSError, ValueError):
        return None
    if time.time() - inicio < 6 * 3600 and _vivo(pid):
        return inicio
    _arq_pid().unlink(missing_ok=True)
    return None


def duracao_ultima() -> float | None:
    try:
        return float((pasta_copia_parcial() / "ultima_geracao.txt").read_text())
    except (OSError, ValueError):
        return None


def disparar_parciais(forcar: bool = False) -> str:
    """Com a etapa 5 em andamento, gera os parciais em segundo plano quando o
    modelo leu algo novo e a última geração tem mais que o intervalo escolhido.
    Devolve o que está acontecendo: 'gerando', 'pronto' ou 'falhou'."""
    g = _geradores()
    with g["trava"]:
        atual = g["por_pasta"].get(str(pasta()))
        if atual and atual["proc"].poll() is None:
            return "gerando"
        if atual and atual.get("codigo") is None:          # acabou agora
            atual["codigo"] = atual["proc"].returncode
            atual["fim"] = time.time()
            atual["log"].close()
            _arq_pid().unlink(missing_ok=True)
            if atual["codigo"] == 0:
                _copiar_parciais()
                (pasta_copia_parcial() / "ultima_geracao.txt").write_text(
                    f"{atual['fim'] - atual['inicio']:.0f}")
        if geracao_externa() is not None:                  # outro painel já está gerando
            g["na_abertura"].add(str(pasta()))             # vale como a geração da abertura
            return "gerando"
        # a raiz pode ter parciais mais novos (rodar.sh parcial à mão)
        if not (atual and atual["proc"].poll() is None):
            try:
                _copiar_parciais()
            except OSError:
                pass
        est = estado_etapa5()
        if est["estado"] != "andamento":
            return "pronto"
        # toda vez que o painel é aberto (o servidor é iniciado), gera os parciais
        # uma vez na hora, sem esperar o intervalo nem leitura nova do modelo
        if str(pasta()) not in g["na_abertura"]:
            g["na_abertura"].add(str(pasta()))
            forcar = True
        script = pasta_mods() / "consultar_atividades_pubmed.py"
        if not script.exists():
            return "falhou"
        t_parcial = _mtime(pasta_copia_parcial() / "atividades_plantas_parcial.csv") or 0
        intervalo = 60 * st.session_state.get("intervalo_parcial", 10)
        ultimo = atual.get("inicio", 0) if atual else 0
        novo = (est["t_cache"] or 0) > t_parcial
        if not forcar and not (novo and time.time() - max(t_parcial, ultimo) >= intervalo):
            return "falhou" if (atual and atual.get("codigo") not in (None, 0)) else "pronto"
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        log = open(_log_gerador(), "w", encoding="utf-8", errors="replace")
        # stdin fechado: se o script fizesse uma pergunta, falharia em vez de esperar para sempre
        proc = subprocess.Popen([sys.executable, str(script), "--parcial"], cwd=str(pasta()),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        inicio = time.time()
        _arq_pid().write_text(f"{proc.pid} {inicio:.0f}")
        g["por_pasta"][str(pasta())] = {"proc": proc, "inicio": inicio, "codigo": None, "log": log}
        return "gerando"


@st.cache_data(max_entries=4)
def _resumos_lidos(caminho_str: str, mtime: float) -> tuple[int, int]:
    """(pares entidade x resumo julgados pelo modelo, quantos positivos)."""
    total = positivos = 0
    with open(caminho_str, "rb") as f:
        for linha in f:
            total += 1
            if b'"positivo": true' in linha or b'"positivo":true' in linha:
                positivos += 1
    return total, positivos


def ha_quanto(t: float | None) -> str:
    if not t:
        return ""
    m = int((time.time() - t) // 60)
    if m < 1:
        return "agora há pouco"
    if m < 60:
        return f"há {m} min"
    h = m // 60
    return f"há {h} h" if h < 48 else f"há {h // 24} dias"


def quando(t: float | None) -> str:
    if not t:
        return "—"
    d = datetime.datetime.fromtimestamp(t)
    hoje = datetime.date.today()
    return d.strftime("%H:%M") if d.date() == hoje else d.strftime("%d/%m %H:%M")


@st.fragment(run_every=20)
def quadro_etapa5():
    """Situação da etapa 5 na barra lateral; refaz a página quando os parciais mudam."""
    est = estado_etapa5()
    if est["estado"] != "andamento":
        if "_parcial_visto" in st.session_state:
            del st.session_state["_parcial_visto"]
            st.rerun(scope="app")                 # a etapa terminou: troca para os finais
        return
    situacao = disparar_parciais()
    p = pasta_copia_parcial() / "atividades_plantas_parcial.csv"
    t_p = _mtime(p)
    visto = st.session_state.get("_parcial_visto")      # 0.0 = ainda sem parcial
    st.session_state["_parcial_visto"] = t_p or 0.0
    if visto is not None and (t_p or 0.0) != visto:
        st.rerun(scope="app")                     # chegaram parciais novos: refaz a página
    cache = pasta_cache() / "cache_llm_classificacao.jsonl"
    lidos = _resumos_lidos(str(cache), _mtime(cache)) if cache.exists() else (0, 0)
    registrar_ritmo(lidos[0])
    texto = (f"**Etapa 5 (pubmed) em andamento**  \n"
             f"{fmt(lidos[0])} julgamentos do modelo ({fmt(lidos[1])} positivos), "
             f"o último às {quando(est['t_cache'])}.  \n")
    na_tela = (f"Na tela: parciais de {quando(t_p)} ({ha_quanto(t_p)})." if t_p
               else "Ainda sem resultados parciais.")
    if situacao == "gerando":
        g = _gerador()
        inicio = g["inicio"] if (g and g["proc"].poll() is None) else geracao_externa()
        dur = duracao_ultima()
        texto += (f"Gerando parciais novos: começou às {quando(inicio)} ({ha_quanto(inicio)})"
                  + (f"; a última geração levou ~{max(1, round(dur / 60))} min" if dur else
                     "; a primeira geração pode levar vários minutos")
                  + ". A página se refaz quando terminar.  \n" + na_tela)
    else:
        texto += na_tela
    if situacao == "falhou":
        st.error(texto + "  \nA última geração dos parciais falhou: veja o registro abaixo.")
    else:
        st.info(texto)
    if st.button("Atualizar os parciais agora", key="parcial_agora", disabled=situacao == "gerando",
                 width="stretch",
                 help="Gera de novo os resultados parciais com o que o modelo já leu"):
        disparar_parciais(forcar=True)
        st.rerun(scope="fragment")
    log = _log_gerador()
    if log.exists() and st.toggle("Mostrar o registro da geração", key="parcial_log"):
        st.code("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]) or "(vazio)")


# =============================================================================
# Ritmo de leitura e diagnóstico da leitura do modelo (diagnostico_leitura.py)
# =============================================================================
def _arq_ritmo() -> Path:
    return pasta_copia_parcial() / "ritmo.csv"


def registrar_ritmo(julgamentos: int):
    """Guarda (hora, nº de julgamentos no cache) a cada 2 min, para medir o ritmo."""
    arq = _arq_ritmo()
    try:
        ultima = arq.read_text(encoding="utf-8").strip().splitlines()[-1].split(",")
        t0, n0 = float(ultima[0]), int(ultima[1])
    except (OSError, IndexError, ValueError):
        t0, n0 = 0.0, -1
    if julgamentos != n0 and time.time() - t0 >= 120:
        with open(arq, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.0f},{julgamentos}\n")


def ritmo_por_hora(janela_min: int = 60) -> float | None:
    """Julgamentos por hora na última janela (precisa de 2 amostras com 10+ min
    de distância; a mais recente com menos de 15 min)."""
    try:
        r = pd.read_csv(_arq_ritmo(), header=None, names=["t", "n"])
    except (OSError, pd.errors.EmptyDataError):
        return None
    agora = time.time()
    if r.empty or agora - r["t"].iloc[-1] > 15 * 60:
        return None
    r = r[r["t"] >= r["t"].iloc[-1] - janela_min * 60]
    dt = r["t"].iloc[-1] - r["t"].iloc[0]
    dn = r["n"].iloc[-1] - r["n"].iloc[0]
    return dn / dt * 3600 if dt >= 600 and dn > 0 else None


def _dir_diag() -> Path:
    d = pasta_copia_parcial() / "diagnostico"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _vivo_pelo_arquivo(arq: Path, horas: int = 6) -> float | None:
    try:
        pid, inicio = arq.read_text().split()
        pid, inicio = int(pid), float(inicio)
    except (OSError, ValueError):
        return None
    if time.time() - inicio < horas * 3600 and _vivo(pid):
        return inicio
    arq.unlink(missing_ok=True)
    return None


def gerando_parciais() -> bool:
    g = _gerador()
    return bool((g and g["proc"].poll() is None) or geracao_externa() is not None)


def disparar_diagnostico(pedir: bool = False) -> str:
    """Roda o diagnostico_leitura.py em segundo plano. Devolve 'rodando',
    'esperando' (aguarda a geração dos parciais acabar: os dois juntos pesam na
    memória), 'pronto', 'falhou' ou 'sem_script'."""
    g = _geradores()
    chave = str(pasta())
    with g["trava"]:
        diag = g.setdefault("diag", {})
        pedidos = g.setdefault("diag_pedido", set())
        atual = diag.get(chave)
        if atual and atual["proc"].poll() is None:
            return "rodando"
        if atual and atual.get("codigo") is None:
            atual["codigo"] = atual["proc"].returncode
            atual["log"].close()
            (_dir_diag() / "rodando.pid").unlink(missing_ok=True)
        if _vivo_pelo_arquivo(_dir_diag() / "rodando.pid") is not None:
            return "rodando"
        script = pasta_mods() / "diagnostico_leitura.py"
        if not script.exists():
            script = pasta() / "diagnostico_leitura.py"     # formato antigo
        if not script.exists():
            return "sem_script"
        if pedir:
            pedidos.add(chave)
        if chave not in pedidos:
            return "falhou" if (atual and atual.get("codigo") not in (None, 0)) else "pronto"
        if gerando_parciais():
            return "esperando"
        pedidos.discard(chave)
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        log = open(_dir_diag() / "diagnostico.log", "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen([sys.executable, str(script), "--saida", str(_dir_diag())], cwd=str(pasta()),
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (_dir_diag() / "rodando.pid").write_text(f"{proc.pid} {time.time():.0f}")
        diag[chave] = {"proc": proc, "inicio": time.time(), "codigo": None, "log": log}
        return "rodando"


def meta_diagnostico() -> dict | None:
    try:
        import json
        return json.loads((_dir_diag() / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ler_diag(nome: str) -> pd.DataFrame | None:
    p = _dir_diag() / nome
    m = _mtime(p)
    return _ler(str(p), m, None, "__sem_traducao__") if m else None


# =============================================================================
# Utilidades
# =============================================================================
def fmt(n) -> str:
    try:
        if isinstance(n, float) and not n.is_integer():
            return f"{n:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def pct(a, b) -> str:
    if not b:
        return "—"
    r = 100 * a / b
    return "<1%" if 0 < r < 1 else f"{r:.0f}%"


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def vazio(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype(str).str.strip().isin(["", "nan", "None"])


def itens(s: pd.Series) -> pd.Series:
    """'a; b; c' -> uma linha por item (sem vazios)."""
    x = s.dropna().astype(str).str.split(SEP, regex=True).explode().str.strip()
    return x[x.ne("") & x.ne("nan")]


def opcoes(s: pd.Series, ordem=None) -> list:
    v = itens(s).value_counts()
    if ordem:
        return [o for o in ordem if o in v.index] + [o for o in v.index if o not in ordem]
    return v.index.tolist()


def contem_algum(s: pd.Series, escolhidos) -> pd.Series:
    """Linhas cuja lista 'a; b; c' tem ao menos um dos itens escolhidos."""
    if not escolhidos:
        return pd.Series(True, index=s.index)
    padrao = r"(?:^|;)\s*(?:" + "|".join(re.escape(x) for x in escolhidos) + r")\s*(?:;|$)"
    return s.fillna("").astype(str).str.contains(padrao, regex=True, case=False)


def busca(s: pd.Series, texto: str) -> pd.Series:
    if not texto:
        return pd.Series(True, index=s.index)
    return s.fillna("").astype(str).str.contains(re.escape(texto.strip()), case=False, regex=True)


def melhor_nivel(texto) -> str:
    """'in vitro; in vivo' -> 'in vivo' (a evidência mais forte)."""
    if not isinstance(texto, str) or not texto.strip():
        return "não informado"
    partes = [p.strip() for p in re.split(SEP, texto) if p.strip()]
    partes = [p for p in partes if p in NIVEL] or ["não informado"]
    return min(partes, key=lambda p: NIVEL[p])


def link_pubmed(pmid) -> str | None:
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if isinstance(pmid, str) and pmid.strip() else None


def link_pubchem(cid) -> str | None:
    if isinstance(cid, str) and re.fullmatch(r"\d+(\.0)?", cid.strip()):
        return f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid.strip().split('.')[0]}"
    return None


def link_chembl(cid) -> str | None:
    return f"https://www.ebi.ac.uk/chembl/compound_report_card/{cid}/" if isinstance(cid, str) and cid.startswith("CHEMBL") else None


def limpo(df: pd.DataFrame) -> pd.DataFrame:
    """Células de texto vazias em branco (e não 'None') na tela."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object or pd.api.types.is_string_dtype(df[c]):
            df[c] = df[c].where(df[c].notna(), "")
    return df


def nada(msg: str):
    st.info(msg, icon="ℹ️")


def tabela(df: pd.DataFrame, nome_arquivo: str, config: dict | None = None, altura: int = 420,
           chave: str | None = None):
    """Tabela com download do recorte (CSV UTF-8 com BOM, abre no Excel)."""
    st.caption(f"{fmt(len(df))} linha(s)")
    mostrar = limpo(df.head(20000))
    if len(df) > 20000:
        st.caption("Mostrando as 20.000 primeiras; o download traz todas.")
    st.dataframe(mostrar, hide_index=True, height=altura, column_config=config or {},
                 width="stretch", key=chave)
    st.download_button("Baixar esta tabela (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name=nome_arquivo, mime="text/csv", key=f"dl_{chave or nome_arquivo}")


MILHAR = "replace(datum.label, /,/g, '.')"   # 12,345 -> 12.345 nos eixos


def barras(contagem: pd.Series, titulo: str, eixo: str, cor=AZUL, top: int = 25, cores: dict | None = None,
           italico=False, altura_barra=24, ordenar=True):
    """Barras horizontais (maior em cima) a partir de uma Series rótulo -> valor."""
    if contagem is None or contagem.empty:
        return
    c = contagem.sort_values(ascending=False).head(top) if ordenar else contagem.head(top)
    df = pd.DataFrame({"rotulo": c.index.astype(str), "valor": c.values})
    df["texto"] = df["valor"].map(fmt)
    if cores is None:   # "sem classificação", "não informado", "outros"... em cinza
        neutro = df["rotulo"].str.lower().str.match(r"^\(?(sem |não informado|outros|desconhecid|distribuição desc)")
        if neutro.any():
            cores = {r: (CINZA if n else cor) for r, n in zip(df["rotulo"], neutro)}
    cor_enc = (alt.Color("rotulo:N", scale=alt.Scale(domain=list(cores), range=list(cores.values())),
                         legend=None) if cores else alt.value(cor))
    base = alt.Chart(df).encode(
        y=alt.Y("rotulo:N", sort=df["rotulo"].tolist(), title=None, scale=alt.Scale(paddingInner=0.28),
                axis=alt.Axis(labelLimit=260, labelFontStyle="italic" if italico else "normal")),
        x=alt.X("valor:Q", title=eixo, axis=alt.Axis(format=",d", grid=True, labelExpr=MILHAR)),
        tooltip=[alt.Tooltip("rotulo:N", title=""), alt.Tooltip("texto:N", title=eixo)])
    graf = base.mark_bar(cornerRadiusEnd=3).encode(color=cor_enc) + \
        base.mark_text(align="left", dx=4, fontSize=11, color="#52514e").encode(text="texto:N")
    st.altair_chart(graf.properties(title=titulo, height=altura_barra * len(df) + 120), width="stretch")


def barras_agrupadas(df: pd.DataFrame, cat: str, serie: str, valor: str, titulo: str, eixo: str,
                     ordem_series=None):
    if df.empty:
        return
    ordem_series = ordem_series or df[serie].unique().tolist()
    graf = alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y(f"{cat}:N", sort=alt.EncodingSortField(valor, op="sum", order="descending"), title=None,
                axis=alt.Axis(labelLimit=240)),
        yOffset=alt.YOffset(f"{serie}:N", sort=ordem_series),
        x=alt.X(f"{valor}:Q", title=eixo, axis=alt.Axis(format=",d", labelExpr=MILHAR)),
        color=alt.Color(f"{serie}:N", scale=alt.Scale(domain=ordem_series, range=SERIE[:len(ordem_series)]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[f"{cat}:N", f"{serie}:N", alt.Tooltip(f"{valor}:Q", format=",d")])
    n = df[cat].nunique()
    st.altair_chart(graf.properties(title=titulo, height=n * 16 * len(ordem_series) + 150),
                    width="stretch")


def empilhado_100(df: pd.DataFrame, cat: str, serie: str, valor: str, titulo: str, ordem_series, cores):
    if df.empty:
        return
    graf = alt.Chart(df).mark_bar().encode(
        y=alt.Y(f"{cat}:N", title=None, sort=None),
        x=alt.X(f"sum({valor}):Q", stack="normalize", title=None, axis=alt.Axis(format="%")),
        color=alt.Color(f"{serie}:N", scale=alt.Scale(domain=ordem_series, range=cores),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("ordem:Q"),
        tooltip=[f"{cat}:N", f"{serie}:N", alt.Tooltip(f"{valor}:Q", format=",d")])
    df = df.assign(ordem=df[serie].map({s: i for i, s in enumerate(ordem_series)}))
    st.altair_chart(graf.properties(data=df, title=titulo, height=34 * df[cat].nunique() + 150),
                    width="stretch")


def metricas(pares):
    cols = st.columns(len(pares))
    for c, (rotulo, valor, *ajuda) in zip(cols, pares):
        c.metric(rotulo, valor, help=ajuda[0] if ajuda else None)


def multiselect_lateral(rotulo, opcoes_, chave, ajuda=None):
    return st.sidebar.multiselect(rotulo, opcoes_, key=chave, help=ajuda, placeholder="todos")


# =============================================================================
# Dados derivados (com cache)
# =============================================================================
# =============================================================================
# Escopo: plantas da região x plantas de fora ([bioativos] escopo = completo)
# =============================================================================
FORA = "não"


def so_da_regiao() -> bool:
    """O painel retrata a PROSPECÇÃO da região. Com [bioativos] escopo =
    completo as bases químicas entram inteiras, e as plantas de fora da região
    ficariam misturadas nas contagens - por isso ficam de fora por padrão,
    com o interruptor em Configurações. A página do Banco não filtra: ela
    mostra o banco publicável como ele está."""
    return st.session_state.get("so_regiao", True)


def fora_da_regiao(s: pd.Series) -> pd.Series:
    return s.fillna("").str.strip().str.lower().eq(FORA)


def filtrar_regiao(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Tira as linhas de plantas de fora da região, se o interruptor pedir."""
    if df is None or "na_regiao" not in df.columns or not so_da_regiao():
        return df
    return df[~fora_da_regiao(df["na_regiao"])]


@st.cache_data(max_entries=8)
def _iks_da_regiao(chave: tuple) -> frozenset | None:
    """InChIKeys com ao menos uma planta da região; None = nada de fora
    (escopo regiao, ou planilha anterior à v3.18: nada a filtrar)."""
    for nome, col_ik in [("banco/origem_biologica.csv", "inchikey"),
                         ("especies_com_compostos_bioativos.csv", "composto_inchikey")]:
        if caminho(nome) is None:
            continue
        df = ler(nome, [col_ik, "na_regiao"])
        if df is None or "na_regiao" not in df.columns or df["na_regiao"].isna().all():
            continue
        if not fora_da_regiao(df["na_regiao"]).any():
            return None
        dentro = df.loc[~fora_da_regiao(df["na_regiao"]), col_ik].dropna()
        return frozenset(dentro.str.strip().str.upper())
    return None


def iks_da_regiao() -> frozenset | None:
    p = caminho("banco/origem_biologica.csv") or caminho("especies_com_compostos_bioativos.csv")
    if p is None:
        return None
    return _iks_da_regiao((str(p), p.stat().st_mtime))


def aviso_escopo():
    """Uma linha dizendo que há plantas de fora da região, e o que o painel fez."""
    if iks_da_regiao() is None:
        return
    if so_da_regiao():
        st.caption("Há compostos de plantas de **fora da região** nesta rodada "
                   "(`[bioativos] escopo = completo`); eles estão fora desta página. "
                   "Para incluí-los, desligue *Só as plantas da região* em **Configurações**.")
    else:
        st.caption("Incluindo os compostos de plantas de **fora da região** "
                   "(`[bioativos] escopo = completo`).")


# as quatro colunas por fonte da etapa bioativos, mais o veredito
COLUNAS_SMILES_FONTE = ["smiles_npass", "smiles_coconut", "smiles_lotus", "smiles_pubchem",
                        "conferencia_smiles"]

COLS_PLANTAS = ["nome_cientifico", "nome_aceito", "nome_popular_pt", "familia", "ordem",
                "categoria_taxonomica", "n_ocorrencias_na_area", "situacao_nome", "fonte",
                "estados_br", "dominios_br", "endemismo_br", "origem_br", "fonte_distribuicao",
                "nomes_juntados", "atividades_artigos", "speciesKey"]


def plantas() -> pd.DataFrame | None:
    return ler("plantas.csv", COLS_PLANTAS)


def planta_composto() -> pd.DataFrame | None:
    """Pares planta x composto: inchikey (ou id da base), nome do composto, planta.
    Do banco (origem_biologica) quando existe; senão da etapa bioativos."""
    if tem_banco() and caminho("banco/origem_biologica.csv"):
        ob = ler("banco/origem_biologica.csv", ["inchikey", "nome_cientifico", "familia", "bases",
                                                "parte_planta", "teor", "referencias", "na_regiao"])
        ob = filtrar_regiao(ob)
        comp = ler("banco/compostos.csv", ["inchikey", "nome_preferido"])
        nomes = dict(zip(comp["inchikey"], comp["nome_preferido"])) if comp is not None else {}
        return ob.assign(composto=ob["inchikey"].map(nomes).fillna(ob["inchikey"]))
    bio = ler("especies_com_compostos_bioativos.csv",
              ["composto_nome", "composto_id", "composto_inchikey", "nome_cientifico", "familia", "base",
               "parte_planta_duke", "teor_ppm_duke", "referencias_lotus", "na_regiao"])
    bio = filtrar_regiao(bio)
    if bio is None:
        return None
    ik = bio["composto_inchikey"].fillna("").str.strip().str.upper()
    valido = ik.str.match(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
    return pd.DataFrame({
        "inchikey": ik.where(valido, "ID:" + bio["composto_id"].fillna("?")),
        "nome_cientifico": bio["nome_cientifico"], "familia": bio["familia"], "bases": bio["base"],
        "parte_planta": bio["parte_planta_duke"], "teor": bio["teor_ppm_duke"],
        "referencias": bio["referencias_lotus"],
        "composto": bio["composto_nome"].fillna(ik)}).drop_duplicates(["inchikey", "nome_cientifico"])


# Divergência estrutural entre as bases. Existe em dois lugares, com nomes
# diferentes: no banco relacional é um conflito registrado em conflicts.csv
# (com severidade e resolução), e nas planilhas da raiz é a coluna
# conferencia_smiles. Quando há banco, a fonte nativa dele é a preferida.
CONFLITO_PARA_VEREDITO = {
    # estrutura divergente entre as bases
    "estrutura_entre_bases": "estruturas diferentes",
    "structure_between_sources": "estruturas diferentes",
    "id_x_estrutura": "estruturas diferentes",
    "id_vs_structure": "estruturas diferentes",
    "nome_x_estrutura": "estruturas diferentes",
    "name_vs_structure": "estruturas diferentes",
    # a própria base se contradiz: o InChIKey que ela declara não é o do SMILES dela
    "inchikey_declarado_x_smiles": "InChIKey não corresponde ao SMILES",
    "reported_inchikey_vs_smiles": "InChIKey não corresponde ao SMILES",
    "smiles_invalido": "SMILES inválido",
    "unparseable_smiles": "SMILES inválido",
    "formula_entre_bases": "fórmula divergente",
    "formula_between_sources": "fórmula divergente",
    "variantes_estereo": "estereoquímica diferente",
    "stereo_variants": "estereoquímica diferente",
    "sal_ou_forma_carregada": "sal ou forma carregada",
    "salt_or_charged_form": "sal ou forma carregada",
}
SEM_CONFLITO = "sem conflito registrado"
# do mais para o menos grave: um composto com vários conflitos fica com o pior
ORDEM_VEREDITO = ["estruturas diferentes", "InChIKey não corresponde ao SMILES",
                  "SMILES inválido", "fórmula divergente", "estereoquímica diferente",
                  "sal ou forma carregada"]
# os que pedem olho humano na estrutura
VEREDITOS_PARA_CONFERIR = ORDEM_VEREDITO[:3]


@st.cache_data(max_entries=8)
def _divergencias(chave: tuple) -> pd.Series:
    """InChIKey -> veredito da comparação dos SMILES entre as bases."""
    if chave[0] == "banco":
        conf = ler("banco/conflitos.csv", ["inchikey", "tipo_conflito"])
        if conf is None or conf.empty:
            return pd.Series(dtype=object)
        conf = conf.assign(v=conf["tipo_conflito"].map(CONFLITO_PARA_VEREDITO)).dropna(subset=["v"])
        if conf.empty:
            return pd.Series(dtype=object)
        # um composto pode ter mais de um conflito: fica o mais grave
        peso = {v: i for i, v in enumerate(ORDEM_VEREDITO)}
        conf = conf.sort_values("v", key=lambda s: s.map(peso))
        return conf.groupby("inchikey")["v"].first()
    bio = ler("especies_com_compostos_bioativos.csv",
              ["composto_inchikey", "conferencia_smiles"])
    if bio is None or "conferencia_smiles" not in bio.columns:
        return pd.Series(dtype=object)
    bio = bio.dropna(subset=["conferencia_smiles"])
    if bio.empty:
        return pd.Series(dtype=object)
    ik = bio["composto_inchikey"].fillna("").str.strip().str.upper()
    # "estruturas diferentes: A x B" -> "estruturas diferentes", para o filtro
    # funcionar igual nos dois modos; o detalhe fica na Ficha
    rotulo = bio["conferencia_smiles"].str.split(":").str[0].str.strip()
    peso = {v: i for i, v in enumerate(ORDEM_VEREDITO)}
    d = bio.assign(inchikey=ik, v=rotulo).sort_values(
        "v", key=lambda s: s.map(lambda x: peso.get(x, len(peso))))
    return d.groupby("inchikey")["v"].first()


def divergencias() -> pd.Series:
    p = caminho("banco/compostos.csv") or caminho("especies_com_compostos_bioativos.csv")
    if p is None:
        return pd.Series(dtype=object)
    modo = "banco" if tem_banco() else "etapa"
    extra = caminho("banco/conflitos.csv") if modo == "banco" else None
    return _divergencias((modo, str(p), p.stat().st_mtime,
                          extra.stat().st_mtime if extra else 0))


@st.cache_data(show_spinner="Montando a tabela de compostos...", max_entries=6)
def _compostos(chave: tuple, iks_regiao: frozenset | None = None) -> pd.DataFrame:
    """Uma linha por composto, com as colunas usadas nos filtros e gráficos,
    do banco (preferido) ou da etapa bioativos (sem o banco). Com iks_regiao,
    só os compostos que ocorrem em alguma planta da região."""
    if chave[0] == "banco":
        c = ler("banco/compostos.csv", ["inchikey", "nome_preferido", "nome_iupac", "pubchem_cid",
                                        "formula_molecular", "massa_molecular", "xlogp_pubchem", "tpsa_pubchem",
                                        "classyfire_superclass", "classyfire_class", "np_classifier_pathway",
                                        "np_classifier_superclass", "bases", "n_bases", "n_plantas",
                                        "n_bioatividades", "n_conflitos", "smiles_isomerico"])
        ad = ler("banco/perfil_admet.csv", ["inchikey", "qed", "logp_crippen", "tpsa", "massa_molecular_rdkit",
                                            "violacoes_lipinski", "lipinski_ok", "veber_ok",
                                            "absorcao_gi_provavel", "permeacao_bhe_provavel",
                                            "alertas_pains", "alertas_brenk"])
        df = c.merge(ad, on="inchikey", how="left") if ad is not None else c
        df = df.rename(columns={"nome_preferido": "nome", "np_classifier_pathway": "via",
                                "classyfire_superclass": "superclasse"})
        df["massa"] = num(df["massa_molecular"]).fillna(num(df.get("massa_molecular_rdkit")))
        df["logp"] = num(df.get("logp_crippen")).fillna(num(df["xlogp_pubchem"]))
        df["tpsa_"] = num(df.get("tpsa")).fillna(num(df["tpsa_pubchem"]))
        df["qed_"] = num(df.get("qed"))
        df["np_likeness"] = float("nan")
        df["n_plantas_"] = num(df["n_plantas"])
        if iks_regiao is not None:
            df = df[df["inchikey"].isin(iks_regiao)]
        return anexar_divergencia(df)
    bio = ler("especies_com_compostos_bioativos.csv",
              ["composto_nome", "composto_id", "composto_inchikey", "nome_cientifico", "base", "pubchem_cid",
               "np_classifier_pathway", "np_classifier_superclass", "chemical_class", "chemical_super_class",
               "qed_drug_likeliness", "np_likeness", "molecular_formula", "composto_smiles",
               "estados_composto", "na_regiao"])
    bio = filtrar_regiao(bio)
    ik = bio["composto_inchikey"].fillna("").str.strip().str.upper()
    bio["inchikey"] = ik.where(ik.str.match(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$"), "ID:" + bio["composto_id"].fillna("?"))
    g = bio.groupby("inchikey", sort=False)
    df = g.agg(nome=("composto_nome", "first"), pubchem_cid=("pubchem_cid", "first"),
               via=("np_classifier_pathway", "first"), np_classifier_superclass=("np_classifier_superclass", "first"),
               superclasse=("chemical_super_class", "first"), classyfire_class=("chemical_class", "first"),
               formula_molecular=("molecular_formula", "first"), qed=("qed_drug_likeliness", "first"),
               np_likeness=("np_likeness", "first"), smiles_isomerico=("composto_smiles", "first"),
               estados_composto=("estados_composto", "first"),
               n_plantas_=("nome_cientifico", "nunique")).reset_index()
    bases = bio.assign(b=bio["base"].fillna("").str.split(SEP)).explode("b")
    bases = bases[bases["b"].str.strip().ne("")].groupby("inchikey")["b"].agg(lambda s: "; ".join(sorted(set(s))))
    df["bases"] = df["inchikey"].map(bases)
    df["qed_"] = num(df["qed"])
    df["np_likeness"] = num(df["np_likeness"])
    for c in ["massa", "logp", "tpsa_"]:
        df[c] = float("nan")
    return anexar_divergencia(df)


def anexar_divergencia(df: pd.DataFrame) -> pd.DataFrame:
    """Coluna conferencia_smiles com o veredito da comparação entre as bases."""
    d = divergencias()
    if d.empty:
        df["conferencia_smiles"] = None
        return df
    df["conferencia_smiles"] = df["inchikey"].map(d)
    tem_smiles = df["smiles_isomerico"].notna() if "smiles_isomerico" in df.columns else True
    df.loc[df["conferencia_smiles"].isna() & tem_smiles, "conferencia_smiles"] = SEM_CONFLITO
    return df


def compostos() -> pd.DataFrame | None:
    iks = iks_da_regiao() if so_da_regiao() else None
    if tem_banco():
        p = caminho("banco/compostos.csv")
        a = caminho("banco/perfil_admet.csv")
        return _compostos(("banco", p.stat().st_mtime, a.stat().st_mtime if a else 0, str(pasta()),
                           iks is not None), iks)
    p = caminho("especies_com_compostos_bioativos.csv")
    if p is None:
        return None
    return _compostos(("etapa", p.stat().st_mtime, str(pasta()), iks is not None))


def evidencias_pubmed() -> pd.DataFrame | None:
    ev = ler("evidencias_pubmed.csv", ["tipo_entidade", "entidade", "InChIKey", "PMID", "ano", "revista",
                                       "titulo", "DOI", "atividades", "tipo_estudo", "parte_planta",
                                       "justificativa_llm", "via_busca", "link"])
    if ev is None:
        return None
    ev = ev.copy()
    ev["nivel"] = ev["tipo_estudo"].map(melhor_nivel)
    ev["link"] = ev["link"].fillna(ev["PMID"].map(link_pubmed))
    return ev


def evidencias_chembl() -> pd.DataFrame | None:
    """Registros de ensaio ativos: do banco (ChEMBL + NPASS) ou da etapa chembl."""
    if tem_banco() and caminho("banco/bioatividade.csv"):
        b = ler("banco/bioatividade.csv", ["inchikey", "fonte", "natureza", "correspondencia", "molecula_ensaiada",
                                           "atividade_input", "alvo", "organismo_alvo", "tipo_ensaio",
                                           "descricao_ensaio", "tipo_medida", "relacao", "valor", "unidade",
                                           "pvalor", "ativo", "pmid", "doi", "ano", "id_registro_fonte"])
        b = b[b["fonte"].ne("PubMed")].copy()
        return b.rename(columns={"inchikey": "InChIKey", "atividade_input": "atividade", "tipo_medida": "medida",
                                 "pvalor": "pchembl", "pmid": "PMID", "doi": "DOI",
                                 "id_registro_fonte": "documento"})
    ev = ler("evidencias_chembl.csv", ["InChIKey", "composto", "atividade", "correspondencia", "molecula_ensaiada",
                                       "alvo", "organismo_alvo", "descricao_ensaio", "tipo_ensaio", "medida",
                                       "relacao", "valor", "unidade", "pchembl", "PMID", "DOI", "ano",
                                       "documento_chembl"])
    if ev is None:
        return None
    return ev.assign(fonte="ChEMBL", ativo="true").rename(columns={"documento_chembl": "documento"})


def filtros_distribuicao(prefixo: str, df: pd.DataFrame):
    """Filtros de distribuição na barra lateral; devolve a máscara."""
    m = pd.Series(True, index=df.index)
    if "estados_br" in df and df["estados_br"].notna().any():
        ufs = multiselect_lateral("Estados (UF)", UFS, f"{prefixo}_uf",
                                  "Plantas que ocorrem em ao menos um dos estados escolhidos")
        m &= contem_algum(df["estados_br"], ufs)
    if "dominios_br" in df and df["dominios_br"].notna().any():
        dom = multiselect_lateral("Domínios", opcoes(df["dominios_br"], DOMINIOS), f"{prefixo}_dom")
        m &= contem_algum(df["dominios_br"], dom)
    if "endemismo_br" in df and df["endemismo_br"].notna().any():
        en = multiselect_lateral("Endemismo", opcoes(df["endemismo_br"]), f"{prefixo}_end")
        if en:
            m &= df["endemismo_br"].isin(en)
    if "origem_br" in df and df["origem_br"].notna().any():
        orig = multiselect_lateral("Origem", opcoes(df["origem_br"]), f"{prefixo}_orig")
        m &= contem_algum(df["origem_br"], orig)
    return m


# =============================================================================
# Páginas
# =============================================================================
def pagina_inicio():
    st.title("Painel do pipeline de prospecção")
    st.caption(f"Pasta do projeto: `{pasta()}`")
    linhas_tab = []
    est5 = estado_etapa5()["estado"]
    for n, eid, arq, desc in ETAPAS:
        p = caminho(arq)
        if eid == "pubmed" and est5 == "andamento":
            sit = "em andamento: resultados parciais" if p else "em andamento: gerando os parciais"
            arq_ = arq.replace(".csv", "_parcial.csv")
        elif n in ("6", "7", "8") and est5 == "andamento":
            sit, arq_ = "aguardando a etapa 5 terminar", arq
        else:
            sit, arq_ = ("concluída" if p else "não rodou ainda"), arq
        linhas_tab.append({"etapa": f"{n} · {eid}", "o que tem": desc, "arquivo": arq_,
                           "situação": sit,
                           "linhas": "" if (p is None or arq.endswith((".txt", "/")))
                                     else fmt(linhas(arq)),
                           "atualizado em": (datetime.datetime.fromtimestamp(p.stat().st_mtime)
                                             .strftime("%d/%m/%Y %H:%M") if p else None)})
    t = pd.DataFrame(linhas_tab)
    feitas = (t["situação"] == "concluída").sum()
    st.subheader(f"Etapas: {feitas} de {len(t)} com resultado")
    st.dataframe(t, hide_index=True, width="stretch")
    st.caption("Etapa 0 (downloads): a lista das bases e a situação de cada download estão em `bases_baixadas.txt`.")
    if est5 == "andamento":
        st.info("A etapa 5 (pubmed) **ainda está rodando**. O painel mostra os **resultados parciais**: "
                "o que o modelo já leu, atualizado sozinho em segundo plano (veja o quadro na barra "
                "lateral). O banco relacional e a análise de qualidade (etapas 6 a 8) aparecem quando "
                "a etapa 5 terminar.", icon="⏳")

    # funil
    pl, comp, apl = plantas(), compostos(), ler("atividades_plantas.csv", ["n_artigos_positivos"])
    gb = ler("especies_gbif.csv", ["nome_cientifico"])
    passos = []
    if gb is not None:
        passos.append(("Plantas", "espécies na região (GBIF)", len(gb)))
    if pl is not None:
        passos.append(("Plantas", "plantas na lista final", len(pl)))
    pc = planta_composto()
    if pc is not None:
        passos.append(("Plantas", "com compostos conhecidos", pc["nome_cientifico"].nunique()))
    if apl is not None:
        passos.append(("Plantas", "com atividade em artigos", int((num(apl["n_artigos_positivos"]).fillna(0) > 0).sum())))
    if comp is not None:
        passos.append(("Compostos", "compostos distintos", len(comp)))
    ch = evidencias_chembl()
    if ch is not None:
        ativos = ch[ch["ativo"].astype(str).str.lower().isin(["true", "1", "sim"])]
        passos.append(("Compostos", "com ensaio ativo (ChEMBL/NPASS)", ativos["InChIKey"].nunique()))
    ev = evidencias_pubmed()
    if ev is not None:
        passos.append(("Compostos", "com atividade em artigos", ev.loc[ev["tipo_entidade"] == "composto", "InChIKey"].nunique()))
    if passos:
        st.subheader("Do levantamento às evidências")
        cols = st.columns(2)
        for col, ent, cor in zip(cols, ["Plantas", "Compostos"], [AZUL, LARANJA]):
            sub = [(r, v) for e, r, v in passos if e == ent]
            if sub:
                with col:
                    barras(pd.Series(dict(sub)), ent, "quantidade", cor=cor, ordenar=False)
    st.markdown("""
**Como usar.** Escolha uma página no menu à esquerda. Os filtros ficam na barra lateral e
valem para tudo da página; cada tabela tem um botão para baixar o recorte em CSV.
A página **Prospecção** cruza as etapas para listar plantas candidatas, e a **Ficha** reúne
tudo sobre uma planta ou um composto. Nada é alterado nos arquivos do pipeline.
""")


def pagina_gbif():
    st.title("1 · GBIF: plantas com registro na região")
    df = ler("especies_gbif.csv", ["nome_cientifico", "familia", "ordem", "nome_popular_pt",
                                   "n_ocorrencias_na_area", "speciesKey"])
    if df is None:
        return nada("`especies_gbif.csv` não encontrado: a etapa 1 ainda não rodou (ou foi pulada).")
    df = df.assign(registros=num(df["n_ocorrencias_na_area"]).fillna(0).astype(int))
    st.sidebar.header("Filtros")
    txt = st.sidebar.text_input("Nome científico ou popular contém", key="gb_txt")
    fam = multiselect_lateral("Família", opcoes(df["familia"]), "gb_fam")
    mx = int(df["registros"].max() or 1)
    rmin = st.sidebar.number_input("Mínimo de registros", 0, mx, 0, key="gb_min")
    m = (busca(df["nome_cientifico"], txt) | busca(df["nome_popular_pt"], txt)) & df["registros"].ge(rmin)
    if fam:
        m &= df["familia"].isin(fam)
    f = df[m]
    metricas([("Espécies", fmt(len(f))), ("Registros", fmt(f["registros"].sum())),
              ("Famílias", fmt(f["familia"].nunique())),
              ("Com 1 registro só", fmt((f["registros"] == 1).sum()), "espécies raras ou pouco amostradas")])
    c1, c2 = st.columns(2)
    with c1:
        barras(f.set_index("nome_cientifico")["registros"], "Espécies mais registradas", "registros", italico=True)
    with c2:
        barras(f.groupby(f["familia"].fillna("(sem família)"))["nome_cientifico"].nunique(),
               "Famílias com mais espécies", "espécies")
    t = f.drop(columns=["n_ocorrencias_na_area"]).sort_values("registros", ascending=False)
    t["GBIF"] = t["speciesKey"].map(lambda k: f"https://www.gbif.org/species/{k}"
                                    if isinstance(k, str) and k.strip().isdigit() else None)
    tabela(t.drop(columns=["speciesKey"]), "gbif_recorte.csv",
           {"GBIF": st.column_config.LinkColumn("GBIF", display_text="abrir")}, chave="gb_tab")


# ---- etapa 5 nas páginas de plantas e compostos ------------------------------
SITUACOES_ETAPA5 = ["com artigo positivo", "leitura pendente", "lida, sem positivo", "sem artigo no PubMed",
                    "busca pendente", "não pesquisada", "fora da etapa 5"]


def situacao_curta(status, n_pos: int) -> str:
    if n_pos:
        return "com artigo positivo"
    if not isinstance(status, str) or not status.strip():
        return "fora da etapa 5"
    s = status.strip()
    if s.startswith("artigos encontrados"):
        return "leitura pendente"
    if s.startswith("nenhuma relação"):
        return "lida, sem positivo"
    if s.startswith("nenhum artigo"):
        return "sem artigo no PubMed"
    if s.startswith("busca pendente"):
        return "busca pendente"
    if s.startswith("não pesquisad"):
        return "não pesquisada"
    return "com artigo positivo"


@st.cache_data(show_spinner=False, max_entries=16)
def _resumo_pubmed(marca: tuple, tipo: str, ativ: tuple, nivel: str) -> pd.DataFrame:
    """Por planta (nome) ou composto (InChIKey): artigos positivos, atividades e
    melhor evidência, só com os artigos da atividade e evidência escolhidas."""
    ev = evidencias_pubmed()
    vazio_ = pd.DataFrame(columns=["artigos_positivos", "atividades_pubmed", "melhor_evidencia"])
    if ev is None or ev.empty:
        return vazio_
    chave = "entidade" if tipo == "planta" else "InChIKey"
    e = ev[ev["tipo_entidade"].eq(tipo) & ev[chave].notna()]
    if ativ:
        e = e[contem_algum(e["atividades"].str.lower(), list(ativ))]
    e = e[e["nivel"].map(NIVEL).le(NIVEL[nivel])]
    if e.empty:
        return vazio_
    g = e.groupby(chave)
    at = (e.assign(a=e["atividades"].fillna("").str.lower().str.split(SEP, regex=True)).explode("a")
          .assign(a=lambda d: d["a"].str.strip()).query("a != ''"))
    contagem = at.groupby([chave, "a"])["PMID"].nunique().reset_index().sort_values(
        [chave, "PMID"], ascending=[True, False])
    texto = contagem.groupby(chave).apply(
        lambda d: "; ".join(f"{a} ({n})" for a, n in zip(d["a"].head(5), d["PMID"].head(5)))
        + (f"; +{len(d) - 5}" if len(d) > 5 else ""), include_groups=False)
    return pd.DataFrame({"artigos_positivos": g["PMID"].nunique(), "atividades_pubmed": texto,
                         "melhor_evidencia": g["nivel"].agg(lambda s: min(s, key=NIVEL.get))})


def resumo_pubmed(tipo: str, ativ=(), nivel: str = "não informado") -> pd.DataFrame | None:
    p = caminho("evidencias_pubmed.csv")
    if p is None:
        return None
    return _resumo_pubmed((str(p), p.stat().st_mtime), tipo, tuple(sorted(ativ)), nivel)


def status_etapa5(tipo: str) -> pd.Series:
    if tipo == "planta":
        a = ler("atividades_plantas.csv", ["nome_cientifico", "atividades_relatadas_planta"])
        if a is None:
            return pd.Series(dtype=object)
        return a.drop_duplicates("nome_cientifico").set_index("nome_cientifico")["atividades_relatadas_planta"]
    a = ler("atividades_compostos.csv", ["InChIKey", "atividades_relatadas_composto"])
    if a is None:
        return pd.Series(dtype=object)
    a = a.dropna(subset=["InChIKey"])
    # um composto aparece uma vez por planta: fica o status mais informativo
    a = a.assign(_pos=~a["atividades_relatadas_composto"].fillna("").str.match(r"(não |nenhum|artigos encontr|busca)"))
    return a.sort_values("_pos", ascending=False).drop_duplicates("InChIKey").set_index("InChIKey")[
        "atividades_relatadas_composto"]


def etapa5_na_pagina(df: pd.DataFrame, chave_col: str, tipo: str, prefixo: str) -> tuple:
    """Filtros da etapa 5 na barra lateral e as colunas dela para a tabela.
    Devolve (máscara, df com as colunas novas)."""
    tudo = resumo_pubmed(tipo)
    if tudo is None and caminho("atividades_plantas.csv") is None:
        return pd.Series(True, index=df.index), df
    tudo = tudo if tudo is not None else pd.DataFrame(columns=["artigos_positivos", "atividades_pubmed",
                                                               "melhor_evidencia"])
    st.sidebar.subheader("Etapa 5 (PubMed)" + (" · parcial" if estado_etapa5()["estado"] == "andamento" else ""))
    ev = evidencias_pubmed()
    rotulos = opcoes(ev.loc[ev["tipo_entidade"].eq(tipo), "atividades"].str.lower()) if ev is not None else []
    sit = multiselect_lateral("Situação na etapa 5", SITUACOES_ETAPA5, f"{prefixo}_s5",
                              "com artigo positivo · leitura pendente (o modelo ainda não leu) · lida, sem positivo · "
                              "sem artigo no PubMed · não pesquisada (fora da busca pela configuração)")
    ativ = multiselect_lateral("Atividade em artigos (PubMed)", rotulos, f"{prefixo}_a5",
                               "Rótulos escritos pelo modelo. Mostra só quem tem artigo positivo com essas atividades")
    nivel = st.sidebar.select_slider("Evidência mínima nos artigos", options=list(reversed(EVIDENCIAS)),
                                     value="não informado", key=f"{prefixo}_n5",
                                     help="clínico > in vivo > ex vivo > in vitro")
    chave = df[chave_col]
    d = df.copy()
    for c in tudo.columns:
        d[c] = chave.map(tudo[c])
    d["artigos_positivos"] = num(d["artigos_positivos"]).fillna(0).astype(int)
    d["situacao_etapa5"] = [situacao_curta(s, n) for s, n in zip(chave.map(status_etapa5(tipo)),
                                                                  d["artigos_positivos"])]
    m = pd.Series(True, index=df.index)
    if sit:
        m &= d["situacao_etapa5"].isin(sit)
    if ativ or nivel != "não informado":
        sel = resumo_pubmed(tipo, ativ, nivel)
        m &= chave.isin(sel.index)
    return m, d


COLS_ETAPA5 = {
    "artigos_positivos": st.column_config.NumberColumn("artigos positivos", help="artigos do PubMed em que o "
                                                       "modelo achou relação causal positiva (etapa 5)"),
    "atividades_pubmed": st.column_config.TextColumn("atividades (PubMed)", width="large",
                                                     help="as 5 mais citadas, com o nº de artigos"),
    "melhor_evidencia": st.column_config.TextColumn("melhor evidência"),
    "situacao_etapa5": st.column_config.TextColumn("situação na etapa 5"),
    "atividades_artigos": st.column_config.TextColumn("citada em artigos da descoberta (etapa 2)",
                                                      help="artigos achados na etapa 2, não julgados pelo modelo"),
}


def pagina_plantas():
    st.title("2 · Plantas: lista final e distribuição")
    df = plantas()
    if df is None:
        return nada("`plantas.csv` não encontrado: a etapa 2 ainda não rodou.")
    st.sidebar.header("Filtros")
    txt = st.sidebar.text_input("Nome científico ou popular contém", key="pl_txt")
    fam = multiselect_lateral("Família", opcoes(df["familia"]), "pl_fam")
    fontes = multiselect_lateral("Fonte", ["lista", "gbif", "artigos"], "pl_fonte",
                                 "lista = sua lista · gbif = registro na região · artigos = citada em artigos")
    sit = multiselect_lateral("Situação do nome", opcoes(df["situacao_nome"]), "pl_sit")
    m = (busca(df["nome_cientifico"], txt) | busca(df["nome_popular_pt"], txt))
    if fam:
        m &= df["familia"].isin(fam)
    m &= contem_algum(df["fonte"], fontes)
    if sit:
        m &= df["situacao_nome"].isin(sit)
    m &= filtros_distribuicao("pl", df)
    m5, df = etapa5_na_pagina(df, "nome_cientifico", "planta", "pl")
    f = df[m & m5]
    desc = f["estados_br"].fillna(DESCONHECIDA).eq(DESCONHECIDA)
    pares = [("Plantas", fmt(len(f)), "linhas de plantas.csv que passam nos filtros"),
             ("Famílias", fmt(f["familia"].nunique())),
             ("Com estado conhecido", fmt((~desc).sum()), pct((~desc).sum(), len(f))),
             ("Endêmicas do Brasil", fmt(f["endemismo_br"].eq("endêmica do Brasil").sum())),
             ("Nativas", fmt(contem_algum(f["origem_br"], ["nativa"]).sum()))]
    if "situacao_etapa5" in f:
        pos = f["artigos_positivos"].gt(0).sum()
        pares.append(("Com artigo positivo", fmt(pos), f"{pct(pos, len(f))} · etapa 5 (PubMed)"
                      + (", resultados parciais" if estado_etapa5()["estado"] == "andamento" else "")))
    metricas(pares)

    aba1, aba2, aba3 = st.tabs(["Lista", "Distribuição no Brasil", "Conferência e descartes"])
    with aba1:
        c1, c2 = st.columns(2)
        with c1:
            barras(f.groupby(f["familia"].fillna("(sem família)")).size(), "Famílias com mais plantas", "plantas")
        with c2:
            barras(itens(f["fonte"]).value_counts(), "Fonte", "plantas", top=5)
            barras(f["situacao_nome"].fillna("(vazio)").value_counts(), "Situação do nome", "plantas", top=10)
        cols = [c for c in ["nome_cientifico", "nome_popular_pt", "familia", "situacao_nome", "fonte",
                            "artigos_positivos", "atividades_pubmed", "melhor_evidencia", "situacao_etapa5",
                            "n_ocorrencias_na_area", "estados_br", "dominios_br", "endemismo_br", "origem_br",
                            "fonte_distribuicao", "nome_aceito", "nomes_juntados", "atividades_artigos"]
                if c in f.columns and (f[c].notna().any() or c == "artigos_positivos")]
        t = f[cols].sort_values("artigos_positivos", ascending=False) if "artigos_positivos" in cols else f[cols]
        tabela(t, "plantas_recorte.csv", COLS_ETAPA5, chave="pl_tab")
    with aba2:
        if not f["estados_br"].notna().any():
            nada("Este `plantas.csv` não tem distribuição por estado (versão anterior à 3.9).")
        else:
            uf = itens(f.loc[~desc, "estados_br"]).value_counts()
            st.caption("Uma planta conta em todos os estados em que ocorre. Estados segundo a Flora e Funga "
                       "do Brasil (e o GBIF, para o que ela não cobre: ver `fonte_distribuicao`).")
            c1, c2 = st.columns(2)
            with c1:
                barras(uf, "Plantas por estado", "plantas", top=27)
            with c2:
                uma = f.loc[~desc & ~f["estados_br"].fillna("").str.contains(";")
                            & f["fonte_distribuicao"].fillna("").str.startswith("Flora"), "estados_br"]
                barras(uma.value_counts(), "Plantas que ocorrem em um só estado (Flora)", "plantas", top=27)
            dom = f["dominios_br"].fillna("").map(lambda v: [d.strip() for d in v.split(";") if d.strip()])
            ocorre = itens(f["dominios_br"]).value_counts()
            so = dom[dom.map(len) == 1].map(lambda l: l[0]).value_counts()
            tab = pd.concat([pd.DataFrame({"domínio": ocorre.index, "série": "ocorre no domínio", "plantas": ocorre.values}),
                             pd.DataFrame({"domínio": so.index, "série": "só nesse domínio", "plantas": so.values})])
            c1, c2 = st.columns(2)
            with c1:
                barras_agrupadas(tab, "domínio", "série", "plantas", "Plantas por domínio", "plantas",
                                 ["ocorre no domínio", "só nesse domínio"])
            with c2:
                ex = f.assign(d=dom).explode("d").dropna(subset=["d"])
                ex = ex[ex["d"].ne("")]
                ex["endemismo"] = ex["endemismo_br"].fillna("sem informação")
                t = ex.groupby(["d", "endemismo"]).size().reset_index(name="plantas")
                ordem = ["endêmica do Brasil", "não endêmica", "sem informação"]
                empilhado_100(t, "d", "endemismo", "plantas", "Endemismo do Brasil em cada domínio",
                              [o for o in ordem if o in set(t["endemismo"])],
                              [c for o, c in zip(ordem, [AZUL, LARANJA, CINZA]) if o in set(t["endemismo"])])
    with aba3:
        conf = ler("plantas_conferencia_taxonomica.csv")
        if conf is not None:
            st.subheader("Conferência dos nomes")
            st.caption("O que cada base taxonômica disse sobre cada nome (`plantas_conferencia_taxonomica.csv`).")
            t = st.text_input("Nome contém", key="pl_conf_txt")
            col_nome = "nome" if "nome" in conf.columns else conf.columns[0]
            tabela(conf[busca(conf[col_nome], t)], "conferencia_recorte.csv", altura=300, chave="pl_conf")
        desc_ = ler("plantas_descartados.csv")
        if desc_ is not None:
            st.subheader("Nomes descartados")
            st.caption("Nomes do GBIF e dos artigos que não entraram na lista (não são plantas, ou só gênero).")
            if "motivo" in desc_:
                barras(desc_["motivo"].fillna("").str.split(":").str[0].value_counts(), "Motivo", "nomes", cor=CINZA)
            tabela(desc_, "descartados.csv", altura=300, chave="pl_desc")
        if conf is None and desc_ is None:
            nada("Sem `plantas_conferencia_taxonomica.csv` nem `plantas_descartados.csv`.")


def filtros_compostos(df: pd.DataFrame, prefixo: str) -> pd.Series:
    st.sidebar.header("Filtros")
    txt = st.sidebar.text_input("Nome do composto ou InChIKey contém", key=f"{prefixo}_txt")
    m = busca(df["nome"], txt) | busca(df["inchikey"], txt)
    planta_txt = st.sidebar.text_input("Ocorre na planta (nome contém)", key=f"{prefixo}_planta",
                                       help="Ex.: Euterpe oleracea, ou só o gênero")
    if planta_txt:
        pc = planta_composto()
        if pc is not None:
            iks = set(pc.loc[busca(pc["nome_cientifico"], planta_txt), "inchikey"])
            m &= df["inchikey"].isin(iks)
    fam = st.sidebar.text_input("Ocorre na família (contém)", key=f"{prefixo}_fam")
    if fam:
        pc = planta_composto()
        if pc is not None:
            m &= df["inchikey"].isin(set(pc.loc[busca(pc["familia"], fam), "inchikey"]))
    bases = multiselect_lateral("Base de origem", opcoes(df["bases"]), f"{prefixo}_base")
    m &= contem_algum(df["bases"], bases)
    vias = multiselect_lateral("Via biossintética (NPClassifier)", opcoes(df["via"].str.replace("|", "; ", regex=False)),
                               f"{prefixo}_via")
    m &= contem_algum(df["via"].str.replace("|", "; ", regex=False), vias)
    sup = multiselect_lateral("Superclasse (ClassyFire)", opcoes(df["superclasse"]), f"{prefixo}_sup")
    if sup:
        m &= df["superclasse"].isin(sup)
    if "conferencia_smiles" in df.columns and df["conferencia_smiles"].notna().any():
        div = multiselect_lateral("Conferência dos SMILES", opcoes(df["conferencia_smiles"]),
                                  f"{prefixo}_div")
        if div:
            m &= df["conferencia_smiles"].isin(div)
        st.sidebar.caption("Para conferir discrepância à mão, escolha *estruturas diferentes* "
                           "ou *InChIKey não corresponde ao SMILES*: são os casos em que as "
                           "bases discordam da estrutura.")
    nmin = st.sidebar.number_input("Presente em ao menos N plantas", 1, 1000, 1, key=f"{prefixo}_np")
    m &= df["n_plantas_"].fillna(0).ge(nmin)
    if df["qed_"].notna().any():
        q = st.sidebar.slider("QED (semelhança com fármaco)", 0.0, 1.0, (0.0, 1.0), 0.05, key=f"{prefixo}_qed")
        if q != (0.0, 1.0):
            m &= df["qed_"].between(*q)
    if df["massa"].notna().any():
        mm = st.sidebar.slider("Massa molecular (g/mol)", 0, 2000, (0, 2000), 50, key=f"{prefixo}_mm",
                               help="Uso tópico: costuma-se preferir < 500 Da")
        if mm != (0, 2000):
            m &= df["massa"].between(*mm)
    if "lipinski_ok" in df and df["lipinski_ok"].notna().any():
        if st.sidebar.checkbox("Só regra de Lipinski ok (≤ 1 violação)", key=f"{prefixo}_lip"):
            m &= df["lipinski_ok"].astype(str).str.lower().eq("true")
        if st.sidebar.checkbox("Sem alertas PAINS", key=f"{prefixo}_pains",
                               help="PAINS: subestruturas que costumam dar falso positivo em ensaios"):
            m &= vazio(df["alertas_pains"])
    return m


def pagina_compostos():
    st.title("3 · Compostos das plantas")
    df = compostos()
    if df is None:
        return nada("Sem `especies_com_compostos_bioativos.csv` nem `banco/compostos.csv`: "
                    "a etapa 3 ainda não rodou.")
    aviso_escopo()
    st.caption("Fonte: " + ("banco relacional (`banco/compostos.csv`, `perfil_admet.csv`): compostos "
                            "deduplicados por InChIKey canônico." if tem_banco() else
                            "etapa bioativos (`especies_com_compostos_bioativos.csv`). "
                            + ("ClassyFire, massa e o perfil ADMET entram quando a etapa 5 terminar e as "
                               "etapas 6 e 7 rodarem." if estado_etapa5()["estado"] == "andamento" else
                               "Rode as etapas 6 e 7 para ter ClassyFire, massa e o perfil ADMET.")))
    m = filtros_compostos(df, "co")
    m5, df = etapa5_na_pagina(df, "inchikey", "composto", "co")
    f = df[m & m5]
    pares = [("Compostos", fmt(len(f))),
             ("Com PubChem CID", fmt(f["pubchem_cid"].notna().sum()), pct(f["pubchem_cid"].notna().sum(), len(f)))]
    if f["qed_"].notna().any():
        pares.append(("QED ≥ 0,5", fmt((f["qed_"] >= 0.5).sum()), "propriedades próximas de fármacos orais"))
    if "lipinski_ok" in f:
        pares.append(("Lipinski ok", fmt(f["lipinski_ok"].astype(str).str.lower().eq("true").sum())))
        pares.append(("Com alerta PAINS", fmt((~vazio(f["alertas_pains"])).sum())))
    if "conferencia_smiles" in f.columns and f["conferencia_smiles"].notna().any():
        n_div = f["conferencia_smiles"].isin(VEREDITOS_PARA_CONFERIR).sum()
        pares.append(("A conferir (SMILES)", fmt(n_div),
                      "estrutura divergente entre as bases: conferir à mão"))
    if "situacao_etapa5" in f:
        pos = f["artigos_positivos"].gt(0).sum()
        pares.append(("Com artigo positivo", fmt(pos), f"{pct(pos, len(f))} · etapa 5 (PubMed)"
                      + (", resultados parciais" if estado_etapa5()["estado"] == "andamento" else "")))
    metricas(pares)
    aba1, aba2, aba3 = st.tabs(["Classes químicas", "Espaço químico", "Tabela"])
    with aba1:
        c1, c2 = st.columns(2)
        with c1:
            barras(itens(f["via"].fillna("sem classificação").str.replace("|", "; ", regex=False)).value_counts(),
                   "Via biossintética (NPClassifier)", "compostos", top=10)
            barras(itens(f["bases"]).value_counts(), "Base de origem", "compostos", top=8, cor=LARANJA)
        with c2:
            barras(f["superclasse"].fillna("sem classificação").value_counts(), "Superclasse (ClassyFire)",
                   "compostos")
    with aba2:
        if f["massa"].notna().any() and f["logp"].notna().any():
            x, y, tx, ty = "massa", "logp", "massa molecular (g/mol)", "logP"
        elif f["np_likeness"].notna().any() and f["qed_"].notna().any():
            x, y, tx, ty = "np_likeness", "qed_", "NP-likeness (mais alto = mais típico de produto natural)", "QED"
        else:
            x = None
        if x is None:
            nada("Sem propriedades físico-químicas para desenhar o espaço químico.")
        else:
            d = f.dropna(subset=[x, y])
            amostra = d.sample(min(len(d), 5000), random_state=1) if len(d) > 5000 else d
            amostra = amostra.assign(via_=amostra["via"].fillna("sem classificação").str.split("|").str[0])
            vias = amostra["via_"].value_counts().index.tolist()
            principais = vias[:7]
            amostra["via_"] = amostra["via_"].where(amostra["via_"].isin(principais), "outras")
            dom = principais + (["outras"] if "outras" in set(amostra["via_"]) else [])
            cores = [CINZA if v in ("sem classificação", "outras") else c
                     for v, c in zip(dom, SERIE + [CINZA] * 3)]
            graf = alt.Chart(amostra).mark_circle(size=28, opacity=0.65).encode(
                x=alt.X(f"{x}:Q", title=tx), y=alt.Y(f"{y}:Q", title=ty),
                color=alt.Color("via_:N", title="via", scale=alt.Scale(domain=dom, range=cores),
                                legend=alt.Legend(orient="bottom")),
                tooltip=["nome:N", "inchikey:N", alt.Tooltip(f"{x}:Q", format=".2f"),
                         alt.Tooltip(f"{y}:Q", format=".2f"), "via_:N"])
            regras = []
            if x == "massa":
                regras = [alt.Chart(pd.DataFrame({"v": [500]})).mark_rule(strokeDash=[4, 3], color="#52514e").encode(x="v:Q"),
                          alt.Chart(pd.DataFrame({"v": [5]})).mark_rule(strokeDash=[4, 3], color="#52514e").encode(y="v:Q")]
            st.altair_chart(alt.layer(graf, *regras).properties(height=480, title="Espaço químico"
                            + (f" (amostra de {fmt(len(amostra))} de {fmt(len(d))})" if len(d) > len(amostra) else "")),
                            width="stretch")
            if x == "massa":
                st.caption("Linhas tracejadas: massa 500 g/mol e logP 5 (limites da regra de Lipinski). "
                           "Para uso tópico, a janela de permeação na pele fica em massa < 500 e logP entre ~1 e 4.")
            else:
                st.caption("QED: semelhança com fármaco oral (0 a 1). NP-likeness: semelhança com produto natural.")
    with aba3:
        cols = [c for c in ["nome", "inchikey", "pubchem_cid", "artigos_positivos", "atividades_pubmed",
                            "melhor_evidencia", "situacao_etapa5", "formula_molecular", "massa", "logp", "tpsa_", "qed_",
                            "np_likeness", "lipinski_ok", "alertas_pains", "superclasse", "classyfire_class", "via",
                            "np_classifier_superclass", "bases", "n_plantas_", "n_bioatividades", "n_conflitos",
                            "estados_composto", "smiles_isomerico", "conferencia_smiles"]
                if c in f.columns and (c in ("nome", "inchikey", "pubchem_cid", "n_plantas_", "artigos_positivos")
                                       or f[c].notna().any())]
        t = f[cols].rename(columns={"tpsa_": "tpsa", "qed_": "qed", "n_plantas_": "n_plantas",
                                    "smiles_isomerico": "smiles",
                                    "conferencia_smiles": "conferência dos SMILES"})
        t = t.sort_values(["artigos_positivos", "n_plantas"] if "artigos_positivos" in t else ["n_plantas"],
                          ascending=False)
        t.insert(2, "PubChem", t["pubchem_cid"].map(link_pubchem))
        tabela(t, "compostos_recorte.csv", {**COLS_ETAPA5,
            "PubChem": st.column_config.LinkColumn("PubChem", display_text="abrir"),
            "massa": st.column_config.NumberColumn(format="%.1f"), "logp": st.column_config.NumberColumn(format="%.2f"),
            "tpsa": st.column_config.NumberColumn(format="%.1f"), "qed": st.column_config.NumberColumn(format="%.2f"),
            "np_likeness": st.column_config.NumberColumn(format="%.2f"),
            "smiles": st.column_config.TextColumn("smiles", width="medium")}, chave="co_tab")
        st.caption("A **conferência dos SMILES** compara as estruturas que cada base informa "
                   + ("(da tabela de conflitos do banco, que registra também a severidade e a "
                      "resolução adotada)." if tem_banco() else
                      "(coluna `conferencia_smiles` da etapa bioativos).")
                   + " `sem conflito registrado` não garante que houve comparação: um composto "
                     "com SMILES em uma só base não tem com o que ser comparado. Os SMILES de "
                     "cada fonte, lado a lado, estão na **Ficha** do composto.")


def pagina_chembl():
    st.title("4 · ChEMBL: atividades medidas em ensaios")
    ev = evidencias_chembl()
    sit = ler("compostos_chembl.csv", ["InChIKey", "chembl_id", "correspondencia_chembl", "atividades_chembl"])
    if ev is None and sit is None:
        return nada("`compostos_chembl.csv` não encontrado: a etapa 4 ainda não rodou.")
    if sit is not None:
        v = sit["atividades_chembl"].fillna("")
        rot = pd.Series("com atividade medida", index=sit.index)
        rot[v.str.startswith("composto não encontrado")] = "não encontrado no ChEMBL"
        rot[v.str.startswith("no ChEMBL, sem atividade")] = "no ChEMBL, sem registro ativo"
        rot[v.str.startswith("consulta pendente")] = "consulta pendente"
        rot[v.eq("") | v.str.startswith("sem InChIKey") | v.str.startswith("não consultado")] = "não consultado / sem InChIKey"
        metricas([("Compostos consultados", fmt(len(sit))),
                  ("Encontrados no ChEMBL", fmt(sit["chembl_id"].notna().sum()), pct(sit["chembl_id"].notna().sum(), len(sit))),
                  ("Com atividade medida", fmt((rot == "com atividade medida").sum()))])
    if ev is None or ev.empty:
        return nada("Nenhum registro de ensaio ativo.")
    ev = ev.copy()
    ev["pchembl_"] = num(ev["pchembl"])
    ev["ano_"] = num(ev["ano"])
    st.sidebar.header("Filtros")
    if ev["fonte"].nunique() > 1:
        fon = multiselect_lateral("Fonte", sorted(ev["fonte"].dropna().unique()), "ch_fonte")
        if fon:
            ev = ev[ev["fonte"].isin(fon)]
    at = multiselect_lateral("Atividade", opcoes(ev["atividade"]), "ch_at")
    alvo = st.sidebar.text_input("Alvo contém", key="ch_alvo", help="Ex.: tyrosinase, Staphylococcus")
    org = st.sidebar.text_input("Organismo do alvo contém", key="ch_org")
    tipo = multiselect_lateral("Tipo de ensaio", opcoes(ev["tipo_ensaio"]), "ch_tipo",
                               "B = ligação · F = funcional · A = ADME · T = toxicidade")
    med = multiselect_lateral("Medida", opcoes(ev["medida"]), "ch_med")
    corr = multiselect_lateral("Correspondência", opcoes(ev["correspondencia"]), "ch_corr",
                               "exata = o próprio composto · estereoisômero = mesma conectividade · prevista = similaridade")
    pmin = st.sidebar.slider("pChEMBL mínimo", 4.0, 10.0, 4.0, 0.5, key="ch_pmin",
                             help="6 = 1 µM · 7 = 100 nM. Registros sem pChEMBL saem quando o mínimo passa de 4.")
    m = contem_algum(ev["atividade"], at) & busca(ev["alvo"], alvo) & busca(ev["organismo_alvo"], org)
    if tipo:
        m &= ev["tipo_ensaio"].isin(tipo)
    if med:
        m &= ev["medida"].isin(med)
    if corr:
        m &= ev["correspondencia"].isin(corr)
    if pmin > 4.0:
        m &= ev["pchembl_"].ge(pmin)
    f = ev[m]
    metricas([("Registros", fmt(len(f))), ("Compostos", fmt(f["InChIKey"].nunique())),
              ("Alvos", fmt(f["alvo"].nunique())),
              ("Mediana de pChEMBL", "—" if f["pchembl_"].isna().all() else f"{f['pchembl_'].median():.1f}".replace(".", ","))])
    c1, c2 = st.columns(2)
    with c1:
        barras(f.groupby("atividade")["InChIKey"].nunique(), "Compostos com ensaio ativo, por atividade", "compostos")
        barras(f.groupby(f["alvo"].fillna("?") + " — " + f["organismo_alvo"].fillna("?"))["InChIKey"].nunique(),
               "Alvos com mais compostos", "compostos", top=15)
    with c2:
        p = f.dropna(subset=["pchembl_"])
        if not p.empty:
            h = alt.Chart(p).mark_bar(color=AZUL).encode(
                x=alt.X("pchembl_:Q", bin=alt.Bin(step=0.25), title="pChEMBL (−log10 molar; mais alto = mais potente)"),
                y=alt.Y("count():Q", title="registros"))
            regras = alt.Chart(pd.DataFrame({"v": [5, 6, 7, 8], "r": ["10 µM", "1 µM", "100 nM", "10 nM"]}))
            st.altair_chart(alt.layer(h, regras.mark_rule(strokeDash=[4, 3], color="#52514e").encode(x="v:Q"),
                                      regras.mark_text(align="left", dx=3, dy=-6, color="#52514e", fontSize=10)
                                      .encode(x="v:Q", y=alt.value(8), text="r:N"))
                            .properties(height=300, title="Potência dos registros"), width="stretch")
        barras(f["medida"].fillna("(sem tipo)").value_counts(), "Tipo de medida", "registros", top=10, cor=LARANJA)
    comp = compostos()
    nomes = dict(zip(comp["inchikey"], comp["nome"])) if comp is not None else {}
    cols = [c for c in ["InChIKey", "composto", "fonte", "atividade", "correspondencia", "alvo", "organismo_alvo",
                        "tipo_ensaio", "medida", "relacao", "valor", "unidade", "pchembl_", "ano", "PMID", "DOI",
                        "documento", "descricao_ensaio"] if c in f.columns]
    t = f[cols].rename(columns={"pchembl_": "pchembl"}).sort_values("pchembl", ascending=False)
    if "composto" not in t:
        t.insert(1, "composto", t["InChIKey"].map(nomes))
    t.insert(t.columns.get_loc("PMID") + 1, "artigo", t["PMID"].map(link_pubmed))
    tabela(t, "ensaios_recorte.csv", {"artigo": st.column_config.LinkColumn("artigo", display_text="PubMed"),
                                      "pchembl": st.column_config.NumberColumn(format="%.2f")}, chave="ch_tab")


def pagina_pubmed():
    st.title("5 · PubMed: atividades demonstradas em artigos")
    ev = evidencias_pubmed()
    apl = ler("atividades_plantas.csv")
    aco = ler("atividades_compostos.csv")
    andamento = estado_etapa5()["estado"] == "andamento"
    if ev is None and apl is None:
        if andamento:
            return nada("A etapa 5 está rodando e os primeiros resultados parciais estão sendo "
                        "gerados (veja o quadro na barra lateral). A página se atualiza sozinha.")
        return nada("A etapa 5 ainda não rodou.")
    if andamento:
        t = _mtime(pasta_copia_parcial() / "atividades_plantas_parcial.csv")
        st.info(f"**Resultados parciais** (de {quando(t)}, {ha_quanto(t)}): só o que o modelo já leu. Plantas e "
                "compostos ainda não lidos aparecem como pendentes ou sem artigo.", icon="⏳")
    st.sidebar.header("Filtros")
    ev = ev if ev is not None else pd.DataFrame(columns=["tipo_entidade", "atividades", "nivel", "parte_planta", "ano"])
    ativ = multiselect_lateral("Atividade (rótulo do modelo)", opcoes(ev["atividades"].str.lower()), "pm_at")
    nivel = st.sidebar.select_slider("Evidência mínima", options=list(reversed(EVIDENCIAS)), value="não informado",
                                     key="pm_nivel", help="clínico > in vivo > ex vivo > in vitro")
    sust = st.sidebar.checkbox("Só coleta sustentável (folha, fruto, semente, flor, exsudato, parte aérea)",
                               key="pm_sust")
    anos = num(ev["ano"]).dropna()
    faixa = None
    if len(anos):
        a0, a1 = int(anos.min()), int(anos.max())
        if a0 < a1:
            faixa = st.sidebar.slider("Ano de publicação", a0, a1, (a0, a1), key="pm_ano")
    m = contem_algum(ev["atividades"].str.lower(), ativ) & ev["nivel"].map(NIVEL).le(NIVEL[nivel])
    if sust:
        m &= ev["tipo_entidade"].ne("planta") | contem_algum(ev["parte_planta"], sorted(SUSTENTAVEL))
    if faixa and faixa != (int(anos.min()), int(anos.max())):
        m &= num(ev["ano"]).between(*faixa)
    f = ev[m]
    fp, fc = f[f["tipo_entidade"] == "planta"], f[f["tipo_entidade"] == "composto"]
    metricas([("Artigos positivos", fmt(f["PMID"].nunique())), ("Plantas", fmt(fp["entidade"].nunique())),
              ("Compostos", fmt(fc["InChIKey"].nunique() or fc["entidade"].nunique())),
              ("Estudos in vivo ou clínicos", fmt(f.loc[f["nivel"].isin(["clínico", "in vivo"]), "PMID"].nunique()))])
    aba1, aba2, aba3, aba4, aba5 = st.tabs(["Resumo", "Plantas", "Compostos", "Artigos", "Leitura do modelo"])
    with aba1:
        c1, c2 = st.columns(2)
        with c1:
            a = f.assign(at=f["atividades"].str.lower().str.split(SEP)).explode("at")
            a = a[a["at"].fillna("").str.strip().ne("")]
            t = a.groupby(["at", "tipo_entidade"])["PMID"].nunique().reset_index(name="artigos")
            t["tipo_entidade"] = t["tipo_entidade"].map({"planta": "plantas", "composto": "compostos"})
            top = t.groupby("at")["artigos"].sum().sort_values(ascending=False).head(20).index
            barras_agrupadas(t[t["at"].isin(top)], "at", "tipo_entidade", "artigos", "Atividades demonstradas",
                             "artigos positivos", ["plantas", "compostos"])
        with c2:
            nv = f.drop_duplicates(["tipo_entidade", "entidade", "PMID"])["nivel"].value_counts()
            barras(nv.reindex([e for e in EVIDENCIAS if e in nv.index]),
                   "Tipo de estudo (o mais forte de cada artigo)", "artigos", cores=COR_EVIDENCIA, top=5,
                   ordenar=False)
            pp = itens(fp.drop_duplicates(["entidade", "PMID"])["parte_planta"].fillna("não informado")).value_counts()
            barras(pp, "Parte da planta (artigos sobre plantas)", "artigos",
                   cores={p: (AZUL if p in SUSTENTAVEL else LARANJA if p in DESTRUTIVA else CINZA) for p in pp.index})
            st.caption("Azul: coleta sustentável · laranja: coleta destrutiva · cinza: não informado")
        if num(f["ano"]).notna().any():
            y = f.drop_duplicates(["tipo_entidade", "PMID"]).assign(ano_=num(f["ano"])).dropna(subset=["ano_"])
            y = y.groupby(["ano_", "tipo_entidade"]).size().reset_index(name="artigos")
            st.altair_chart(alt.Chart(y).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("ano_:Q", title="ano", axis=alt.Axis(format="d"), scale=alt.Scale(nice=False, zero=False)),
                y=alt.Y("artigos:Q"),
                color=alt.Color("tipo_entidade:N", title=None, scale=alt.Scale(domain=["planta", "composto"], range=[AZUL, LARANJA]),
                                legend=alt.Legend(orient="bottom")))
                .properties(height=340, title="Artigos positivos por ano"), width="stretch")
    with aba2:
        if fp.empty:
            nada("Nenhum artigo positivo sobre plantas com estes filtros.")
        else:
            g = fp.groupby("entidade").agg(artigos_positivos=("PMID", "nunique"),
                                           melhor_evidencia=("nivel", lambda s: min(s, key=lambda p: NIVEL[p])),
                                           atividades=("atividades", lambda s: "; ".join(sorted(set(itens(s.str.lower()))))),
                                           partes=("parte_planta", lambda s: "; ".join(sorted(set(itens(s)))))).reset_index()
            pl = plantas()
            if pl is not None:
                g = g.merge(pl[["nome_cientifico", "familia", "nome_popular_pt", "estados_br", "dominios_br",
                                "endemismo_br", "origem_br"]].rename(columns={"nome_cientifico": "entidade"}),
                            on="entidade", how="left")
                mdist = filtros_distribuicao("pm", g)
                g = g[mdist]
            g = g.rename(columns={"entidade": "planta"}).sort_values("artigos_positivos", ascending=False)
            barras(g.set_index("planta")["artigos_positivos"], "Plantas com mais artigos positivos", "artigos",
                   cores=None, italico=True)
            tabela(g, "plantas_com_atividade.csv", chave="pm_pl")
    with aba3:
        if fc.empty:
            nada("Nenhum artigo positivo sobre compostos com estes filtros.")
        else:
            g = fc.groupby(fc["InChIKey"].fillna(fc["entidade"])).agg(
                composto=("entidade", "first"), artigos_positivos=("PMID", "nunique"),
                melhor_evidencia=("nivel", lambda s: min(s, key=lambda p: NIVEL[p])),
                atividades=("atividades", lambda s: "; ".join(sorted(set(itens(s.str.lower()))))),
                via_busca=("via_busca", lambda s: "; ".join(sorted(set(itens(s)))))).reset_index(names="InChIKey")
            if aco is not None and "n_plantas" in aco:
                g = g.merge(aco[["InChIKey", "n_plantas", "plantas"]].drop_duplicates("InChIKey"), on="InChIKey", how="left")
            g = g.sort_values("artigos_positivos", ascending=False)
            barras(g.set_index("composto")["artigos_positivos"], "Compostos com mais artigos positivos", "artigos")
            st.caption("Compostos muito estudados em geral (ex.: quercetina) lideram: o artigo trata do composto, "
                       "não necessariamente da sua planta.")
            tabela(g, "compostos_com_atividade.csv", chave="pm_co")
    with aba4:
        t = st.text_input("Título, revista ou justificativa contém", key="pm_txt")
        a = f[busca(f["titulo"], t) | busca(f["revista"], t) | busca(f["justificativa_llm"], t)]
        cols = [c for c in ["tipo_entidade", "entidade", "PMID", "link", "ano", "revista", "titulo", "atividades",
                            "tipo_estudo", "parte_planta", "justificativa_llm", "via_busca", "DOI"] if c in a.columns]
        tabela(a[cols].sort_values(["ano", "PMID"], ascending=False), "artigos_recorte.csv",
               {"link": st.column_config.LinkColumn("artigo", display_text="PubMed"),
                "justificativa_llm": st.column_config.TextColumn("justificativa do modelo", width="large")},
               chave="pm_art")
    with aba5:
        aba_leitura()


GRUPOS_LEITURA = {   # na ordem em que o modelo lê
    "1 plantas com compostos": "plantas com compostos",
    "2 plantas sem compostos citadas na descoberta": "plantas sem compostos citadas na descoberta",
    "2b plantas sem compostos (outras)": "outras plantas sem compostos",
    "3 compostos": "compostos",
}


def duracao(horas: float) -> str:
    if horas < 1:
        return f"~{max(1, round(horas * 60))} min"
    if horas < 48:
        return f"~{horas:.0f} h" if horas >= 10 else f"~{horas:.1f} h".replace(".", ",")
    return f"~{horas / 24:.0f} dias"


@st.fragment(run_every=15)
def quadro_diagnostico():
    """Situação do diagnóstico; refaz a página quando um novo fica pronto."""
    situacao = disparar_diagnostico()
    meta = meta_diagnostico()
    fim = meta.get("fim") if meta else None
    visto = st.session_state.get("_diag_visto")
    st.session_state["_diag_visto"] = fim or 0.0
    if visto is not None and (fim or 0.0) != visto:
        st.rerun(scope="app")
    c1, c2 = st.columns([3, 1])
    if situacao == "sem_script":
        c1.warning("Falta o `diagnostico_leitura.py` na pasta `mods/`.")
        return
    if situacao == "rodando":
        c1.info("Conferindo a lista de artigos com o cache do modelo... (leva alguns minutos, como a "
                "geração dos parciais; a aba se atualiza sozinha)")
    elif situacao == "esperando":
        c1.info("O diagnóstico começa assim que a geração dos parciais terminar (os dois juntos pesam na memória).")
    elif situacao == "falhou":
        c1.error("O último diagnóstico falhou: veja o registro.")
    elif meta:
        c1.caption(f"Diagnóstico de {quando(fim)} ({ha_quanto(fim)}), levou "
                   f"{duracao((meta['fim'] - meta['inicio']) / 3600)}.")
    if c2.button("Refazer o diagnóstico", key="diag_agora", disabled=situacao in ("rodando", "esperando"),
                 width="stretch", help="Monta de novo a lista de artigos da etapa 5 e confere no cache o que "
                                       "o modelo já leu (sem internet e sem ler artigo novo)"):
        disparar_diagnostico(pedir=True)
        st.rerun(scope="fragment")
    log = _dir_diag() / "diagnostico.log"
    if log.exists() and situacao != "rodando" and st.toggle("Mostrar o registro do diagnóstico", key="diag_log"):
        st.code("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]) or "(vazio)")


def aba_leitura():
    """O que o modelo da etapa 5 já leu e o que falta, por grupo, com previsão;
    e as entidades com artigos não lidos (inclusive as que já têm positivo)."""
    st.caption("Confere a lista de artigos que a etapa 5 manda ao modelo com o que já está no cache dele "
               "(`diagnostico_leitura.py`, sem internet). Mostra o que as outras abas não mostram: quanto falta "
               "ler em cada grupo, quando deve terminar e quem ainda tem artigo por ler, **inclusive quem já tem "
               "resultado positivo** (nas planilhas, o positivo esconde a pendência).")
    if meta_diagnostico() is None and disparar_diagnostico() == "pronto":
        disparar_diagnostico(pedir=True)        # primeira vez: roda sozinho
    quadro_diagnostico()
    meta = meta_diagnostico()
    g = ler_diag("grupos.csv")
    if meta is None or g is None:
        return
    for c in ["pares", "lidos", "faltam"]:
        g[c] = num(g[c]).fillna(0).astype(int)
    andamento = estado_etapa5()["estado"] == "andamento"
    cache = pasta_cache() / "cache_llm_classificacao.jsonl"
    agora = _resumos_lidos(str(cache), _mtime(cache))[0] if cache.exists() else meta["julgamentos_no_cache"]
    novos = max(0, agora - meta["julgamentos_no_cache"]) if andamento else 0
    r = (g.groupby("grupo")[["pares", "lidos", "faltam"]].sum()
         .reindex([k for k in GRUPOS_LEITURA if k in set(g["grupo"])]))
    # julgamentos depois do diagnóstico: descontados na ordem de leitura
    resto, falta_agora = novos, []
    for f in r["faltam"]:
        d = min(f, resto)
        falta_agora.append(f - d)
        resto -= d
    r["faltam_agora"] = falta_agora
    total, lidos_ = int(r["pares"].sum()), int(r["pares"].sum() - r["faltam_agora"].sum())
    ritmo = ritmo_por_hora() if andamento else None
    prev = "—"
    if ritmo:
        acum, termina = 0, []
        for f in r["faltam_agora"]:
            acum += f
            termina.append(time.time() + acum / ritmo * 3600 if f else None)
        r["termina"] = termina
        h = r["faltam_agora"].sum() / ritmo
        prev = duracao(h) if h else "terminou"
    metricas([("Lidos", f"{fmt(lidos_)} ({pct(lidos_, total)})",
               f"de {fmt(total)} pares entidade × artigo que a etapa 5 manda ao modelo"
               + (f"; inclui {fmt(novos)} lidos depois do diagnóstico" if novos else "")),
              ("Faltam", fmt(total - lidos_), "estimado agora"),
              ("Ritmo", f"{fmt(round(ritmo))}/h" if ritmo else "—",
               "julgamentos por hora na última hora (medidos com o painel aberto e a etapa 5 rodando)"),
              ("Previsão para terminar", prev, "no ritmo atual, na ordem de leitura")])
    if andamento and not ritmo:
        st.caption("Ritmo e previsão aparecem depois de uns 10 minutos com o painel aberto e o modelo lendo.")
    if not andamento and r["faltam_agora"].sum():
        st.caption("A etapa 5 não está rodando: o que falta só é lido quando ela rodar de novo "
                   "(página **Rodar o pipeline**, a partir de 5 · pubmed; o que já foi lido não é lido de novo).")
    t = pd.DataFrame({"grupo (na ordem de leitura)": [GRUPOS_LEITURA.get(k, k) for k in r.index],
                      "pares": r["pares"].map(fmt).values,
                      "lidos": (r["pares"] - r["faltam_agora"]).map(fmt).values,
                      "faltam": r["faltam_agora"].map(fmt).values,
                      "% lido": [pct(p - f, p) for p, f in zip(r["pares"], r["faltam_agora"])]})
    if "termina" in r:
        t["termina"] = [("já terminou" if f == 0 else f"{quando(x)} ({duracao((x - time.time()) / 3600)})")
                        for f, x in zip(r["faltam_agora"], r["termina"])]
    st.dataframe(limpo(t), hide_index=True, width="stretch",
                 column_config={c: st.column_config.TextColumn(c, width="small")
                                for c in ["pares", "lidos", "faltam", "% lido"]})
    st.subheader("Quem ainda tem artigo por ler")
    p = ler_diag("pendentes.csv")
    if p is None or p.empty:
        return nada("Ninguém: tudo o que a etapa 5 monta já foi lido.")
    for c in ["pares", "faltam", "positivos", "faltam_descoberta"]:
        p[c] = num(p[c]).fillna(0).astype(int)
    p["grupo"] = p["grupo"].map(lambda k: GRUPOS_LEITURA.get(k, k))
    p["situação"] = p["positivos"].map(lambda n: "já tem positivo" if n else "sem positivo ainda")
    c1, c2, c3 = st.columns([2, 1, 1])
    grupos = c1.multiselect("Grupo", [v for v in GRUPOS_LEITURA.values() if v in set(p["grupo"])],
                            key="diag_grupo", placeholder="todos")
    so_pos = c2.toggle("Só as que já têm positivo", key="diag_pos",
                       help="Nas planilhas da etapa 5 elas aparecem com as atividades, sem indicar que falta ler")
    nome = c3.text_input("Nome contém", key="diag_nome")
    if grupos:
        p = p[p["grupo"].isin(grupos)]
    if so_pos:
        p = p[p["positivos"] > 0]
    p = p[busca(p["entidade"], nome)]
    if novos:
        st.caption(f"Lista do diagnóstico de {quando(meta['fim'])}: o modelo leu {fmt(novos)} pares depois "
                   "dele. Refaça o diagnóstico para atualizar.")
    tabela(p.sort_values(["grupo", "faltam"], ascending=[True, False])
           [["grupo", "entidade", "pares", "faltam", "faltam_descoberta", "positivos", "situação"]],
           "pendentes_leitura.csv",
           {"pares": st.column_config.NumberColumn("artigos", help="pares entidade × artigo"),
            "faltam": st.column_config.NumberColumn("por ler"),
            "faltam_descoberta": st.column_config.NumberColumn("por ler (descoberta)",
                                                               help="dos por ler, quantos são artigos da etapa 2"),
            "positivos": st.column_config.NumberColumn("positivos já lidos")}, chave="diag_tab")
    sp = ler_diag("sem_pares.csv")
    if sp is not None and len(sp):
        with st.expander(f"{fmt(len(sp))} planta(s) pesquisada(s) sem nenhum artigo para o modelo"):
            st.caption("Sem artigo com resumo no PubMed, ou com a busca ainda não feita.")
            tabela(sp, "plantas_sem_artigo_para_o_modelo.csv", chave="diag_sp", altura=250)


def pagina_prospeccao():
    st.title("Prospecção: plantas candidatas")
    st.caption("Cruza as etapas: atividade demonstrada na planta (artigos), compostos da planta com atividade "
               "(artigos e ensaios), distribuição e coleta. Nenhuma nota opaca: escolha a ordenação.")
    aviso_escopo()
    pl, pc, ev, ch = plantas(), planta_composto(), evidencias_pubmed(), evidencias_chembl()
    if pl is None:
        return nada("`plantas.csv` não encontrado: a etapa 2 ainda não rodou.")
    if ev is None and ch is None:
        return nada("A prospecção precisa das etapas 4 (ChEMBL) ou 5 (PubMed).")
    ev = ev if ev is not None else pd.DataFrame(columns=["tipo_entidade", "entidade", "InChIKey", "PMID",
                                                         "atividades", "nivel", "parte_planta"])
    ch = ch if ch is not None else pd.DataFrame(columns=["InChIKey", "atividade", "pchembl", "ativo", "correspondencia"])
    st.sidebar.header("Critérios")
    todas = sorted(set(opcoes(ev["atividades"].str.lower())) | set(opcoes(ch["atividade"].str.lower())))
    ativ = multiselect_lateral("Atividades de interesse", todas, "pr_at",
                               "Rótulos do PubMed (escritos pelo modelo) e do ChEMBL (os do input.txt)")
    nivel = st.sidebar.select_slider("Evidência mínima (artigos)", options=list(reversed(EVIDENCIAS)),
                                     value="não informado", key="pr_nivel")
    pmin = st.sidebar.slider("pChEMBL mínimo (ensaios)", 4.0, 10.0, 5.0, 0.5, key="pr_pmin")
    so_exata = st.sidebar.checkbox("Só ensaios do próprio composto (sem estereoisômero/previsto)", True, key="pr_exata")
    sust = st.sidebar.checkbox("Artigos da planta só com coleta sustentável", key="pr_sust")
    exige = st.sidebar.radio("A planta precisa ter", ["artigo positivo OU composto ativo", "artigo positivo",
                                                      "composto ativo", "artigo positivo E composto ativo"],
                             key="pr_exige")

    # plantas com artigo positivo
    e = ev[contem_algum(ev["atividades"].str.lower(), ativ) & ev["nivel"].map(NIVEL).le(NIVEL[nivel])]
    ep = e[e["tipo_entidade"] == "planta"]
    if sust:
        ep = ep[contem_algum(ep["parte_planta"], sorted(SUSTENTAVEL))]
    art = ep.groupby("entidade").agg(artigos_planta=("PMID", "nunique"),
                                     melhor_evidencia=("nivel", lambda s: min(s, key=lambda p: NIVEL[p])),
                                     partes=("parte_planta", lambda s: "; ".join(sorted(set(itens(s)))))) \
        if not ep.empty else pd.DataFrame(columns=["artigos_planta", "melhor_evidencia", "partes"])
    # compostos ativos: artigos e ensaios
    comp_art = set(e.loc[e["tipo_entidade"] == "composto", "InChIKey"].dropna())
    c = ch[contem_algum(ch["atividade"].str.lower(), ativ)].copy()
    c["p"] = num(c["pchembl"])
    c = c[c["p"].ge(pmin) & c["ativo"].astype(str).str.lower().isin(["true", "1"])]
    if so_exata:
        c = c[c["correspondencia"].fillna("exata").str.startswith("exata")]
    melhor_p = c.groupby("InChIKey")["p"].max()
    ativos = comp_art | set(melhor_p.index)
    if pc is not None and ativos:
        pa = pc[pc["inchikey"].isin(ativos)].copy()
        pa["via"] = pa["inchikey"].map(lambda k: ("artigo" if k in comp_art else "")
                                       + (" + ensaio" if k in melhor_p.index else "")).str.strip(" +")
        pa["p"] = pa["inchikey"].map(melhor_p)
        por_planta = pa.groupby("nome_cientifico").agg(
            compostos_ativos=("inchikey", "nunique"),
            compostos_em_artigos=("via", lambda s: int(s.str.contains("artigo").sum())),
            compostos_em_ensaios=("via", lambda s: int(s.str.contains("ensaio").sum())),
            melhor_pchembl=("p", "max"),
            exemplos=("composto", lambda s: "; ".join(sorted(set(s.dropna().astype(str)), key=str.lower)[:6])))
    else:
        por_planta = pd.DataFrame(columns=["compostos_ativos", "compostos_em_artigos", "compostos_em_ensaios",
                                           "melhor_pchembl", "exemplos"])
    n_comp = pc.groupby("nome_cientifico")["inchikey"].nunique() if pc is not None else pd.Series(dtype=int)
    base = pl[["nome_cientifico", "nome_popular_pt", "familia", "estados_br", "dominios_br", "endemismo_br",
               "origem_br"]].drop_duplicates("nome_cientifico").set_index("nome_cientifico")
    t = base.join(art, how="left").join(por_planta, how="left")
    t["compostos_conhecidos"] = n_comp.reindex(t.index).fillna(0).astype(int)
    for col in ["artigos_planta", "compostos_ativos", "compostos_em_artigos", "compostos_em_ensaios"]:
        t[col] = num(t[col]).fillna(0).astype(int)
    tem_art, tem_comp = t["artigos_planta"] > 0, t["compostos_ativos"] > 0
    m = {"artigo positivo OU composto ativo": tem_art | tem_comp, "artigo positivo": tem_art,
         "composto ativo": tem_comp, "artigo positivo E composto ativo": tem_art & tem_comp}[exige]
    # filtros de distribuição: um só conjunto na barra lateral, para as duas abas
    b = base.reset_index()
    na_dist = set(b.loc[filtros_distribuicao("pr", b), "nome_cientifico"])
    t = t[m].reset_index().rename(columns={"nome_cientifico": "planta"})
    t = t[t["planta"].isin(na_dist)]
    aba1, aba2 = st.tabs(["Candidatas", "Sem compostos, com artigos da descoberta"])
    with aba2:
        aba_sem_compostos(pl, n_comp, na_dist)
    with aba1:
        candidatas(t)


def candidatas(t: pd.DataFrame):
    ordem = st.selectbox("Ordenar por", ["artigos positivos da planta", "compostos ativos",
                                         "melhor evidência, depois artigos", "melhor pChEMBL",
                                         "menos compostos conhecidos (química pouco explorada)"], key="pr_ordem")
    t["_nivel"] = t["melhor_evidencia"].map(NIVEL).fillna(9)
    chaves = {"artigos positivos da planta": (["artigos_planta", "compostos_ativos"], [False, False]),
              "compostos ativos": (["compostos_ativos", "artigos_planta"], [False, False]),
              "melhor evidência, depois artigos": (["_nivel", "artigos_planta"], [True, False]),
              "melhor pChEMBL": (["melhor_pchembl", "compostos_ativos"], [False, False]),
              "menos compostos conhecidos (química pouco explorada)": (["compostos_conhecidos", "_nivel"], [True, True])}
    col, asc = chaves[ordem]
    t = t.sort_values(col, ascending=asc, na_position="last").drop(columns="_nivel")
    t = t[[c for c in ["planta", "nome_popular_pt", "familia", "artigos_planta", "melhor_evidencia", "partes",
                       "compostos_ativos", "compostos_em_artigos", "compostos_em_ensaios", "melhor_pchembl",
                       "exemplos", "compostos_conhecidos", "estados_br", "dominios_br", "endemismo_br",
                       "origem_br"] if c in t.columns]]
    metricas([("Plantas candidatas", fmt(len(t))),
              ("Com artigo positivo", fmt((t["artigos_planta"] > 0).sum())),
              ("Com composto ativo", fmt((t["compostos_ativos"] > 0).sum())),
              ("Com os dois", fmt(((t["artigos_planta"] > 0) & (t["compostos_ativos"] > 0)).sum())),
              ("Evidência in vivo ou clínica", fmt(t["melhor_evidencia"].isin(["clínico", "in vivo"]).sum()))])
    if not t.empty:
        d = t[(t["artigos_planta"] > 0) | (t["compostos_ativos"] > 0)].copy()
        d["evidência"] = d["melhor_evidencia"].fillna("só compostos")
        dom = [e for e in EVIDENCIAS if e in set(d["evidência"])] + (["só compostos"] if "só compostos" in set(d["evidência"]) else [])
        graf = alt.Chart(d).mark_circle(size=60, opacity=0.8, stroke="white", strokeWidth=1).encode(
            x=alt.X("compostos_ativos:Q", title="compostos da planta com atividade (artigos ou ensaios)",
                    scale=alt.Scale(type="symlog")),
            y=alt.Y("artigos_planta:Q", title="artigos positivos sobre a planta", scale=alt.Scale(type="symlog")),
            color=alt.Color("evidência:N", scale=alt.Scale(domain=dom, range=[COR_EVIDENCIA.get(x, VERDE) for x in dom]),
                            legend=alt.Legend(orient="bottom", title="melhor evidência na planta")),
            tooltip=["planta:N", "nome_popular_pt:N", "familia:N", "artigos_planta:Q", "compostos_ativos:Q",
                     "melhor_evidencia:N", "exemplos:N"])
        st.altair_chart(graf.properties(height=380, title="Evidência na planta × compostos ativos"), width="stretch")
        st.caption("Eixos em escala logarítmica. Passe o mouse num ponto para ver a planta. No canto de cima à "
                   "direita ficam as plantas com evidência nos dois caminhos.")
    tabela(t, "plantas_candidatas.csv", {
        "melhor_pchembl": st.column_config.NumberColumn("melhor pChEMBL", format="%.1f"),
        "exemplos": st.column_config.TextColumn("compostos ativos (exemplos)", width="large")}, chave="pr_tab")


RE_ATIV_ARTIGOS = re.compile(r"^(.*?)\s*\((\d+)\s+artigos?\)\s*$")


def atividades_da_descoberta(texto) -> list[tuple[str, int]]:
    """'clareadora (3 artigos); antioxidante (1 artigo)' -> [('clareadora', 3), ('antioxidante', 1)]"""
    if not isinstance(texto, str):
        return []
    saida = []
    for parte in re.split(SEP, texto):
        parte = parte.strip()
        if parte:
            r = RE_ATIV_ARTIGOS.match(parte)
            saida.append((r.group(1).strip(), int(r.group(2))) if r else (parte, 0))
    return saida


def link_referencia(ref) -> str | None:
    """'PMID 123' -> PubMed; 'DOI 10.x/y' -> doi.org; 'OpenAlex W123' -> OpenAlex."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    ref = ref.strip()
    m = re.fullmatch(r"(?:PMID\s*)?(\d+)", ref)
    if m:
        return link_pubmed(m.group(1))
    if ref.upper().startswith("DOI "):
        return link_doi(ref[4:])
    m = re.search(r"(W\d+)$", ref)
    return f"https://openalex.org/{m.group(1)}" if m else (ref if ref.startswith("http") else None)


def link_doi(doi) -> str | None:
    if not isinstance(doi, str) or not doi.strip():
        return None
    doi = doi.strip()
    return doi if doi.startswith("http") else f"https://doi.org/{doi}"


def aba_sem_compostos(pl: pd.DataFrame, n_comp: pd.Series, na_dist: set):
    """Plantas sem nenhum composto nas bases da etapa 3 que aparecem em artigos
    da descoberta (etapa 2). Com plantas_pesquisadas = com_compostos, a etapa 5
    não lê os artigos delas: é a química pouco explorada da região."""
    st.caption("Plantas **sem nenhum composto** nas bases químicas da etapa 3, mas citadas em artigos sobre a "
               "região que a etapa 2 achou (coluna `atividades_artigos` e `plantas_artigos_evidencias.csv`). "
               "Os artigos da descoberta **não foram julgados pelo modelo** aqui: indicam o tema, não confirmam a "
               "atividade. Desde a mudança da etapa 5, ela também lê os artigos dessas plantas: o resultado está "
               "na coluna **situação na etapa 5** (e, se for positivo, na aba Candidatas). Valem aqui os filtros "
               "de distribuição da barra lateral; os de atividade, evidência e pChEMBL, não.")
    ev2 = ler("plantas_artigos_evidencias.csv", ["nome_no_artigo", "linha_em_plantas_csv", "nome_aceito",
                                                 "atividades_no_texto", "base", "referencia", "ano", "titulo", "doi"])
    if ev2 is not None:
        # a linha de plantas.csv do nome: linha_em_plantas_csv (3.1+) ou nome_aceito (3)
        ev2["planta"] = ev2["linha_em_plantas_csv"].fillna(ev2["nome_aceito"])
        ev2 = ev2.dropna(subset=["planta"])
    t = pl[["nome_cientifico", "nome_popular_pt", "familia", "fonte", "atividades_artigos", "estados_br",
            "dominios_br", "endemismo_br", "origem_br"]].drop_duplicates("nome_cientifico")
    t = t[~t["nome_cientifico"].isin(n_comp[n_comp > 0].index) & t["nome_cientifico"].isin(na_dist)].copy()
    if ev2 is not None and not ev2.empty:
        refs = ev2.drop_duplicates(["planta", "base", "referencia"])
        t["artigos"] = t["nome_cientifico"].map(refs.groupby("planta").size()).fillna(0).astype(int)
        t["ano_mais_recente"] = t["nome_cientifico"].map(num(refs["ano"]).groupby(refs["planta"]).max())
    else:   # sem o arquivo de evidências: o maior número da coluna atividades_artigos
        t["artigos"] = t["atividades_artigos"].map(
            lambda x: max([n for _, n in atividades_da_descoberta(x)], default=0)).astype(int)
        t["ano_mais_recente"] = None
    t = t[(t["artigos"] > 0) | t["atividades_artigos"].notna()]
    if t.empty:
        return nada("Nenhuma planta sem compostos e com artigos da descoberta (com estes filtros). "
                    "Os artigos da descoberta vêm da etapa 2, com `termos_texto` preenchido.")
    rotulos = sorted({a for x in t["atividades_artigos"] for a, _ in atividades_da_descoberta(x)}, key=str.lower)
    c1, c2 = st.columns([2, 1])
    with c1:
        quer = st.multiselect("Atividade citada nos artigos", rotulos, key="pr2_at", placeholder="todas",
                              help="Rótulos de [termos_pubmed] do input.txt (ou \"atividade biológica (geral)\")")
    with c2:
        fam = st.multiselect("Família", opcoes(t["familia"]), key="pr2_fam", placeholder="todas")
    if quer:
        quer_ = {q.lower() for q in quer}
        t = t[t["atividades_artigos"].map(lambda x: any(a.lower() in quer_ for a, _ in atividades_da_descoberta(x)))]
    if fam:
        t = t[t["familia"].isin(fam)]
    apl = ler("atividades_plantas.csv", ["nome_cientifico", "atividades_relatadas_planta"])
    if apl is not None:
        t["situacao_etapa5"] = t["nome_cientifico"].map(
            apl.drop_duplicates("nome_cientifico").set_index("nome_cientifico")["atividades_relatadas_planta"])
    t = t.rename(columns={"nome_cientifico": "planta", "atividades_artigos": "atividades_citadas"}) \
        .sort_values(["artigos", "planta"], ascending=[False, True])
    metricas([("Plantas", fmt(len(t)), "sem composto conhecido e com artigo da descoberta"),
              ("Famílias", fmt(t["familia"].nunique())),
              ("Artigos (planta × artigo)", fmt(int(t["artigos"].sum()))),
              ("Endêmicas do Brasil", fmt(t["endemismo_br"].eq("endêmica do Brasil").sum()))])
    if t.empty:
        return nada("Nenhuma planta com estes filtros.")
    c1, c2 = st.columns(2)
    with c1:
        barras(t.set_index("planta")["artigos"], "Plantas citadas em mais artigos", "artigos", italico=True)
    with c2:
        barras(t.groupby(t["familia"].fillna("(sem família)")).size(), "Famílias", "plantas")
    cols = [c for c in ["planta", "nome_popular_pt", "familia", "artigos", "ano_mais_recente", "atividades_citadas",
                        "situacao_etapa5", "fonte", "estados_br", "dominios_br", "endemismo_br", "origem_br"]
            if c in t.columns]
    tabela(t[cols], "plantas_sem_compostos_com_artigos.csv",
           {"ano_mais_recente": st.column_config.NumberColumn("ano mais recente", format="%d"),
            "situacao_etapa5": st.column_config.TextColumn("situação na etapa 5")}, chave="pr2_tab")
    if ev2 is None or ev2.empty:
        return st.caption("Sem `plantas_artigos_evidencias.csv`: a lista de artigos de cada planta não está disponível.")
    st.subheader("Artigos de uma planta")
    nome = st.selectbox("Planta", t["planta"].tolist()[:2000], key="pr2_pl")
    a = ev2[ev2["planta"] == nome].drop_duplicates(["base", "referencia"]).copy()
    a["link"] = a["referencia"].map(link_referencia)
    a["doi_link"] = a["doi"].map(link_doi)
    a = a.assign(ano_=num(a["ano"])).sort_values("ano_", ascending=False)
    tabela(a[["ano", "titulo", "nome_no_artigo", "atividades_no_texto", "base", "referencia", "link", "doi_link"]],
           "artigos_da_planta.csv",
           {"titulo": st.column_config.TextColumn("título", width="large"),
            "nome_no_artigo": st.column_config.TextColumn("nome no artigo"),
            "atividades_no_texto": st.column_config.TextColumn("atividades no texto"),
            "link": st.column_config.LinkColumn("artigo", display_text="abrir"),
            "doi_link": st.column_config.LinkColumn("DOI", display_text="DOI")}, altura=300, chave="pr2_art")


def pagina_ficha():
    st.title("Ficha")
    aviso_escopo()
    tipo = st.radio("Ficha de", ["planta", "composto"], horizontal=True, key="fi_tipo")
    if tipo == "planta":
        ficha_planta()
    else:
        ficha_composto()


def ficha_planta():
    pl = plantas()
    if pl is None:
        return nada("`plantas.csv` não encontrado.")
    txt = st.text_input("Nome científico ou popular", key="fi_pl_txt", placeholder="ex.: Euterpe oleracea, açaí")
    cand = pl[busca(pl["nome_cientifico"], txt) | busca(pl["nome_popular_pt"], txt)] if txt else pl.head(0)
    if txt and cand.empty:
        return nada("Nenhuma planta com esse nome.")
    if cand.empty:
        return
    nome = st.selectbox("Planta", cand["nome_cientifico"].tolist()[:500], key="fi_pl")
    r = pl[pl["nome_cientifico"] == nome].iloc[0]
    st.header(f"*{nome}*" + (f" — {r['nome_popular_pt']}" if isinstance(r["nome_popular_pt"], str) else ""))
    info = {"família": r["familia"], "situação do nome": r["situacao_nome"], "nome aceito": r["nome_aceito"],
            "fonte": r["fonte"], "registros na região": r["n_ocorrencias_na_area"], "estados": r["estados_br"],
            "domínios": r["dominios_br"], "endemismo": r["endemismo_br"], "origem": r["origem_br"],
            "distribuição por": r["fonte_distribuicao"], "nomes juntados": r["nomes_juntados"]}
    st.table(pd.DataFrame({"": [k for k, v in info.items() if isinstance(v, str) and v],
                           "valor": [v for v in info.values() if isinstance(v, str) and v]}).set_index(""))
    ev = evidencias_pubmed()
    if ev is not None:
        e = ev[(ev["tipo_entidade"] == "planta") & (ev["entidade"] == nome)]
        st.subheader(f"Artigos positivos sobre a planta ({e['PMID'].nunique()})")
        if not e.empty:
            st.dataframe(limpo(e)[["PMID", "link", "ano", "titulo", "atividades", "tipo_estudo", "parte_planta",
                            "justificativa_llm"]], hide_index=True, width="stretch",
                         column_config={"link": st.column_config.LinkColumn("artigo", display_text="PubMed")})
    pc = planta_composto()
    if pc is not None:
        cp = pc[pc["nome_cientifico"] == nome]
        st.subheader(f"Compostos ({cp['inchikey'].nunique()})")
        if not cp.empty:
            comp = compostos()
            t = cp.merge(comp[[c for c in ["inchikey", "via", "superclasse", "qed_", "massa", "pubchem_cid"] if c in comp]],
                         on="inchikey", how="left") if comp is not None else cp
            if ev is not None:
                ec = ev[ev["tipo_entidade"] == "composto"]
                n_art = ec.groupby("InChIKey")["PMID"].nunique()
                ats = ec.groupby("InChIKey")["atividades"].agg(lambda s: "; ".join(sorted(set(itens(s.str.lower())))))
                t["artigos_positivos"] = t["inchikey"].map(n_art).fillna(0).astype(int)
                t["atividades_artigos"] = t["inchikey"].map(ats)
            ch = evidencias_chembl()
            if ch is not None:
                p = num(ch["pchembl"])
                t["melhor_pchembl"] = t["inchikey"].map(ch.assign(p=p).groupby("InChIKey")["p"].max())
                t["atividades_ensaios"] = t["inchikey"].map(ch.groupby("InChIKey")["atividade"].agg(
                    lambda s: "; ".join(sorted(set(s.dropna())))))
            t = t.rename(columns={"qed_": "qed"})
            if "pubchem_cid" in t:
                t["PubChem"] = t["pubchem_cid"].map(link_pubchem)
            ordem = [c for c in ["composto", "inchikey", "PubChem", "artigos_positivos", "atividades_artigos",
                                 "melhor_pchembl", "atividades_ensaios", "via", "superclasse", "qed", "massa",
                                 "bases", "parte_planta", "teor", "referencias"] if c in t.columns]
            sort = "artigos_positivos" if "artigos_positivos" in t else "composto"
            tabela(t[ordem].sort_values(sort, ascending=False), f"compostos_{nome.replace(' ', '_')}.csv",
                   {"PubChem": st.column_config.LinkColumn("PubChem", display_text="abrir"),
                    "qed": st.column_config.NumberColumn(format="%.2f"),
                    "massa": st.column_config.NumberColumn(format="%.1f"),
                    "melhor_pchembl": st.column_config.NumberColumn(format="%.1f")}, altura=360, chave="fi_pl_comp")


def smiles_por_fonte(ik: str, r) -> None:
    """Os SMILES que cada base informa para o composto, lado a lado - é a
    visão que serve para conferir discrepância à mão. Do banco vem a tabela de
    fontes (uma linha por registro de base, com o InChIKey declarado e o
    método que decidiu); sem banco, vêm as quatro colunas por fonte da etapa
    bioativos."""
    veredito = r.get("conferencia_smiles")
    linhas = None
    if tem_banco():
        fo = ler("banco/fontes.csv", ["inchikey", "base", "nome_na_base", "smiles_na_base",
                                      "smiles_valido", "inchikey_declarado",
                                      "metodo_identificacao"])
        if fo is not None and not fo.empty:
            d = fo[fo["inchikey"] == ik]
            if not d.empty:
                linhas = (d[["base", "nome_na_base", "smiles_na_base", "smiles_valido",
                             "inchikey_declarado", "metodo_identificacao"]]
                          .rename(columns={"base": "fonte", "nome_na_base": "nome na base",
                                           "smiles_na_base": "smiles",
                                           "smiles_valido": "SMILES interpretável",
                                           "inchikey_declarado": "InChIKey declarado",
                                           "metodo_identificacao": "método"})
                          .drop_duplicates())
    if linhas is None:
        bio = ler("especies_com_compostos_bioativos.csv",
                  ["composto_inchikey"] + COLUNAS_SMILES_FONTE)
        if bio is None:
            return
        d = bio[bio["composto_inchikey"].fillna("").str.strip().str.upper() == ik]
        if d.empty:
            return
        p = d.iloc[0]
        linhas = pd.DataFrame(
            [{"fonte": f.replace("smiles_", "").upper(), "smiles": p.get(f)}
             for f in COLUNAS_SMILES_FONTE if f != "conferencia_smiles"])
        linhas = linhas[linhas["smiles"].notna()]
        veredito = veredito or p.get("conferencia_smiles")
    if linhas is None or linhas.empty:
        return
    with st.expander(f"SMILES por fonte ({len(linhas)})"
                     + (f" — {veredito}" if isinstance(veredito, str) and veredito else ""),
                     expanded=isinstance(veredito, str)
                     and veredito.startswith("estruturas diferentes")):
        st.dataframe(linhas, hide_index=True, width="stretch")
        st.caption("Compare as estruturas: grafias diferentes podem ser a mesma molécula. "
                   "A conferência estrutural é feita pelo pipeline com o RDKit; aqui está o "
                   "texto original de cada base, para o olho humano.")


def ficha_composto():
    comp = compostos()
    if comp is None:
        return nada("Sem tabela de compostos (etapa 3 ou banco).")
    txt = st.text_input("Nome, InChIKey ou PubChem CID", key="fi_co_txt", placeholder="ex.: quercetin")
    if not txt:
        return
    cand = comp[busca(comp["nome"], txt) | busca(comp["inchikey"], txt) | comp["pubchem_cid"].fillna("").eq(txt.strip())]
    if cand.empty:
        return nada("Nenhum composto com esse nome ou identificador.")
    cand = cand.sort_values("n_plantas_", ascending=False).head(500)
    rotulos = (cand["nome"].fillna("?") + "  ·  " + cand["inchikey"]).tolist()
    escolha = st.selectbox("Composto", rotulos, key="fi_co")
    ik = escolha.split("  ·  ")[-1]
    r = comp[comp["inchikey"] == ik].iloc[0]
    st.header(str(r["nome"]))
    links = [f"[PubChem]({link_pubchem(r['pubchem_cid'])})" if link_pubchem(r.get("pubchem_cid")) else ""]
    st.markdown(f"`{ik}` " + " ".join(l for l in links if l))
    campos = {"nome IUPAC": r.get("nome_iupac"), "fórmula": r.get("formula_molecular"),
              "massa molecular": r.get("massa"), "logP": r.get("logp"), "TPSA": r.get("tpsa_"), "QED": r.get("qed_"),
              "NP-likeness": r.get("np_likeness"), "violações de Lipinski": r.get("violacoes_lipinski"),
              "absorção GI provável": r.get("absorcao_gi_provavel"), "atravessa BHE (provável)": r.get("permeacao_bhe_provavel"),
              "alertas PAINS": r.get("alertas_pains"), "alertas Brenk": r.get("alertas_brenk"),
              "superclasse (ClassyFire)": r.get("superclasse"), "classe (ClassyFire)": r.get("classyfire_class"),
              "via (NPClassifier)": r.get("via"), "bases": r.get("bases"), "SMILES": r.get("smiles_isomerico")}
    vals = {k: (f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v) for k, v in campos.items()
            if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() not in ("", "nan")}
    st.table(pd.DataFrame({"": list(vals), "valor": [str(v) for v in vals.values()]}).set_index(""))
    st.caption("Massa, logP, TPSA, QED e os filtros (Lipinski, BOILED-Egg, PAINS, Brenk) são previsões por regra "
               "(RDKit), não medidas.")
    smiles_por_fonte(ik, r)
    pc = planta_composto()
    if pc is not None:
        p = pc[pc["inchikey"] == ik]
        pl = plantas()
        if pl is not None:
            p = p.merge(pl[["nome_cientifico", "nome_popular_pt", "estados_br", "dominios_br"]], on="nome_cientifico",
                        how="left")
        st.subheader(f"Plantas em que ocorre ({p['nome_cientifico'].nunique()})")
        st.dataframe(limpo(p.drop(columns=["inchikey", "composto"], errors="ignore")), hide_index=True, width="stretch")
    ch = evidencias_chembl()
    if ch is not None:
        c = ch[ch["InChIKey"] == ik]
        st.subheader(f"Ensaios ({len(c)})")
        if not c.empty:
            c = c.assign(artigo=c["PMID"].map(link_pubmed))
            st.dataframe(limpo(c)[[x for x in ["fonte", "atividade", "correspondencia", "alvo", "organismo_alvo", "tipo_ensaio",
                                        "medida", "relacao", "valor", "unidade", "pchembl", "ano", "artigo"] if x in c]],
                         hide_index=True, width="stretch",
                         column_config={"artigo": st.column_config.LinkColumn("artigo", display_text="PubMed")})
    ev = evidencias_pubmed()
    if ev is not None:
        e = ev[(ev["tipo_entidade"] == "composto") & (ev["InChIKey"] == ik)]
        st.subheader(f"Artigos positivos ({e['PMID'].nunique()})")
        if not e.empty:
            st.dataframe(limpo(e)[["PMID", "link", "ano", "titulo", "atividades", "tipo_estudo", "justificativa_llm"]],
                         hide_index=True, width="stretch",
                         column_config={"link": st.column_config.LinkColumn("artigo", display_text="PubMed")})
    if tem_banco():
        for arq, titulo in [("banco/vias_metabolicas.csv", "Vias metabólicas"), ("banco/dados_espectrais.csv", "Dados espectrais"),
                            ("banco/sinonimos.csv", "Sinônimos"), ("banco/conflitos.csv", "Conflitos entre bases")]:
            d = ler(arq)
            if d is not None and "inchikey" in d:
                d = d[d["inchikey"] == ik]
                if not d.empty:
                    with st.expander(f"{titulo} ({len(d)})"):
                        st.dataframe(limpo(d.drop(columns=["inchikey"])), hide_index=True, width="stretch")


def pagina_banco():
    st.title("6 a 8 · Banco relacional e qualidade")
    est = estado_etapa5()
    if est["estado"] == "andamento":
        return nada("O banco relacional e a análise de qualidade ficam disponíveis quando a etapa 5 "
                    "(pubmed) terminar: as etapas 6 a 8 usam o resultado dela. Enquanto isso, as "
                    "outras páginas mostram os resultados parciais.")
    if not tem_banco():
        return nada("A pasta `banco/` ainda não existe: rode as etapas `normalizacao`, `banco` e `qualidade` "
                    "(`--a-partir-de normalizacao`).")
    t_banco = _mtime(caminho("banco/compostos.csv"))
    if est["t_final"] and t_banco and t_banco < est["t_final"]:
        st.warning("Este banco é de **antes** da última rodada da etapa 5: ainda não inclui as atividades "
                   "novas. Para atualizá-lo: página **Rodar o pipeline**, a partir de 6 · normalizacao.")
    if iks_da_regiao() is not None:
        st.caption("Esta página mostra o **banco inteiro**, como ele está na pasta `banco/` — "
                   "inclusive os compostos de plantas de fora da região. O interruptor "
                   "*Só as plantas da região* vale para as outras páginas.")
    pb = res() / "banco"
    tabelas_ = sorted(p.stem for p in pb.glob("*.csv")
                      if p.stem not in ("dicionario_dados", "data_dictionary"))
    contagem = {t: linhas(f"banco/{t}.csv") for t in tabelas_}
    aba1, aba2, aba3, aba4 = st.tabs(["Tabelas", "Drogabilidade (ADMET)", "Conflitos entre bases", "Qualidade"])
    with aba1:
        barras(pd.Series(contagem), "Linhas por tabela", "linhas", top=20)
        dic = ler("banco/dicionario_dados.csv")
        if dic is None:
            dic = ler("banco/data_dictionary.csv")
        escolha = st.selectbox("Abrir a tabela", tabelas_, key="bd_tab",
                               index=tabelas_.index("compostos") if "compostos" in tabelas_ else 0)
        if dic is not None:
            with st.expander("Dicionário de dados desta tabela"):
                st.dataframe(dic[dic["tabela"] == f"{escolha}.csv"].drop(columns=["tabela"]), hide_index=True,
                             width="stretch")
        d = ler(f"banco/{escolha}.csv", traduzir=False)
        txt = st.text_input("Contém (busca em todas as colunas de texto)", key="bd_txt")
        if txt:
            m = pd.Series(False, index=d.index)
            for c in d.columns:
                m |= busca(d[c], txt)
            d = d[m]
        tabela(d, f"{escolha}_recorte.csv", chave="bd_tabela")
    with aba2:
        ad = ler("banco/perfil_admet.csv")
        if ad is None or ad.empty:
            nada("Sem `perfil_admet.csv` (o RDKit não estava instalado quando a etapa `banco` rodou?).")
        else:
            st.caption("Previsões por regra (RDKit), para triagem: não são medidas.")
            regras = {"Lipinski ok": "lipinski_ok", "Veber ok": "veber_ok", "Ghose ok": "ghose_ok",
                      "Egan ok": "egan_ok", "Muegge ok": "muegge_ok", "absorção GI provável": "absorcao_gi_provavel",
                      "atravessa BHE (provável)": "permeacao_bhe_provavel"}
            ok = pd.Series({r: int(ad[c].astype(str).str.lower().eq("true").sum()) for r, c in regras.items() if c in ad})
            calc = int(ad.get("status_admet", pd.Series("calculado", index=ad.index)).eq("calculado").sum())
            metricas([("Compostos com perfil", fmt(calc)),
                      ("Com alerta PAINS", fmt((~vazio(ad["alertas_pains"])).sum()) if "alertas_pains" in ad else "—"),
                      ("Com alerta Brenk", fmt((~vazio(ad["alertas_brenk"])).sum()) if "alertas_brenk" in ad else "—")])
            c1, c2 = st.columns(2)
            with c1:
                barras(ok, "Compostos que passam em cada filtro", "compostos")
            with c2:
                q = num(ad["qed"]).dropna() if "qed" in ad else pd.Series(dtype=float)
                if not q.empty:
                    st.altair_chart(alt.Chart(pd.DataFrame({"qed": q})).mark_bar(color=AZUL).encode(
                        x=alt.X("qed:Q", bin=alt.Bin(step=0.05), title="QED"), y=alt.Y("count():Q", title="compostos"))
                        .properties(height=300, title="Distribuição do QED"), width="stretch")
            if "alertas_pains" in ad:
                barras(itens(ad["alertas_pains"]).value_counts(), "Alertas PAINS mais comuns", "compostos", top=15,
                       cor=LARANJA)
    with aba3:
        cf = ler("banco/conflitos.csv")
        if cf is None or cf.empty:
            nada("Nenhum conflito registrado.")
        else:
            u = cf.drop_duplicates("id_conflito")
            metricas([("Conflitos", fmt(len(u))), ("Compostos envolvidos", fmt(cf["inchikey"].nunique())),
                      ("Severidade alta", fmt(u["severidade"].eq("alta").sum()))])
            t = u.groupby(["tipo_conflito", "severidade"]).size().reset_index(name="conflitos")
            ordem = [s for s in ["alta", "média", "baixa", "informativa"] if s in set(t["severidade"])]
            cores = {"alta": VERMELHO, "média": AMARELO, "baixa": AZUL, "informativa": CINZA}
            graf = alt.Chart(t).mark_bar().encode(
                y=alt.Y("tipo_conflito:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("sum(conflitos):Q", title="conflitos"),
                color=alt.Color("severidade:N", scale=alt.Scale(domain=ordem, range=[cores[s] for s in ordem]),
                                legend=alt.Legend(orient="bottom")),
                tooltip=["tipo_conflito:N", "severidade:N", "conflitos:Q"])
            st.altair_chart(graf.properties(height=150 + 26 * t["tipo_conflito"].nunique(),
                                            title="Conflitos por tipo e severidade"), width="stretch")
            sev = st.multiselect("Severidade", ordem, key="bd_sev", placeholder="todas")
            tabela(cf[cf["severidade"].isin(sev)] if sev else cf, "conflitos_recorte.csv", chave="bd_cf")
    with aba4:
        pq = pb / "qualidade"
        rel = next((pq / n for n in ("RELATORIO_QUALIDADE.md", "QUALITY_REPORT.md")
                    if (pq / n).exists()), pq / "RELATORIO_QUALIDADE.md")
        if not pq.exists():
            nada("A etapa `qualidade` ainda não rodou.")
        else:
            arqs = sorted(p.name for p in pq.glob("*.csv"))
            if arqs:
                a = st.selectbox("Planilha de qualidade", arqs, key="bd_q")
                tabela(ler(f"banco/qualidade/{a}"), a, altura=320, chave="bd_q_tab")
            if rel.exists():
                with st.expander(f"Relatório de qualidade ({rel.name})", expanded=not arqs):
                    st.markdown(rel.read_text(encoding="utf-8", errors="replace"))


# =============================================================================
# Rodar o pipeline, Ollama, GPU e instalação
# =============================================================================
import json
import urllib.request
from collections import deque

ETAPAS_PIPELINE = [("downloads", "0 · downloads"), ("gbif", "1 · gbif"), ("plantas", "2 · plantas"),
                   ("bioativos", "3 · bioativos"), ("chembl", "4 · chembl"), ("pubmed", "5 · pubmed"),
                   ("normalizacao", "6 · normalizacao"), ("banco", "7 · banco"), ("qualidade", "8 · qualidade")]
ROTULO_ETAPA = dict(ETAPAS_PIPELINE)
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _P():
    import processos
    return processos


def _lancador() -> str:
    return r"mods\rodar.bat" if os.name == "nt" else "mods/rodar.sh"


# ---- rodadas iniciadas pelo painel -------------------------------------------
def _arq_rodada() -> Path:
    return pasta_logs() / "pipeline_atual.json"


def rodada_do_painel() -> dict | None:
    try:
        r = json.loads(_arq_rodada().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    reg = _geradores().setdefault("rodadas", {})       # Popen guardado: evita processo zumbi
    proc = reg.get(r.get("pid"))
    if proc is not None:
        proc.poll()
    r["vivo"] = _P().vivo(r.get("pid"))
    return r


@st.cache_data(ttl=8, show_spinner=False)
def _processos(raiz: str, marca: int) -> list:
    try:
        return _P().processos_do_projeto(Path(raiz))
    except Exception:   # noqa: BLE001
        return []


def processos_agora(fresco: bool = False) -> list:
    if fresco:
        st.session_state["_proc_marca"] = st.session_state.get("_proc_marca", 0) + 1
    return _processos(str(pasta()), st.session_state.get("_proc_marca", 0))


def pipeline_rodando() -> dict | None:
    """A rodada em andamento (do painel ou do terminal), ou None."""
    r = rodada_do_painel()
    if r and r["vivo"]:
        return {**r, "origem": "painel"}
    ext = [p for p in processos_agora() if p["tipo"] == "pipeline"]
    if not ext:
        return None
    principal = next((p for p in ext if p["script"] == "main.py"), ext[0])
    return {"pid": principal["pid"], "comando": principal["cmd"], "origem": "terminal", "inicio": None,
            "log": None, "vivo": True}


def iniciar_rodada(script: str, args: list[str], rotulo: str, tipo: str = "pipeline"):
    agora = datetime.datetime.now()
    log = pasta_logs() / f"{'pipeline' if tipo == 'pipeline' else tipo}_{agora:%Y%m%d_%H%M%S}.log"
    proc = _P().iniciar([sys.executable, str(pasta_mods() / script), *args], log, pasta(),
                        {"PIPELINE_CWD": str(pasta())})
    _geradores().setdefault("rodadas", {})[proc.pid] = proc
    _arq_rodada().write_text(json.dumps({"pid": proc.pid, "inicio": time.time(), "comando": rotulo,
                                         "log": str(log), "tipo": tipo}, ensure_ascii=False), encoding="utf-8")
    processos_agora(fresco=True)


def ler_log(caminho: str | None, linhas: int = 60) -> tuple[list[str], str | None]:
    """Últimas linhas (as barras de progresso, que reescrevem a linha com \\r,
    ficam só com o estado mais recente) e a última etapa anunciada."""
    if not caminho or not os.path.exists(caminho):
        return [], None
    tam = os.path.getsize(caminho)
    with open(caminho, "rb") as f:
        f.seek(max(0, tam - 400_000))
        bruto = f.read().decode("utf-8", "replace")
    etapas = re.findall(r"ETAPA \[(\w+)\]", bruto)
    if not etapas and tam > 400_000:
        with open(caminho, "rb") as f:
            etapas = re.findall(r"ETAPA \[(\w+)\]", f.read().decode("utf-8", "replace"))
    saida = []
    for linha in bruto.split("\n"):
        partes = [p for p in linha.split("\r") if p.strip()]
        if partes:
            saida.append(partes[-1].rstrip())
    return saida[-linhas:], (etapas[-1] if etapas else None)


@st.fragment(run_every=3)
def quadro_rodada():
    r = pipeline_rodando()
    if not r:
        ultima = rodada_do_painel()
        if st.session_state.get("_rodando_visto"):
            st.session_state["_rodando_visto"] = False
            st.rerun(scope="app")                     # terminou: volta ao formulário
        if ultima and ultima.get("log"):
            with st.expander(f"Última rodada pelo painel: {ultima['comando']} "
                             f"({quando(ultima.get('inicio'))})", expanded=False):
                linhas, _ = ler_log(ultima["log"], 40)
                st.code("\n".join(linhas) or "(registro vazio)", language=None)
                st.caption(f"Registro completo: `{ultima['log']}`")
        return
    st.session_state["_rodando_visto"] = True
    linhas, etapa = ler_log(r.get("log"))
    etapa_txt = ROTULO_ETAPA.get(etapa, etapa) if etapa else None
    desde = f" desde {quando(r['inicio'])} ({ha_quanto(r['inicio'])})" if r.get("inicio") else ""
    titulo = {"graficos": "Gerando os gráficos", "utilitario": "Rodando"}.get(r.get("tipo"), "Pipeline rodando")
    st.info(f"**{titulo}**{desde}" + (f" · etapa **{etapa_txt}**" if etapa_txt else "")
            + f"  \n`{r['comando'][:160]}`", icon="⚙️")
    pedido = st.session_state.get("_interromper_em")
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("Interromper", type="primary", key="parar", width="stretch",
                 help="O mesmo que Ctrl+C no terminal: a etapa atual para, o que já foi lido fica no "
                      "cache e as etapas seguintes não começam. Depois, rode 'a partir' desta etapa."):
        st.session_state["_interromper_em"] = time.time()
        msg = _P().interromper(r["pid"])
        st.toast(f"Interrompendo ({msg})...")
    if pedido and time.time() - pedido > 30 and os.name != "nt":
        if c2.button("Forçar", key="forcar", width="stretch",
                     help="Ainda não parou depois de 30 s: encerra à força (perde só o item em leitura)"):
            _P().interromper(r["pid"], forcar=True)
    if r["origem"] == "terminal":
        st.caption("Esta rodada foi iniciada pelo terminal: o registro aparece lá."
                   + (" No Windows, Interromper encerra o processo (não há como mandar Ctrl+C a "
                      "outro prompt)." if os.name == "nt" else ""))
    else:
        st.code("\n".join(linhas) or "(começando...)", language=None)
        st.caption(f"Registro completo: `{r['log']}`")


# ---- configuração: o que rodar ----------------------------------------------
def _cfg_input() -> dict:
    """[ollama] modelo e url do config/input.txt (leitura simples, sem importar o pipeline)."""
    cfg = {"modelo": "qwen3.5:35b-a3b", "url": "http://localhost:11434", "paralelo": "4"}
    arq = pasta() / "config" / "input.txt"
    secao = None
    try:
        texto = arq.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return cfg
    for linha in texto.splitlines():
        linha = linha.split("#", 1)[0].strip()
        if linha.startswith("[") and linha.endswith("]"):
            secao = linha[1:-1].strip().lower()
        elif secao == "ollama" and "=" in linha:
            k, v = (x.strip() for x in linha.split("=", 1))
            if k in cfg and v:
                cfg[k] = v
    return cfg


def formulario_rodar():
    try:
        import caminhos as _cm
        antigo = [n for n in os.listdir(pasta()) if n.startswith("cache_") and n.endswith(".jsonl")] \
            or any((pasta() / d).is_dir() for d in _cm.PASTAS_DADOS)
    except OSError:
        antigo = False
    if antigo:
        organizar = r"mods\organizar_pasta.bat" if os.name == "nt" else "mods/organizar_pasta.sh"
        st.warning("A pasta ainda está no formato antigo (caches e planilhas soltos na raiz). Organize-a "
                   f"uma vez antes de rodar: feche o painel e, na pasta do projeto, rode `{organizar}`.")
        return
    modo = st.radio("O que rodar", ["A partir de uma etapa", "Só uma etapa", "Tudo (0 a 8)", "Utilitários"],
                    horizontal=True, key="rd_modo")
    args, etapas = [], []
    ids = [e for e, _ in ETAPAS_PIPELINE]
    if modo in ("A partir de uma etapa", "Só uma etapa"):
        st.session_state.setdefault("rd_etapa", "pubmed")
        etapa = st.selectbox("Etapa", ids, format_func=ROTULO_ETAPA.get, key="rd_etapa")
        args = ["--a-partir-de" if modo.startswith("A partir") else "--somente", etapa]
        etapas = ids[ids.index(etapa):] if modo.startswith("A partir") else [etapa]
    elif modo.startswith("Tudo"):
        etapas = ids
    if modo == "Utilitários":
        util = st.radio("Utilitário", ["Exportar os gráficos (figuras e relatório)", "Conferir o input.txt (config)",
                                       "Resumo da etapa 5 (diagnostico)", "Conferir as credenciais"], key="rd_util")
        uargs = []
        if util.startswith("Exportar"):
            script = "graficos.py"
            c1, c2, c3 = st.columns(3)
            formato = c1.selectbox("Formato", ["png", "svg", "pdf"], key="rd_gfmt",
                                   help="SVG e PDF: vetoriais, bons para artigos (o relatório usa PNG)")
            dpi = c2.selectbox("Resolução (PNG)", [150, 300, 600], key="rd_gdpi")
            top = c3.number_input("Itens nos rankings", 10, 100, 25, step=5, key="rd_gtop")
            uargs = ["--formato", formato, "--dpi", str(dpi), "--top", str(int(top))]
            if estado_etapa5()["estado"] == "andamento":
                uargs.append("--parcial")
            st.caption("Grava em `resultados/graficos/`: um arquivo por gráfico, a tabela de cada um "
                       "(`dados/`) e o `relatorio.html`, que abre sem o painel e pode ser enviado a outras "
                       "pessoas." + (" Com a etapa 5 rodando, usa os resultados parciais." if "--parcial" in uargs
                                     else ""))
            rotulo = (r"mods\graficos.bat " if os.name == "nt" else "mods/graficos.sh ") + " ".join(uargs)
        else:
            script = {"Conferir o": "config_pipeline.py", "Resumo da": "diagnostico_pubmed.py"}.get(
                " ".join(util.split()[:2]), "credenciais.py")
            rotulo = f"{_lancador()} " + {"config_pipeline.py": "config", "diagnostico_pubmed.py": "diagnostico",
                                          "credenciais.py": "credenciais"}[script]
        st.code(rotulo, language=None)
        if st.button("Rodar", type="primary", key="rd_util_ir"):
            iniciar_rodada(script, uargs, rotulo, tipo="graficos" if script == "graficos.py" else "utilitario")
            st.rerun()
        if script == "graficos.py" and (res() / "graficos" / "relatorio.html").exists():
            rel = res() / "graficos" / "relatorio.html"
            st.caption(f"Último relatório: `{rel}` ({quando(rel.stat().st_mtime)})")
        return
    with st.expander("Opções", expanded=False):
        c1, c2 = st.columns(2)
        if c1.checkbox("Retomar: pular etapas cuja saída já existe (--retomar)", key="rd_ret"):
            args.append("--retomar")
        if "downloads" in etapas and c1.checkbox("Pular os downloads (--pular-downloads)", key="rd_pd"):
            args.append("--pular-downloads")
        if c1.checkbox("Atualizar as bases: baixar versões novas (--atualizar-bases)", key="rd_ab"):
            args.append("--atualizar-bases")
        if "gbif" in etapas and c2.checkbox("Sem GBIF: só a lista do input.txt (--sem-gbif)", key="rd_sg"):
            args.append("--sem-gbif")
        if c2.checkbox("Gerar os gráficos ao fim das etapas 2 a 5 (--com-graficos)", key="rd_cgraf",
                       help="Desligado por padrão: o painel já mostra os resultados. Para exportar figuras, "
                            "use Utilitários -> Exportar os gráficos."):
            args.append("--com-graficos")
        chave = c2.text_input("Usar um download do GBIF já feito (--gbif-chave)", key="rd_chave",
                              placeholder="ex.: 0021558-261023074918325") if "gbif" in etapas else ""
        if chave.strip():
            args += ["--gbif-chave", chave.strip()]
    rotulo = f"{_lancador()} {' '.join(args)}".strip()
    st.code(rotulo, language=None)
    # conferências
    problemas = []
    if not (pasta() / "config" / "input.txt").exists():
        problemas.append("Falta o `config/input.txt`.")
    if "gbif" in etapas and "--sem-gbif" not in args and not chave.strip():
        try:
            import credenciais
            credenciais.carregar()
            if not credenciais.gbif_ok():
                st.warning("Credenciais do GBIF vazias (`config/credenciais.txt`). Pelo painel o pipeline não "
                           "tem como perguntar: se a etapa 1 precisar de um download novo, ela para com um "
                           "aviso. Preencha o arquivo antes, ou use um download já feito (Opções).")
        except Exception:   # noqa: BLE001
            pass
    if "pubmed" in etapas and ollama_info()["no_ar"] is False:
        st.warning("O Ollama não está respondendo e a etapa 5 precisa dele. Inicie-o na aba **Ollama e GPU**.")
    for p in problemas:
        st.error(p)
    if st.button("Rodar", type="primary", disabled=bool(problemas), key="rd_ir"):
        confirmar_rodada(args, rotulo)


@st.dialog("Rodar o pipeline")
def confirmar_rodada(args, rotulo):
    st.write("Vai rodar:")
    st.code(rotulo, language=None)
    st.caption("O pipeline roda separado do painel: fechar o painel não o interrompe. O registro fica em "
               "`resultados/logs/`.")
    if st.button("Rodar agora", type="primary"):
        iniciar_rodada("main.py", args, rotulo)
        st.rerun()


# ---- Ollama -------------------------------------------------------------------
def _ollama_api(caminho: str, timeout: float = 2.0) -> dict | None:
    url = _cfg_input()["url"].rstrip("/") + caminho
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def ollama_bin() -> str | None:
    return _P().ollama_bin()


def ollama_info() -> dict:
    versao = _ollama_api("/api/version")
    if versao is None:
        return {"no_ar": False}
    tags = _ollama_api("/api/tags") or {}
    ps = _ollama_api("/api/ps") or {}
    return {"no_ar": True, "versao": versao.get("version"),
            "modelos": [m.get("name") for m in tags.get("models", [])], "carregados": ps.get("models", [])}


def _arq_ollama_pid() -> Path:
    return pasta_logs() / "ollama.pid"


def ollama_do_painel() -> int | None:
    try:
        pid = int(_arq_ollama_pid().read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if _P().vivo(pid) else None


@st.cache_data(ttl=60, show_spinner=False)
def paralelo_ollama_log(caminho: str, _mtime: float) -> dict:
    """Pedidos simultâneos de fato, lidos do começo do ollama.log (o Ollama
    registra a configuração e o carregamento do modelo ao iniciar; o arquivo é
    recriado a cada início): OLLAMA_NUM_PARALLEL, quantas vagas (slots) o
    modelo abriu e se a arquitetura recusou pedidos simultâneos."""
    try:
        with open(caminho, "rb") as f:
            texto = f.read(4_000_000).decode("utf-8", "replace")
    except OSError:
        return {}
    info = {}
    m = re.findall(r"OLLAMA_NUM_PARALLEL:(\d+)", texto)
    if m:
        info["num_parallel"] = int(m[-1])
    m = re.findall(r"n_slots = (\d+)", texto)
    if m:
        info["slots"] = int(m[-1])
    m = re.findall(r"does not currently support parallel requests\"? architecture=(\S+)", texto)
    if m:
        info["recusa"] = m[-1].strip('"')
    return info


def quadro_paralelo(cfg: dict):
    """Uma linha sobre os pedidos simultâneos: o que o input.txt pede e o que o
    Ollama de fato atende."""
    try:
        pedido = max(1, int(cfg.get("paralelo") or 1))
    except ValueError:
        pedido = 1
    log = pasta_logs() / "ollama.log"
    # o ollama.log só descreve o Ollama em execução se foi o painel ou o pipeline
    # que o iniciou (senão - serviço do sistema, bandeja do Windows - é de uma vez anterior)
    info = (paralelo_ollama_log(str(log), log.stat().st_mtime)
            if ollama_do_painel() and log.exists() else {})
    no_servidor = _P().paralelo_do_ollama()
    if no_servidor is None:
        no_servidor = info.get("num_parallel")
    texto = f"Pedidos simultâneos: **{pedido}** no `input.txt` ([ollama] paralelo)"
    if no_servidor is not None:
        texto += f" · Ollama iniciado com OLLAMA_NUM_PARALLEL = **{no_servidor}**"
    if info.get("slots") is not None:
        texto += f" · modelo carregado com **{info['slots']}** vaga(s)"
    st.write(texto)
    if info.get("recusa") and pedido > 1:
        st.warning(f"A arquitetura do modelo (`{info['recusa']}`) não aceita pedidos simultâneos nesta versão do "
                   "Ollama: os resumos são lidos um de cada vez, qualquer que seja o `paralelo`. Isso muda só "
                   "quando uma versão nova do Ollama liberar essa arquitetura (README, seção 17).", icon="⚠️")
    elif no_servidor is not None and no_servidor < pedido:
        st.warning(f"O Ollama em execução aceita só {no_servidor} pedido(s) por vez: os outros esperam na fila. "
                   "Pare o Ollama e inicie de novo por aqui (ele sobe com o valor do `input.txt`).", icon="⚠️")
    elif info.get("slots") is not None and info["slots"] >= pedido > 1:
        st.caption(f"✓ {info['slots']} resumos são lidos ao mesmo tempo.")
    elif no_servidor is None and not info and pedido > 1:
        st.caption("Este Ollama não foi iniciado pelo painel nem pelo pipeline (serviço do sistema ou ícone "
                   "da bandeja do Windows): não dá para conferir daqui se ele aceita pedidos simultâneos. "
                   f"Defina OLLAMA_NUM_PARALLEL = {pedido} nas variáveis de ambiente e reinicie o Ollama "
                   "(README, seção 17), ou pare-o e inicie por aqui.")


def tem_modelo(modelos: list, modelo: str) -> bool:
    return any(m == modelo or m == f"{modelo}:latest" or m.split(":")[0] == modelo for m in modelos or [])


@st.fragment(run_every=5)
def quadro_ollama():
    cfg = _cfg_input()
    info = ollama_info()
    binario = ollama_bin()
    st.markdown("#### Ollama")
    meu = ollama_do_painel()
    if info["no_ar"]:
        tem = tem_modelo(info["modelos"], cfg["modelo"])
        st.success(f"No ar (versão {info.get('versao') or '?'}, {cfg['url']})"
                   + (" · iniciado por este painel" if meu else ""), icon="✅")
        st.write(f"Modelo do `input.txt`: **{cfg['modelo']}** "
                 + ("— baixado ✓" if tem else "— **não baixado**"))
        quadro_paralelo(cfg)
        if info["carregados"]:
            linhas = []
            for m in info["carregados"]:
                tam, vram = m.get("size") or 0, m.get("size_vram") or 0
                gpu = vram / tam if tam else 0
                onde = "100% GPU" if gpu > 0.995 else ("100% CPU" if gpu < 0.005 else
                                                        f"{gpu:.0%} GPU / {1 - gpu:.0%} CPU")
                linhas.append({"modelo": m.get("name"), "tamanho na memória": f"{tam / 1e9:.1f} GB",
                               "onde está": onde})
            st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch")
            if any((m.get("size_vram") or 0) < 0.995 * (m.get("size") or 1) for m in info["carregados"]):
                st.caption("Parte do modelo está na CPU (não coube na memória da placa): a leitura fica mais "
                           "lenta. Feche outros programas que usam a GPU ou use um modelo menor.")
        else:
            st.caption("Nenhum modelo carregado agora (o Ollama carrega na primeira leitura).")
        c1, c2 = st.columns(2)
        if not tem and binario and c1.button(f"Baixar {cfg['modelo']}", key="ol_pull"):
            iniciar_externo([binario, "pull", cfg["modelo"]], "ollama_pull.log")
        if meu and c2.button("Parar o Ollama", key="ol_parar",
                             help="Só o Ollama que este painel iniciou"):
            _P().interromper(meu, forcar=os.name != "nt")
            _arq_ollama_pid().unlink(missing_ok=True)
            st.rerun(scope="fragment")
    else:
        st.error(f"Fora do ar ({cfg['url']}).", icon="⛔")
        if binario:
            if st.button("Iniciar o Ollama (ollama serve)", type="primary", key="ol_ini",
                         help="Continua no ar mesmo se o painel fechar; o registro fica em "
                              "resultados/logs/ollama.log"):
                proc = iniciar_externo([binario, "serve"], "ollama.log",
                                       env_extra=_P().env_ollama(cfg["paralelo"]))
                _arq_ollama_pid().write_text(str(proc.pid))
                time.sleep(2)
                st.rerun(scope="fragment")
            st.caption(f"Inicia com OLLAMA_NUM_PARALLEL = {cfg['paralelo']} ([ollama] paralelo do input.txt), "
                       "a menos que a variável já esteja definida no ambiente em que o painel foi aberto. "
                       "Outras variáveis (OLLAMA_MODELS...) também valem se estiverem nesse ambiente.")
        else:
            st.caption("Ollama não encontrado neste computador. Instale em https://ollama.com/download "
                       + ("(Linux: `curl -fsSL https://ollama.com/install.sh | sh`)." if os.name != "nt" else "."))
    log_pull = pasta_logs() / "ollama_pull.log"
    if log_pull.exists() and time.time() - log_pull.stat().st_mtime < 3600:
        linhas, _ = ler_log(str(log_pull), 3)
        if linhas:
            st.caption("Download do modelo: " + linhas[-1][-200:])


def iniciar_externo(args: list[str], nome_log: str, env_extra: dict | None = None) -> subprocess.Popen:
    proc = _P().iniciar(args, pasta_logs() / nome_log, pasta(), env_extra=env_extra)
    _geradores().setdefault("rodadas", {})[proc.pid] = proc
    return proc


# ---- GPU (nvidia-smi) -------------------------------------------------------
CAMPOS_GPU = ["index", "name", "temperature.gpu", "power.draw", "power.limit", "utilization.gpu",
              "clocks.sm", "memory.used", "memory.total"]


def _num_gpu(v: str):
    try:
        return float(v)
    except ValueError:
        return None


@st.cache_resource
def gpu_amostrador() -> dict:
    """Lê o nvidia-smi a cada 5 s em segundo plano (últimos ~30 min)."""
    est = {"amostras": deque(maxlen=400), "erro": None, "nvsmi": shutil.which("nvidia-smi")}
    if not est["nvsmi"]:
        return est

    def laco():
        while True:
            try:
                r = subprocess.run([est["nvsmi"], f"--query-gpu={','.join(CAMPOS_GPU)}",
                                    "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                   timeout=10, creationflags=SEM_JANELA)
                gpus = []
                for linha in r.stdout.strip().splitlines():
                    v = [x.strip() for x in linha.split(",")]
                    if len(v) == len(CAMPOS_GPU):
                        gpus.append({"gpu": f"{v[0]} · {v[1]}", "temp": _num_gpu(v[2]), "watts": _num_gpu(v[3]),
                                     "limite_w": _num_gpu(v[4]), "uso": _num_gpu(v[5]), "clock": _num_gpu(v[6]),
                                     "mem": _num_gpu(v[7]), "mem_total": _num_gpu(v[8])})
                if gpus:
                    est["amostras"].append((time.time(), gpus))
                    est["erro"] = None
                else:
                    est["erro"] = (r.stderr or r.stdout).strip()[:300] or "sem resposta"
            except (OSError, subprocess.SubprocessError) as e:
                est["erro"] = str(e)
            time.sleep(5)

    threading.Thread(target=laco, daemon=True, name="gpu").start()
    return est


def gpu_agora() -> list | None:
    a = gpu_amostrador()
    if not a["nvsmi"] or not a["amostras"]:
        return None
    t, gpus = a["amostras"][-1]
    return gpus if time.time() - t < 30 else None


@st.fragment(run_every=5)
def quadro_gpu():
    a = gpu_amostrador()
    st.markdown("#### GPU")
    if not a["nvsmi"]:
        st.caption("`nvidia-smi` não encontrado: sem placa NVIDIA (ou sem o driver), não há o que mostrar.")
        return
    gpus = gpu_agora()
    if not gpus:
        st.caption("Lendo a GPU..." if not a["erro"] else f"O nvidia-smi não respondeu: {a['erro']}")
        return
    st.session_state.setdefault("gpu_limite", 83)
    limite = st.session_state["gpu_limite"]
    for g in gpus:
        if len(gpus) > 1:
            st.caption(g["gpu"])
        if g["temp"] is not None and g["temp"] >= limite:
            st.error(f"Temperatura alta: {g['temp']:.0f} °C (limite escolhido: {limite} °C).", icon="🌡️")
        metricas([("Temperatura", f"{g['temp']:.0f} °C" if g["temp"] is not None else "—"),
                  ("Consumo", f"{g['watts']:.0f} W" if g["watts"] is not None else "—",
                   f"limite da placa: {g['limite_w']:.0f} W" if g["limite_w"] else None),
                  ("Uso", f"{g['uso']:.0f}%" if g["uso"] is not None else "—"),
                  ("Clock", f"{g['clock']:.0f} MHz" if g["clock"] is not None else "—"),
                  ("Memória", f"{g["mem"] / 1024:.1f}/{g["mem_total"] / 1024:.0f} GB".replace(".", ",")
                   if g["mem"] is not None and g["mem_total"] else "—", "memória de vídeo usada")])
    linhas = [{"hora": datetime.datetime.fromtimestamp(t), "gpu": g["gpu"], "Temperatura (°C)": g["temp"],
               "Consumo (W)": g["watts"], "Uso (%)": g["uso"]} for t, gs in a["amostras"] for g in gs]
    df = pd.DataFrame(linhas)
    if len(df) >= 3:
        cols = st.columns(3)
        for c, medida in zip(cols, ["Temperatura (°C)", "Consumo (W)", "Uso (%)"]):
            graf = alt.Chart(df).mark_line(strokeWidth=2).encode(
                x=alt.X("hora:T", title=None, axis=alt.Axis(format="%H:%M", labelAngle=0, tickCount=4)),
                y=alt.Y(f"{medida}:Q", title=None, scale=alt.Scale(zero=medida != "Temperatura (°C)")),
                color=alt.Color("gpu:N", legend=None) if df["gpu"].nunique() > 1 else alt.value(AZUL),
                tooltip=[alt.Tooltip("hora:T", format="%H:%M:%S"), alt.Tooltip(f"{medida}:Q", format=".0f")])
            if medida == "Temperatura (°C)":
                graf = graf + alt.Chart(pd.DataFrame({"y": [limite]})).mark_rule(
                    strokeDash=[4, 4], color=CINZA).encode(y="y:Q")
            c.altair_chart(graf.properties(title=medida, height=170), width="stretch")
        st.caption("Últimos ~30 minutos (desde que o painel abriu), uma leitura a cada 5 s.")


def linha_gpu_lateral() -> str | None:
    gpus = gpu_agora()
    if not gpus:
        return None
    g = gpus[0]
    quente = g["temp"] is not None and g["temp"] >= st.session_state.get("gpu_limite", 83)
    partes = [f"{g['temp']:.0f} °C" if g["temp"] is not None else None,
              f"{g['uso']:.0f}%" if g["uso"] is not None else None,
              f"{g['watts']:.0f} W" if g["watts"] is not None else None]
    return ("🌡️ " if quente else "") + "GPU " + " · ".join(p for p in partes if p)


@st.fragment(run_every=5)
def quadro_lateral_execucao():
    """Barra lateral: pipeline rodando e GPU."""
    r = pipeline_rodando()
    if r:
        _, etapa = ler_log(r.get("log"), 1)
        st.caption("⚙️ **Pipeline rodando**" + (f": {ROTULO_ETAPA.get(etapa, etapa)}" if etapa else "")
                   + (f" (desde {quando(r['inicio'])})" if r.get("inicio") else ""))
    g = linha_gpu_lateral()
    if g:
        st.caption(g)


# ---- instalação: dependências -------------------------------------------------
PACOTES = [  # (import, pacote pip, obrigatório, para quê)
    ("requests", "requests>=2.28", True, "consultas às bases"),
    ("pandas", "pandas>=1.5", True, "planilhas"),
    ("tqdm", "tqdm>=4.60", True, "barras de progresso"),
    ("truststore", "truststore>=0.9", True, "certificados da rede (proxy institucional)"),
    ("matplotlib", "matplotlib>=3.6", True, "gráficos das etapas"),
    ("streamlit", "streamlit>=1.50", True, "este painel"),
    ("rdkit", "rdkit", False, "recomendado: InChIKey, conflitos de estrutura e perfil ADMET (etapas 6 e 7)"),
]


@st.cache_data(ttl=60, show_spinner="Conferindo a instalação...")
def conferir_instalacao(raiz: str, marca: int) -> dict:
    import importlib.util
    pac = []
    for mod, pip, obrig, para in PACOTES:
        ok = importlib.util.find_spec(mod) is not None
        versao = None
        if ok:
            try:
                from importlib.metadata import version
                versao = version({"rdkit": "rdkit"}.get(mod, mod))
            except Exception:   # noqa: BLE001
                versao = "?"
        pac.append({"pacote": mod, "pip": pip, "obrigatorio": obrig, "para": para, "ok": ok, "versao": versao})
    r = Path(raiz)
    arquivos = {
        "config/input.txt": (r / "config" / "input.txt").exists(),
        "config/credenciais.txt": (r / "config" / "credenciais.txt").exists(),
        "pasta organizada (cache/, dados/, resultados/)": (r / "resultados").is_dir() and (r / "cache").is_dir(),
    }
    return {"python": sys.version.split()[0], "python_ok": sys.version_info >= (3, 10),
            "executavel": sys.executable, "pacotes": pac, "arquivos": arquivos,
            "ollama": ollama_bin(), "nvidia": shutil.which("nvidia-smi")}


def aba_instalacao():
    st.caption("Confere o que o pipeline e o painel precisam neste computador e instala os pacotes do Python "
               "que faltarem (no mesmo Python em que o painel está rodando).")
    marca = st.session_state.get("_inst_marca", 0)
    info = conferir_instalacao(str(pasta()), marca)
    linhas = [{"item": "Python", "situação": "✅" if info["python_ok"] else "❌",
               "detalhe": f"{info['python']} ({info['executavel']})" + ("" if info["python_ok"] else
                                                                      " - precisa de 3.10 ou mais recente")}]
    for p in info["pacotes"]:
        linhas.append({"item": p["pacote"], "situação": "✅" if p["ok"] else ("❌" if p["obrigatorio"] else "⚠️"),
                       "detalhe": (f"versão {p['versao']}" if p["ok"] else "falta") + f" · {p['para']}"})
    cfg = _cfg_input()
    info_ol = ollama_info()
    linhas.append({"item": "Ollama", "situação": "✅" if info["ollama"] else "❌",
                   "detalhe": (info["ollama"] or "não instalado (etapa 5)")
                   + (" · no ar" if info_ol["no_ar"] else " · fora do ar (inicie na aba Ollama e GPU)")})
    if info_ol["no_ar"]:
        tem = tem_modelo(info_ol["modelos"], cfg["modelo"])
        linhas.append({"item": f"modelo {cfg['modelo']}", "situação": "✅" if tem else "❌",
                       "detalhe": "baixado" if tem else "não baixado (botão na aba Ollama e GPU)"})
    linhas.append({"item": "nvidia-smi", "situação": "✅" if info["nvidia"] else "⚠️",
                   "detalhe": info["nvidia"] or "não encontrado (sem placa NVIDIA, o Ollama usa a CPU)"})
    for nome, ok in info["arquivos"].items():
        linhas.append({"item": nome, "situação": "✅" if ok else "❌", "detalhe": "" if ok else "falta"})
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch", height=35 * len(linhas) + 40,
                 column_config={"situação": st.column_config.TextColumn("", width="small"),
                                "detalhe": st.column_config.TextColumn(width="large")})
    faltam = [p["pip"] for p in info["pacotes"] if not p["ok"]]
    c1, c2 = st.columns([1, 3])
    rodando = (_geradores().get("pip") or {}).get("proc")
    rodando = rodando if rodando is not None and rodando.poll() is None else None
    if faltam:
        if c1.button(f"Instalar o que falta ({len(faltam)})", type="primary", disabled=rodando is not None,
                     key="inst_ir"):
            dentro_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
            conda = (Path(sys.prefix) / "conda-meta").is_dir()
            extra = [] if (dentro_venv or conda) else ["--user"]
            proc = iniciar_externo([sys.executable, "-m", "pip", "install", "--upgrade", *extra, *faltam],
                                   "instalacao.log")
            _geradores()["pip"] = {"proc": proc}
            st.rerun()
        c2.caption("Usa o `pip` deste Python. Precisa de internet. Se a instalação do RDKit falhar, o resto "
                   "do pipeline funciona sem ele.")
    else:
        c1.success("Pacotes do Python: tudo instalado.")
    if c1.button("Conferir de novo", key="inst_ref"):
        st.session_state["_inst_marca"] = marca + 1
        st.rerun()
    log = pasta_logs() / "instalacao.log"
    if log.exists() and (rodando or time.time() - log.stat().st_mtime < 3600):
        if rodando:
            st.info("Instalando... (a lista acima se atualiza ao terminar; clique em **Conferir de novo**)")
        linhas_log, _ = ler_log(str(log), 25)
        st.code("\n".join(linhas_log) or "(começando...)", language=None)
    if not info["ollama"]:
        st.caption("O Ollama não se instala pelo pip: baixe em https://ollama.com/download"
                   + (" ou rode `curl -fsSL https://ollama.com/install.sh | sh`" if os.name != "nt" else "")
                   + ". Depois, baixe o modelo pela aba **Ollama e GPU**.")


# ---- a página -------------------------------------------------------------------
def pagina_rodar():
    st.title("Rodar o pipeline")
    st.caption("Roda as etapas sem terminal, mostra o registro e interrompe; liga o Ollama e acompanha a GPU. "
               "O pipeline roda separado do painel: fechar o painel não o interrompe.")
    aba1, aba2, aba3 = st.tabs(["Rodar", "Ollama e GPU", "Instalação"])
    with aba1:
        quadro_rodada()
        if not pipeline_rodando():
            formulario_rodar()
    with aba2:
        quadro_ollama()
        st.divider()
        quadro_gpu()
        st.number_input("Avisar quando a temperatura passar de (°C)", 60, 100, step=1, key="gpu_limite",
                        width=320)
    with aba3:
        aba_instalacao()


def fechar_painel():
    """Encerra o servidor do painel (o pipeline e o Ollama, se estiverem rodando, continuam)."""
    try:
        (pasta_logs() / "painel.porta").unlink(missing_ok=True)
    except OSError:
        pass
    threading.Timer(1.0, lambda: os._exit(0)).start()


# =============================================================================
def main():
    st.session_state.setdefault("pasta", str(PASTA_PADRAO))
    paginas = [
        st.Page(pagina_inicio, title="Início", icon="🏠", default=True, url_path="inicio"),
        st.Page(pagina_rodar, title="Rodar o pipeline", icon="▶️", url_path="rodar"),
        st.Page(pagina_gbif, title="1 · GBIF", icon="🗺️", url_path="gbif"),
        st.Page(pagina_plantas, title="2 · Plantas", icon="🌿", url_path="plantas"),
        st.Page(pagina_compostos, title="3 · Compostos", icon="⚗️", url_path="compostos"),
        st.Page(pagina_chembl, title="4 · ChEMBL", icon="🧪", url_path="chembl"),
        st.Page(pagina_pubmed, title="5 · PubMed", icon="📄", url_path="pubmed"),
        st.Page(pagina_prospeccao, title="Prospecção", icon="🎯", url_path="prospeccao"),
        st.Page(pagina_ficha, title="Ficha", icon="🔎", url_path="ficha"),
        st.Page(pagina_banco, title="6–8 · Banco e qualidade", icon="🗄️", url_path="banco"),
    ]
    nav = st.navigation(paginas)
    with st.sidebar:
        with st.expander("Configurações", expanded=False):
            st.text_input("Pasta do projeto", key="pasta",
                          help="A pasta com config/, mods/ e resultados/. Padrão: a pasta acima de mods/.")
            st.session_state.setdefault("intervalo_parcial", 10)
            st.select_slider("Etapa 5 em andamento: atualizar os parciais a cada (min)",
                             options=[2, 5, 10, 20, 30, 60], key="intervalo_parcial",
                             help="Com a etapa 5 rodando, o painel gera sozinho os resultados parciais "
                                  "(o mesmo que 'mods/rodar.sh parcial'), no máximo neste intervalo e só "
                                  "quando o modelo leu algo novo.")
            st.session_state.setdefault("so_regiao", True)
            st.toggle("Só as plantas da região", key="so_regiao",
                      help="Com [bioativos] escopo = completo, as bases químicas entram inteiras. "
                           "Ligado (padrão), o painel mostra só as plantas da sua região; a página "
                           "do Banco mostra o banco inteiro de qualquer modo.")
            if st.button("Recarregar os dados"):
                st.cache_data.clear()
                st.rerun()
            if st.button("Fechar o painel", help="Encerra o painel (o servidor no seu computador). O pipeline e "
                                                 "o Ollama, se estiverem rodando, continuam. Para abrir de novo: "
                                                 "o ícone Painel do pipeline."):
                fechar_painel()
                st.success("Painel fechado. Pode fechar esta aba do navegador.")
                st.stop()
        if not (res() / "plantas.csv").exists() and not (res() / "especies_gbif.csv").exists():
            st.warning("Nenhuma planilha do pipeline nesta pasta. Confira a pasta em **Configurações**.")
        if ESQ is None:
            st.warning("Não encontrei `mods/esquema_banco.py`: o `painel.py` precisa ficar na "
                       "pasta `mods/` do pipeline. Sem ele, a pasta `banco/` gravada em inglês "
                       "não é reconhecida.")
        quadro_lateral_execucao()
        quadro_etapa5()
    nav.run()


main()
