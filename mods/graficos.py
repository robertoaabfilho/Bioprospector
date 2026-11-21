#!/usr/bin/env python3
"""
graficos.py - gráficos dos resultados de cada etapa do pipeline

Lê as planilhas que o pipeline já gravou (nada é consultado na internet e
nenhum arquivo do pipeline é alterado) e grava, na pasta graficos/:

  graficos/relatorio.html     todos os gráficos numa página, etapa por etapa,
                              com os números-chave e a explicação de cada um
  graficos/*.png              um arquivo por gráfico (numerado pela etapa)
  graficos/dados/*.csv        a tabela por trás de cada gráfico

Uso (na pasta do projeto, a mesma do rodar.sh):
  mods/graficos.sh                      todos os gráficos possíveis
  mods/graficos.sh --parcial            etapa 5 a partir dos *_parcial.csv
  mods/graficos.sh --etapas plantas,pubmed
  mods/graficos.sh --top 40 --formato svg
  (Windows: graficos.bat, com as mesmas opções)

Etapas sem arquivo de saída são puladas com aviso: pode rodar a qualquer
momento, inclusive com o pipeline ainda em andamento.

Requer pandas (já instalado pelo pipeline) e matplotlib (o graficos.sh /
graficos.bat instala no .venv na primeira vez).
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import zlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos as _C  # noqa: E402

PASTA = _C.RESULTADOS                            # planilhas do pipeline (resultados/)
NO_WINDOWS = os.name == "nt"
RODAR = r"mods\rodar.bat" if NO_WINDOWS else "mods/rodar.sh"            # comandos mostrados nas mensagens
GRAFICOS = r"mods\graficos.bat" if NO_WINDOWS else "mods/graficos.sh"
INSTALAR = r"mods\instalar.bat" if NO_WINDOWS else "mods/instalar.sh"

try:
    import pandas as pd
except ImportError:
    sys.exit(f"ERRO: pandas não encontrado. Rode {INSTALAR} primeiro.")
try:
    import matplotlib
    matplotlib.use("Agg")                          # sem janela: só grava arquivos
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
except ImportError:
    sys.exit(f"ERRO: matplotlib não encontrado. Use {GRAFICOS} ou rode {INSTALAR} de novo,\n"
             "ou instale à mão:  .venv/bin/python -m pip install matplotlib")

# =============================================================================
# Aparência
# =============================================================================
# Paleta categórica validada para daltonismo (ordem fixa: a cor segue a
# categoria, nunca a posição no ranking).
SERIE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
AZUL = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
        "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
CINZA = "#b9b8b2"                   # "outros", "sem informação", "pendente"
CRITICO = "#d03b3b"                 # só para FALHOU (sempre com o rótulo escrito)
FUNDO = "#fcfcfb"
TEXTO, TEXTO2, TEXTO3 = "#0b0b0b", "#52514e", "#8a8984"
GRADE = "#e6e5e1"
CMAP_AZUL = LinearSegmentedColormap.from_list("azul", ["#f3f7fd"] + AZUL[1:])

# evidência: da mais forte (escura) à mais fraca (clara) - escala ordinal de um só tom
EVIDENCIAS = ["clínico", "in vivo", "ex vivo", "in vitro", "não informado"]
COR_EVIDENCIA = {"clínico": "#0d366b", "in vivo": "#1c5cab", "ex vivo": "#3987e5",
                 "in vitro": "#86b6ef", "não informado": CINZA}

# partes da planta (rótulos do pipeline) agrupadas pelo impacto da coleta
COLETA = {"folha": "sustentável", "fruto": "sustentável", "semente": "sustentável",
          "flor": "sustentável", "exsudato (látex/resina)": "sustentável",
          "parte aérea": "sustentável",
          "raiz": "destrutiva", "casca": "destrutiva", "caule": "destrutiva",
          "rizoma": "destrutiva", "tubérculo/bulbo": "destrutiva", "planta inteira": "destrutiva"}
COR_COLETA = {"sustentável": SERIE[0], "destrutiva": SERIE[1], "indefinida": CINZA}

plt.rcParams.update({
    "figure.facecolor": FUNDO, "axes.facecolor": FUNDO, "savefig.facecolor": FUNDO,
    "font.size": 9.5, "font.family": "DejaVu Sans",
    "axes.edgecolor": GRADE, "axes.labelcolor": TEXTO2, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlecolor": TEXTO, "axes.titlelocation": "left",
    "axes.titlepad": 12, "xtick.color": TEXTO2, "ytick.color": TEXTO2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": False, "grid.color": GRADE, "grid.linewidth": 0.8,
    "legend.frameon": False, "legend.fontsize": 9, "legend.labelcolor": TEXTO2,
})

ETAPAS = ["geral", "downloads", "gbif", "plantas", "bioativos", "chembl", "pubmed"]
TITULO_ETAPA = {
    "geral": "Visão geral: do levantamento às evidências",
    "downloads": "Etapa 0 · downloads: bases baixadas",
    "gbif": "Etapa 1 · gbif: plantas com registro na região",
    "plantas": "Etapa 2 · plantas: lista final e conferência dos nomes",
    "bioativos": "Etapa 3 · bioativos: compostos de cada planta",
    "chembl": "Etapa 4 · chembl: atividades medidas em ensaios",
    "pubmed": "Etapa 5 · pubmed: atividades demonstradas em artigos",
}
NUMERO_ETAPA = {"geral": "00", "downloads": "0", "gbif": "1", "plantas": "2",
                "bioativos": "3", "chembl": "4", "pubmed": "5"}

ARQUIVOS_ETAPA5 = ["atividades_plantas.csv", "atividades_compostos.csv",
                   "especies_atividades.csv", "evidencias_pubmed.csv"]
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


# =============================================================================
# Utilidades
# =============================================================================
def fmt(n) -> str:
    """12345 -> '12.345' (separador de milhar brasileiro)."""
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


def cortar(texto, n=48) -> str:
    texto = str(texto)
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def vazio(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "None")


def partes(serie: pd.Series, sep=r"\s*;\s*") -> pd.Series:
    """Explode valores 'a; b; c' em uma linha por item (sem vazios)."""
    s = serie.dropna().astype(str).str.split(sep, regex=True).explode().str.strip()
    return s[s.ne("") & s.ne("nan")]


def numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


def chave_composto(df: pd.DataFrame) -> pd.Series:
    """InChIKey válido; sem ele, o identificador da base (mesma regra do pipeline)."""
    ik = df["composto_inchikey"].astype(str).str.strip().str.upper()
    valido = ik.str.match(RE_INCHIKEY)
    return ik.where(valido, "ID:" + df.get("composto_id", pd.Series(index=df.index)).astype(str))


class Leitor:
    """Lê os CSVs do pipeline só com as colunas necessárias (arquivos grandes)."""

    def __init__(self, parcial: bool):
        self.parcial = parcial
        self.usados = {}

    def caminho(self, nome: str) -> Path | None:
        if self.parcial and nome in ARQUIVOS_ETAPA5:
            p = PASTA / nome.replace(".csv", "_parcial.csv")
            if p.exists():
                return p
        p = PASTA / nome
        return p if p.exists() else None

    def csv(self, nome: str, colunas=None) -> pd.DataFrame | None:
        p = self.caminho(nome)
        if p is None:
            return None
        quero = set(colunas) if colunas else None
        try:
            df = pd.read_csv(p, dtype=str, encoding="utf-8-sig",
                             usecols=(lambda c: c in quero) if quero else None)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        except UnicodeDecodeError:          # planilha regravada no Excel (ANSI)
            df = pd.read_csv(p, dtype=str, encoding="latin-1",
                             usecols=(lambda c: c in quero) if quero else None)
        for c in (colunas or []):
            if c not in df.columns:
                df[c] = None
        self.usados[p.name] = (len(df), datetime.datetime.fromtimestamp(p.stat().st_mtime))
        return df


# =============================================================================
# Relatório: guarda as figuras e monta o HTML
# =============================================================================
class Relatorio:
    def __init__(self, pasta: Path, formato: str, dpi: int):
        self.pasta, self.formato, self.dpi = pasta, formato, dpi
        self.dados = pasta / "dados"
        self.secoes = {e: {"stats": [], "figs": [], "avisos": []} for e in ETAPAS}
        self.contador = Counter()
        pasta.mkdir(parents=True, exist_ok=True)
        self.dados.mkdir(exist_ok=True)

    def stat(self, etapa, rotulo, valor, detalhe=""):
        self.secoes[etapa]["stats"].append((rotulo, valor, detalhe))

    def aviso(self, etapa, texto):
        self.secoes[etapa]["avisos"].append(texto)
        print(f"  [{etapa}] {texto}")

    def salvar(self, etapa, fig, slug, titulo, descricao, tabela: pd.DataFrame | None = None):
        self.contador[etapa] += 1
        letra = chr(ord("a") + self.contador[etapa] - 1)
        base = f"{NUMERO_ETAPA[etapa]}{letra}_{etapa}_{slug}"
        arquivo = self.pasta / f"{base}.{self.formato}"
        fig.savefig(arquivo, dpi=self.dpi, bbox_inches="tight", pad_inches=0.25)
        if self.formato != "png":   # o relatório HTML usa sempre um PNG leve
            fig.savefig(self.pasta / f"{base}.png", dpi=110, bbox_inches="tight", pad_inches=0.25)
        plt.close(fig)
        csv = None
        if tabela is not None and not tabela.empty:
            csv = self.dados / f"{base}.csv"
            tabela.to_csv(csv, index=False, encoding="utf-8-sig")
        self.secoes[etapa]["figs"].append({"img": f"{base}.png", "titulo": titulo,
                                           "descricao": descricao,
                                           "csv": f"dados/{csv.name}" if csv else None})
        print(f"  {arquivo.relative_to(PASTA) if arquivo.is_relative_to(PASTA) else arquivo}")

    # ---- seções de execuções anteriores (gráficos gerados etapa a etapa) ----
    def _arquivo_estado(self) -> Path:
        return self.dados / "_relatorio.json"

    def incorporar_anteriores(self, escolhidas, leitor: Leitor):
        """Traz para o relatório as seções das etapas NÃO refeitas nesta execução
        (ex.: o pipeline gera os gráficos de cada etapa ao terminá-la): o
        relatorio.html fica sempre com todas as etapas já desenhadas."""
        try:
            estado = json.loads(self._arquivo_estado().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for e, sec in (estado.get("secoes") or {}).items():
            if e not in self.secoes or e in escolhidas:
                continue
            figs = [f for f in sec.get("figs", []) if (self.pasta / f.get("img", "")).exists()]
            self.secoes[e] = {"stats": [tuple(x) for x in sec.get("stats", [])], "figs": figs,
                              "avisos": list(sec.get("avisos", [])),
                              "parcial": bool(sec.get("parcial"))}
        for nome, (linhas, quando) in (estado.get("usados") or {}).items():
            if nome not in leitor.usados:
                try:
                    leitor.usados[nome] = (linhas, datetime.datetime.fromisoformat(quando))
                except (TypeError, ValueError):
                    pass

    def gravar_estado(self, leitor: Leitor):
        estado = {"secoes": {e: {"stats": [list(x) for x in s["stats"]], "figs": s["figs"],
                                 "avisos": s["avisos"], "parcial": bool(s.get("parcial"))}
                             for e, s in self.secoes.items()},
                  "usados": {n: [l, t.isoformat()] for n, (l, t) in leitor.usados.items()}}
        self._arquivo_estado().write_text(json.dumps(estado, ensure_ascii=False, indent=1),
                                          encoding="utf-8")

    def html(self, leitor: Leitor, parcial: bool):
        parcial = parcial or bool(self.secoes["pubmed"].get("parcial"))
        agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        arquivos = "".join(
            f"<li><code>{html.escape(n)}</code> · {fmt(l)} linhas · gravado em {t:%d/%m/%Y %H:%M}</li>"
            for n, (l, t) in sorted(leitor.usados.items()))
        nav, corpo = [], []
        for e in ETAPAS:
            s = self.secoes[e]
            if not (s["stats"] or s["figs"] or s["avisos"]):
                continue
            nav.append(f'<a href="#{e}">{html.escape(TITULO_ETAPA[e].split(":")[0])}</a>')
            stats = "".join(
                f'<div class="tile"><div class="v">{html.escape(str(v))}</div>'
                f'<div class="r">{html.escape(r)}</div>'
                + (f'<div class="d">{html.escape(d)}</div>' if d else "") + "</div>"
                for r, v, d in s["stats"])
            avisos = "".join(f'<p class="aviso">{html.escape(a)}</p>' for a in s["avisos"])
            figs = "".join(
                f'<figure><h3>{html.escape(f["titulo"])}</h3>'
                f'<p class="desc">{html.escape(f["descricao"])}</p>'
                f'<a href="{f["img"]}" target="_blank"><img src="{f["img"]}" '
                f'alt="{html.escape(f["titulo"])}" loading="lazy"></a>'
                + (f'<p class="dl"><a href="{f["csv"]}">tabela do gráfico (CSV)</a> · '
                   f'<a href="{f["img"]}" target="_blank">imagem em tamanho real</a></p>'
                   if f["csv"] else "")
                + "</figure>" for f in s["figs"])
            corpo.append(f'<section id="{e}"><h2>{html.escape(TITULO_ETAPA[e])}</h2>'
                         f'{avisos}<div class="tiles">{stats}</div>{figs}</section>')
        aviso_parcial = ('<p class="aviso">Modo <b>parcial</b>: a etapa 5 foi lida dos arquivos '
                         '<code>*_parcial.csv</code> (só o que o modelo já leu).</p>') if parcial else ""
        pagina = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gráficos do pipeline</title>
<style>
:root {{ color-scheme: light; --fundo:{FUNDO}; --sup:{FUNDO}; --t1:{TEXTO}; --t2:{TEXTO2};
        --t3:{TEXTO3}; --linha:{GRADE}; --acento:{SERIE[0]}; --aviso:#fff6e0; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--fundo); color:var(--t1);
       font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
header, main {{ max-width: 1060px; margin: 0 auto; padding: 0 16px; }}
header {{ padding-top: 28px; }}
h1 {{ font-size: 26px; margin: 0 0 4px; }}
.sub {{ color: var(--t2); margin: 0 0 14px; }}
nav {{ position: sticky; top: 0; z-index: 2; background: var(--fundo);
      border-bottom: 1px solid var(--linha); padding: 10px 16px; overflow-x: auto;
      white-space: nowrap; }}
nav a {{ color: var(--t2); text-decoration: none; margin-right: 18px; font-size: 14px; }}
nav a:hover {{ color: var(--acento); }}
section {{ padding: 26px 0 10px; border-bottom: 1px solid var(--linha); }}
h2 {{ font-size: 20px; margin: 0 0 14px; }}
h3 {{ font-size: 16px; margin: 0 0 4px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
         gap: 10px; margin-bottom: 18px; }}
.tile {{ background: #ffffff; border: 1px solid var(--linha); border-radius: 10px;
        padding: 12px 14px; }}
.tile .v {{ font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }}
.tile .r {{ color: var(--t2); font-size: 13px; }}
.tile .d {{ color: var(--t3); font-size: 12px; margin-top: 2px; }}
figure {{ margin: 0 0 30px; background: var(--sup); border: 1px solid var(--linha);
         border-radius: 12px; padding: 16px; }}
figure img {{ width: 100%; height: auto; display: block; margin-top: 8px; }}
.desc {{ color: var(--t2); margin: 0; font-size: 14px; }}
.dl {{ font-size: 13px; margin: 8px 0 0; }}
.dl a {{ color: var(--acento); }}
.aviso {{ background: var(--aviso); border-radius: 8px; padding: 8px 12px; font-size: 14px; }}
details {{ margin: 18px 0 40px; color: var(--t2); font-size: 14px; }}
code {{ font-size: 13px; }}
</style></head><body>
<header><h1>Gráficos do pipeline de prospecção</h1>
<p class="sub">Gerado em {agora} a partir das planilhas da pasta do projeto.</p>
{aviso_parcial}</header>
<nav>{"".join(nav)}</nav>
<main>{"".join(corpo)}
<details><summary>Arquivos lidos</summary><ul>{arquivos}</ul></details>
</main></body></html>"""
        destino = self.pasta / "relatorio.html"
        destino.write_text(pagina, encoding="utf-8")
        return destino


# =============================================================================
# Tipos de gráfico
# =============================================================================
def _altura(n, por=0.30, minimo=2.0):
    return max(minimo, 1.3 + por * n)


def _abaixo(fig, polegadas=0.55):
    """Distância (fração da altura dos eixos) para pôr a legenda logo abaixo do eixo x."""
    return polegadas / (fig.get_figheight() * 0.77)


def _eixo_log(ax, eixos="xy"):
    f = matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v) if v >= 1 else f"{v:g}".replace(".", ","))
    for e in eixos:
        (ax.xaxis if e == "x" else ax.yaxis).set_major_formatter(f)


def _eixo_valores(ax, eixo="x"):
    e = ax.xaxis if eixo == "x" else ax.yaxis
    e.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))   # contagens: sem "2,5"
    e.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: fmt(v)))
    ax.grid(True, axis=eixo)
    ax.set_axisbelow(True)


def barras_h(rotulos, valores, titulo, xlabel, cores=None, italico=False, legenda=None,
             subtitulo=None, extra=None, log=False):
    """Barras horizontais, a maior em cima, com o valor escrito na ponta."""
    rotulos = [cortar(r) for r in rotulos]
    n = len(rotulos)
    fig, ax = plt.subplots(figsize=(9, _altura(n)))
    y = range(n)[::-1]
    cores = cores or SERIE[0]
    ax.barh(list(y), valores, color=cores, height=0.68, edgecolor=FUNDO, linewidth=1)
    ax.set_yticks(list(y), rotulos, fontstyle="italic" if italico else "normal", color=TEXTO)
    ax.tick_params(axis="y", length=0)
    if log:
        ax.set_xscale("log")
    else:
        _eixo_valores(ax)
    vmax = max(valores) if len(valores) else 0
    for yi, v, txt in zip(y, valores, extra or [None] * n):
        rot = fmt(v) + (f"  {txt}" if txt else "")
        ax.text(v * (1.04 if log else 1) + (0 if log else vmax * 0.01), yi, rot,
                va="center", ha="left", fontsize=8.5, color=TEXTO2)
    if not log:
        ax.set_xlim(0, vmax * 1.16 if vmax else 1)
    ax.set_xlabel(xlabel)
    ax.spines["left"].set_visible(False)
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    if legenda:   # abaixo do eixo x, para nunca cobrir as barras
        ax.legend(handles=legenda, loc="upper center", bbox_to_anchor=(0.5, -_abaixo(fig)),
                  ncol=min(len(legenda), 3))
    return fig


def barras_agrupadas_h(categorias, series: dict, titulo, xlabel, subtitulo=None):
    """Barras horizontais agrupadas (até 3 séries de mesma unidade)."""
    categorias = [cortar(c) for c in categorias]
    n, k = len(categorias), len(series)
    fig, ax = plt.subplots(figsize=(9, _altura(n, por=0.26 + 0.14 * k)))
    alt = 0.8 / k
    vmax = max((max(v) for v in series.values() if len(v)), default=0)
    for i, (nome, vals) in enumerate(series.items()):
        ys = [(n - 1 - j) + (k - 1) * alt / 2 - i * alt for j in range(n)]
        ax.barh(ys, vals, height=alt * 0.92, color=SERIE[i], label=nome,
                edgecolor=FUNDO, linewidth=1)
        for yy, v in zip(ys, vals):
            if v:
                ax.text(v + vmax * 0.01, yy, fmt(v), va="center", fontsize=8, color=TEXTO2)
    ax.set_yticks(range(n)[::-1], categorias, color=TEXTO)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    _eixo_valores(ax)
    ax.set_xlim(0, vmax * 1.15 if vmax else 1)
    ax.set_xlabel(xlabel)
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -_abaixo(fig)), ncol=k)
    return fig


def empilhadas_100(linhas, categorias, matriz, cores, titulo, subtitulo=None):
    """Barras 100% empilhadas: composição de cada linha."""
    fig, ax = plt.subplots(figsize=(9, 1.5 + 0.5 * len(linhas)))
    tot = [sum(r) or 1 for r in matriz]
    esquerda = [0.0] * len(linhas)
    y = list(range(len(linhas)))[::-1]
    for j, cat in enumerate(categorias):
        vals = [100 * matriz[i][j] / tot[i] for i in range(len(linhas))]
        ax.barh(y, vals, left=esquerda, color=cores[j], height=0.5, label=cat,
                edgecolor=FUNDO, linewidth=2)
        for yi, l, v, cnt in zip(y, esquerda, vals, [r[j] for r in matriz]):
            if v >= 7:
                escuro = cores[j] in ("#0d366b", "#1c5cab", SERIE[0], SERIE[5], SERIE[6])
                ax.text(l + v / 2, yi, f"{v:.0f}%", ha="center", va="center", fontsize=8.5,
                        color="white" if escuro else TEXTO)
        esquerda = [a + b for a, b in zip(esquerda, vals)]
    ax.set_yticks(y, linhas, color=TEXTO)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -_abaixo(fig, 0.32)),
              ncol=min(4, len(categorias)))
    return fig


def mapa_calor(df: pd.DataFrame, titulo, rotulo_barra, fmt_cel="{:.0f}", italico_linhas=False,
               subtitulo=None):
    """Matriz linhas x colunas em escala de um só tom (azul claro -> escuro)."""
    nl, nc = df.shape
    fig, ax = plt.subplots(figsize=(max(7.5, 2.8 + 0.62 * nc), max(3.2, 1.6 + 0.34 * nl)))
    im = ax.imshow(df.values, cmap=CMAP_AZUL, aspect="auto", vmin=0)
    ax.set_xticks(range(nc), [cortar(c, 26) for c in df.columns], rotation=40, ha="right")
    ax.set_yticks(range(nl), [cortar(i, 40) for i in df.index],
                  fontstyle="italic" if italico_linhas else "normal", color=TEXTO)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    vmax = df.values.max() if df.size else 0
    for i in range(nl):
        for j in range(nc):
            v = df.values[i, j]
            if v:
                ax.text(j, i, fmt_cel.format(v), ha="center", va="center", fontsize=7.5,
                        color="white" if v > 0.55 * vmax else TEXTO)
    ax.set_xticks([x - 0.5 for x in range(1, nc)], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, nl)], minor=True)
    ax.grid(which="minor", color=FUNDO, linewidth=2)
    ax.tick_params(which="minor", length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label(rotulo_barra, color=TEXTO2)
    cb.outline.set_visible(False)
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    return fig


def linhas_tempo(series: dict, titulo, ylabel, subtitulo=None):
    """Séries anuais (uma linha por série, rótulo direto na ponta)."""
    fig, ax = plt.subplots(figsize=(9, 4))
    for i, (nome, s) in enumerate(series.items()):
        s = s.sort_index()
        ax.plot(s.index, s.values, color=SERIE[i], linewidth=2, label=nome, marker="o",
                markersize=3.5 if len(s) > 25 else 5)
        if len(s) and len(series) > 1:
            ax.annotate(nome, (s.index[-1], s.values[-1]), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=8.5, color=TEXTO2)
    _eixo_valores(ax, "y")
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_ylabel(ylabel)
    ax.set_ylim(bottom=0)
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    if len(series) > 1:
        ax.legend(loc="upper left")
    return fig


def histograma(valores, titulo, xlabel, bins=40, linhas_ref=None, subtitulo=None, log_y=False):
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.hist(valores, bins=bins, color=SERIE[0], edgecolor=FUNDO, linewidth=0.8)
    _eixo_valores(ax, "y")
    if log_y:
        ax.set_yscale("log")
    for x, rot in (linhas_ref or []):
        ax.axvline(x, color=TEXTO2, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(x, 1.0, f" {rot}", transform=ax.get_xaxis_transform(), va="top",
                fontsize=8.5, color=TEXTO2)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("frequência")
    ax.set_title(titulo + ("\n" if subtitulo else ""))
    if subtitulo:
        ax.text(0, 1.02, subtitulo, transform=ax.transAxes, fontsize=9, color=TEXTO2)
    return fig


def boxplot_h(ax, dados, **kw):
    """boxplot horizontal (a opção mudou de nome no matplotlib 3.10)."""
    try:
        return ax.boxplot(dados, orientation="horizontal", **kw)
    except TypeError:
        return ax.boxplot(dados, vert=False, **kw)


def contar(serie: pd.Series, top=None, outros=True) -> pd.DataFrame:
    """value_counts -> DataFrame(rotulo, n), com 'outros' agregados."""
    vc = serie.value_counts()
    if top and len(vc) > top:
        resto = vc.iloc[top:].sum()
        vc = vc.iloc[:top]
        if outros and resto:
            vc = pd.concat([vc, pd.Series({f"outros ({fmt(len(serie.value_counts()) - top)})": resto})])
    return vc.rename_axis("rotulo").reset_index(name="n")


# =============================================================================
# Etapa 0: downloads
# =============================================================================
def tamanho(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return 0


def etapa_downloads(rel: Relatorio, ler: Leitor, top: int):
    arq = _C.DADOS / "bases_baixadas.txt"
    if not arq.exists():
        rel.aviso("downloads", "bases_baixadas.txt não encontrado: a etapa 0 ainda não terminou.")
        return
    linhas = []
    for l in arq.read_text(encoding="utf-8", errors="replace").splitlines():
        p = l.split("\t")
        if len(p) >= 3 and p[0] in ("OK", "FALHOU"):
            caminho = _C.RAIZ / p[2]
            extra = 0
            if p[2].endswith(".zip"):            # pasta extraída ao lado do zip
                for d in (caminho.with_suffix(""), caminho.parent / (caminho.stem + "_extraido"),
                          caminho.parent / (caminho.stem.split("_")[0] + "_extraido")):
                    extra += tamanho(d) if d.is_dir() else 0
            linhas.append({"base": p[1], "status": p[0], "arquivo": p[2],
                           "MB": (tamanho(caminho) + extra) / 1e6})
    if not linhas:
        rel.aviso("downloads", "bases_baixadas.txt sem linhas reconhecíveis.")
        return
    df = pd.DataFrame(linhas).sort_values("MB", ascending=False)
    ok = (df["status"] == "OK").sum()
    rel.stat("downloads", "bases OK", f"{ok} de {len(df)}")
    rel.stat("downloads", "espaço ocupado", f"{df['MB'].sum() / 1000:.1f} GB".replace(".", ","),
             "arquivos das bases (sem caches)")
    data = arq.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    try:
        quando = datetime.datetime.strptime(data.replace("Bases verificadas em ", "").strip(),
                                            "%Y-%m-%d %H:%M").strftime("%d/%m/%Y")
    except ValueError:
        quando = data.replace("Bases verificadas em ", "")
    rel.stat("downloads", "última verificação", quando)
    cores = [SERIE[0] if s == "OK" else CRITICO for s in df["status"]]
    extra = ["" if s == "OK" else "✕ FALHOU" for s in df["status"]]
    fig = barras_h(df["base"].tolist(), df["MB"].round(1).tolist(),
                   "Bases baixadas e espaço em disco", "tamanho em disco (MB)", cores=cores,
                   extra=extra, subtitulo="Barras vermelhas = download que falhou")
    rel.salvar("downloads", fig, "bases", "Bases baixadas e espaço em disco",
               "Uma barra por base local usada nas etapas 2 a 4. Uma base com FALHOU precisa "
               f"ser baixada de novo ({RODAR} --somente downloads) ou à mão.", df)


# =============================================================================
# Etapa 1: gbif
# =============================================================================
def etapa_gbif(rel: Relatorio, ler: Leitor, top: int):
    df = ler.csv("especies_gbif.csv", ["nome_cientifico", "familia", "ordem",
                                        "n_ocorrencias_na_area", "nome_popular_pt"])
    if df is None or df.empty:
        rel.aviso("gbif", "especies_gbif.csv não encontrado ou vazio "
                          "(etapa 1 não rodou ou foi usada a opção --sem-gbif).")
        return
    df["n"] = numero(df["n_ocorrencias_na_area"]).fillna(0)
    total = df["n"].sum()
    singletons = (df["n"] == 1).sum()
    rel.stat("gbif", "espécies na região", fmt(len(df)))
    rel.stat("gbif", "registros de ocorrência", fmt(total))
    rel.stat("gbif", "famílias", fmt(df["familia"].nunique()))
    rel.stat("gbif", "espécies com 1 só registro", fmt(singletons), pct(singletons, len(df)))

    t = df.sort_values("n", ascending=False).head(top)
    extra = [cortar(p, 28) if not vazio(p) else "" for p in t["nome_popular_pt"]]
    fig = barras_h(t["nome_cientifico"].tolist(), t["n"].astype(int).tolist(),
                   f"As {len(t)} espécies mais registradas na região", "registros de ocorrência",
                   italico=True, extra=extra)
    rel.salvar("gbif", fig, "especies_mais_registradas", "Espécies mais registradas",
               "Registros no GBIF dentro da região (com o nome popular, quando há). Muitos "
               "registros indicam planta comum ou muito coletada - inclusive cultivada.",
               t[["nome_cientifico", "nome_popular_pt", "n"]].rename(columns={"n": "registros"}))

    fam = (df.groupby(df["familia"].fillna("(sem família)"))
           .agg(especies=("nome_cientifico", "nunique"), registros=("n", "sum"))
           .sort_values("especies", ascending=False))
    f = fam.head(top)
    fig = barras_h(f.index.tolist(), f["especies"].tolist(),
                   f"As {len(f)} famílias com mais espécies na região", "número de espécies")
    rel.salvar("gbif", fig, "familias", "Famílias com mais espécies",
               "Riqueza de espécies por família botânica no levantamento do GBIF.",
               f.reset_index())

    rank = df["n"].sort_values(ascending=False).reset_index(drop=True)
    rank = rank[rank > 0]
    if len(rank) > 2:
        fig, ax = plt.subplots(figsize=(9, 3.8))
        ax.plot(range(1, len(rank) + 1), rank.values, color=SERIE[0], linewidth=2)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.grid(True, which="major")
        ax.set_axisbelow(True)
        _eixo_log(ax)
        ax.set_xlabel("posição da espécie no ranking (escala log)")
        ax.set_ylabel("registros (escala log)")
        meio = int((rank.cumsum() < total / 2).sum()) + 1
        ax.axvline(meio, color=TEXTO2, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(meio, 1.0, f"  {fmt(meio)} espécie{'s' if meio > 1 else ''} ({pct(meio, len(rank))}) "
                f"{'somam' if meio > 1 else 'soma'} metade dos registros",
                transform=ax.get_xaxis_transform(), va="top", fontsize=8.5, color=TEXTO2)
        ax.set_title("Curva de abundância de registros")
        rel.salvar("gbif", fig, "curva_abundancia", "Curva de abundância de registros",
                   "Cada ponto da linha é uma espécie, da mais para a menos registrada. Uma cauda "
                   "longa indica muitas espécies raras ou pouco amostradas na região.",
                   pd.DataFrame({"posicao": range(1, len(rank) + 1), "registros": rank.values}))


# =============================================================================
# Etapa 2: plantas
# =============================================================================
ORDEM_VEREDITO = ["nome aceito", "sinônimo", "grafia variante", "gênero",
                  "sem status confirmado", "homônimo ambíguo", "não encontrado", "consulta pendente"]
COR_VEREDITO = SERIE[:7] + [CINZA]
# bases taxonômicas em plantas_conferencia_taxonomica.csv (o WCVP entrou na versão 3.1)
BASES_TAXONOMIA = [("veredito_flora", "Flora e Funga do Brasil"), ("veredito_wfo", "World Flora Online"),
                   ("veredito_wcvp", "WCVP (Kew)"), ("veredito_gbif", "GBIF")]
# rótulos longos de situacao_nome (versão 3.1)
ROTULO_SITUACAO = {"não reconhecido nas bases (mantido: está na sua lista)":
                   "não reconhecido, mantido (está na sua lista)"}
# versão 3.3: a linha recebe o nome aceito mesmo quando as fontes só trouxeram sinônimos
ROTULO_SITUACAO_ACEITO = {"aceito (nas fontes só sinônimo ou grafia variante)":
                          "aceito (fontes: só sinônimo/grafia)"}


def classificar_veredito(v) -> str | None:
    if vazio(v):
        return None
    # "<base>: <veredito> (observação)": só o começo do veredito decide, para que
    # uma observação ("homônimo: também consta como sinônimo de...") não confunda
    v = str(v).split(": ", 1)[-1].strip()
    for inicio, rot in [("nome aceito", "nome aceito"), ("sinônimo de", "sinônimo"),
                        ("grafia corrigida", "grafia variante"),      # versão 3
                        ("grafia variante", "grafia variante"),       # versão 3.1
                        ("gênero reconhecido", "gênero"),
                        ("encontrado, sem status", "sem status confirmado"),
                        ("homônimo", "homônimo ambíguo"),
                        ("consulta pendente", "consulta pendente"),
                        ("não encontrado", "não encontrado")]:
        if v.startswith(inicio):
            return rot
    return None


def etapa_plantas(rel: Relatorio, ler: Leitor, top: int):
    df = ler.csv("plantas.csv", ["nome_cientifico", "nome_aceito", "nomes_juntados", "familia",
                                  "categoria_taxonomica",
                                  "n_ocorrencias_na_area", "situacao_nome", "fonte",
                                  "observacoes_taxonomia", "atividades_artigos",
                                  "estados_br", "endemismo_br"])
    if df is None or df.empty:
        rel.aviso("plantas", "plantas.csv não encontrado: a etapa 2 ainda não terminou.")
        return
    sit = df["situacao_nome"].fillna("")
    nao_rec = sit.eq("não reconhecido")
    especie = df["nome_cientifico"].fillna("").str.split().str.len() >= 2
    rel.stat("plantas", "plantas na lista final", fmt(len(df)))
    rel.stat("plantas", "espécies reconhecidas", fmt((especie & ~nao_rec).sum()),
             "usadas nas etapas 3 e 5")
    rel.stat("plantas", "nomes não reconhecidos", fmt(nao_rec.sum()), pct(nao_rec.sum(), len(df)))
    if df["nome_aceito"].notna().any():
        # versão 3.1/3.2: o nome não é trocado; o nome aceito fica em coluna própria.
        # versão 3.3: nome_cientifico já é o nome aceito (difere fica em zero e não aparece)
        aceito = df["nome_aceito"].fillna("").str.strip().str.lower()
        difere = aceito.ne("") & aceito.ne(df["nome_cientifico"].fillna("").str.strip().str.lower())
        if difere.any():
            rel.stat("plantas", "com nome aceito diferente", fmt(difere.sum()),
                     "sinônimo ou grafia variante (nome mantido)")
        juntou = df["nomes_juntados"].fillna("").str.strip().ne("")
        if juntou.any():
            n_nomes = partes(df["nomes_juntados"]).shape[0]
            rel.stat("plantas", "linhas que reúnem vários nomes", fmt(juntou.sum()),
                     f"{fmt(n_nomes)} nomes em nomes_juntados")
    else:
        corrigidos = sit.str.contains("corrigid").sum()
        rel.stat("plantas", "nomes corrigidos", fmt(corrigidos), "sinônimo ou grafia")
    div = df["observacoes_taxonomia"].fillna("").str.contains("DIVERGÊNCIA").sum()
    if div:
        rel.stat("plantas", "divergências entre bases", fmt(div), "ver observacoes_taxonomia")

    c = contar(df["fonte"].fillna("(sem fonte)"))
    c["rotulo"] = c["rotulo"].str.replace("; ", " + ")
    fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "De onde veio cada planta da lista",
                   "número de plantas", subtitulo="gbif = registro na região · lista = sua lista · "
                   "artigos = citada em artigos sobre a região")
    rel.salvar("plantas", fig, "fontes", "Origem das plantas",
               "Quantas plantas vieram de cada fonte ou combinação de fontes. Plantas em mais de uma "
               "fonte (ex.: gbif + artigos) têm ocorrência na região confirmada por dois caminhos.", c)

    c = contar(partes(df["situacao_nome"]))
    cores = [CINZA if r == "não reconhecido" else SERIE[1] if r in ROTULO_SITUACAO else SERIE[0]
             for r in c["rotulo"]]
    rotulos = {**ROTULO_SITUACAO, **ROTULO_SITUACAO_ACEITO}
    c["rotulo"] = c["rotulo"].map(lambda r: rotulos.get(r, r))
    fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Situação dos nomes após a conferência",
                   "número de plantas", cores=cores)
    rel.salvar("plantas", fig, "situacao_nomes", "Situação dos nomes",
               "Resultado da conferência taxonômica (Flora e Funga do Brasil > WFO > WCVP > GBIF; o WCVP "
               "só a partir da versão 3.1). Cinza: 'não reconhecido', fica fora das etapas 3 e 5. Laranja: "
               "nome da sua lista que nenhuma base conhece, mantido e pesquisado normalmente.", c)

    conf = ler.csv("plantas_conferencia_taxonomica.csv", [c for c, _ in BASES_TAXONOMIA])
    if conf is not None and not conf.empty:
        linhas, matriz, tab = [], [], []
        for col, nome in BASES_TAXONOMIA:
            cls = conf[col].map(classificar_veredito).dropna()
            if cls.empty:
                continue
            cnt = cls.value_counts()
            linhas.append(nome)
            matriz.append([int(cnt.get(k, 0)) for k in ORDEM_VEREDITO])
            tab += [{"base": nome, "veredito": k, "n": int(cnt.get(k, 0))} for k in ORDEM_VEREDITO]
        usadas = [j for j in range(len(ORDEM_VEREDITO)) if any(r[j] for r in matriz)]
        if linhas:
            fig = empilhadas_100(linhas, [ORDEM_VEREDITO[j] for j in usadas],
                                 [[r[j] for j in usadas] for r in matriz],
                                 [COR_VEREDITO[j] for j in usadas],
                                 "O que cada base taxonômica disse sobre os nomes",
                                 subtitulo=f"{fmt(len(conf))} nomes conferidos")
            rel.salvar("plantas", fig, "vereditos_bases", "Vereditos das bases taxonômicas",
                       "Para cada base, a proporção de nomes aceitos, sinônimos, grafias variantes, "
                       "homônimos ambíguos e "
                       "não encontrados. Uma base que não encontra muitos nomes indica nomes de fora da "
                       "sua cobertura (ex.: espécies exóticas na Flora do Brasil).", pd.DataFrame(tab))

    ev = ler.csv("plantas_artigos_evidencias.csv",
                 ["nome_aceito", "linha_em_plantas_csv", "base", "referencia", "ano"])
    if ev is not None and not ev.empty:
        # a linha de plantas.csv a que o nome do artigo pertence: "linha_em_plantas_csv"
        # na versão 3.1, "nome_aceito" na versão 3
        ev["nome_aceito"] = (ev["linha_em_plantas_csv"] if ev["linha_em_plantas_csv"].notna().any()
                             else ev["nome_aceito"])
        arts = ev.drop_duplicates(["base", "referencia"]).copy()
        arts["ano"] = numero(arts["ano"])
        arts = arts.dropna(subset=["ano"])
        arts = arts[arts["ano"].between(1900, datetime.date.today().year)]
        rel.stat("plantas", "artigos da descoberta", fmt(ev.drop_duplicates(["base", "referencia"]).shape[0]),
                 " · ".join(f"{b} {fmt(n)}" for b, n in
                            ev.drop_duplicates(["base", "referencia"])["base"].value_counts().items()))
        if not arts.empty:
            series = {b: g.groupby(g["ano"].astype(int)).size()
                      for b, g in arts.groupby("base")}
            fig = linhas_tempo(series, "Artigos sobre a região que citam plantas, por ano",
                               "artigos")
            tab = pd.DataFrame(series).fillna(0).astype(int).rename_axis("ano").reset_index()
            rel.salvar("plantas", fig, "artigos_por_ano", "Artigos da descoberta por ano",
                       "Artigos do PubMed e do OpenAlex que citam a região e ao menos uma planta. "
                       "O último ano costuma estar incompleto.", tab)
        p = (ev.dropna(subset=["nome_aceito"]).drop_duplicates(["nome_aceito", "base", "referencia"])
             .groupby("nome_aceito").size().sort_values(ascending=False).head(top))
        if not p.empty:
            # situação do nome em plantas.csv: os não reconhecidos ficam de fora das etapas 3 e 5
            sit_por_nome = dict(zip(df["nome_cientifico"].fillna("").str.lower(), sit))
            reconhecido = [sit_por_nome.get(str(n).lower(), "") != "não reconhecido" for n in p.index]
            n_nao = reconhecido.count(False)
            leg = [Patch(color=SERIE[0], label="nome reconhecido"),
                   Patch(color=CINZA, label="não reconhecido (fora das etapas 3 e 5)")] if n_nao else None
            fig = barras_h(p.index.tolist(), p.tolist(),
                           f"As {len(p)} plantas mais citadas nos artigos sobre a região",
                           "número de artigos", italico=True, legenda=leg,
                           cores=[SERIE[0] if r else CINZA for r in reconhecido],
                           subtitulo=(f"{n_nao} nome(s) em cinza: nenhuma base taxonômica os reconheceu"
                                      if n_nao else None))
            tab = p.rename_axis("planta").reset_index(name="artigos")
            tab["situacao_nome"] = [sit_por_nome.get(str(n).lower(), "") for n in p.index]
            rel.salvar("plantas", fig, "plantas_mais_citadas", "Plantas mais citadas nos artigos",
                       "Quantos artigos sobre a região citam cada planta (qualquer tema). Em cinza, nomes "
                       "que nenhuma base taxonômica reconheceu (palavras, animais, microrganismos): não "
                       "são usados nas etapas 3 e 5. Citação não prova ocorrência na região: compare com "
                       "o GBIF.", tab)

    descartados(rel, ler, top)

    atv = partes(df["atividades_artigos"])
    if not atv.empty:
        rot = atv.str.replace(r"\s*\(\d+ artigos?\)$", "", regex=True)
        if rot.nunique() > 1:
            c = contar(rot, top)
            fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(),
                           "Plantas citadas em artigos sobre cada atividade", "número de plantas",
                           subtitulo="Só uma pista de tema: quem julga a atividade é o modelo, na etapa 5")
            rel.salvar("plantas", fig, "atividades_artigos", "Atividades citadas nos artigos",
                       "Quantas plantas aparecem em artigos que mencionam cada atividade de "
                       "[termos_pubmed].", c)
        else:
            # uma atividade só - em geral "atividade biológica (geral)", da versão 3.2 com
            # [termos_pubmed] vazia: mais útil mostrar QUAIS plantas têm mais artigos
            rotulo = rot.iloc[0]
            n_art = df["atividades_artigos"].fillna("").str.extract(r"\((\d+) artigos?\)\s*$")[0]
            t = (pd.DataFrame({"planta": df["nome_cientifico"], "artigos": numero(n_art)})
                 .dropna().sort_values("artigos", ascending=False))
            rel.stat("plantas", "citadas em artigos com atividade", fmt(len(t)), rotulo)
            t = t.head(top)
            if len(t) >= 3:
                fig = barras_h(t["planta"].tolist(), t["artigos"].astype(int).tolist(),
                               f"As {len(t)} plantas com mais artigos sobre {rotulo}",
                               "artigos da descoberta que citam a planta e a atividade", italico=True,
                               subtitulo="Só uma pista de tema: quem julga a atividade é o modelo, na etapa 5")
                rel.salvar("plantas", fig, "atividades_artigos", "Plantas com mais artigos sobre atividade",
                           f"Plantas citadas em artigos sobre a região que mencionam {rotulo}. Com "
                           "[termos_pubmed] vazia, a versão 3.2 usa os termos do filtro geral de atividade "
                           "da etapa 5.", t)

    fam = df.loc[~nao_rec].groupby(df["familia"].fillna("(sem família)")).size() \
        .sort_values(ascending=False).head(top)
    fig = barras_h(fam.index.tolist(), fam.tolist(), f"As {len(fam)} famílias com mais plantas na lista final",
                   "número de plantas")
    rel.salvar("plantas", fig, "familias", "Famílias na lista final",
               "Plantas reconhecidas por família, juntando GBIF, sua lista e artigos.",
               fam.rename_axis("familia").reset_index(name="plantas"))

    # distribuição por estado (Flora e Funga do Brasil)
    est = df["estados_br"].dropna().astype(str)
    if not est.empty:
        desconhecida = est.eq("distribuição desconhecida")
        rel.stat("plantas", "com estado(s) conhecido(s)", fmt(int((~desconhecida).sum())),
                 f"{pct(int((~desconhecida).sum()), len(est))}; o resto: distribuição desconhecida")
        endem = df["endemismo_br"].eq("endêmica do Brasil").sum()
        if endem:
            rel.stat("plantas", "endêmicas do Brasil", fmt(int(endem)), pct(int(endem), len(est)))
        ufs = partes(est[~desconhecida]).value_counts()
        if not ufs.empty:
            rot = ufs.index.tolist() + ["distribuição desconhecida"]
            val = [int(v) for v in ufs.values] + [int(desconhecida.sum())]
            fig = barras_h(rot, val, "Plantas da lista por estado", "plantas",
                           cores=[SERIE[0]] * len(ufs) + [CINZA],
                           subtitulo="Estados de ocorrência segundo a Flora e Funga do Brasil; "
                                     "uma planta conta em todos os estados em que ocorre")
            rel.salvar("plantas", fig, "estados", "Plantas por estado",
                       "Quantas plantas da lista ocorrem em cada estado, segundo a Flora e Funga do "
                       "Brasil (coluna estados_br). Em cinza, as sem estado conhecido: em geral, "
                       "espécies que não constam da Flora ou que ela registra só como 'Brasil'.",
                       pd.DataFrame({"estado": rot, "plantas": val}))


def descartados(rel: Relatorio, ler: Leitor, top: int):
    """plantas_descartados.csv (versão 3.1): nomes do GBIF e dos artigos que ficaram fora."""
    d = ler.csv("plantas_descartados.csv", ["nome", "fonte", "motivo", "n_artigos"])
    if d is None or d.empty:
        return
    rel.stat("plantas", "nomes descartados", fmt(len(d)), "não são plantas ou só gênero")
    d["tipo"] = d["motivo"].fillna("(sem motivo)").str.split(":", n=1).str[0].str.strip()
    c = contar(d["tipo"])
    fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Por que os nomes foram descartados",
                   "número de nomes", cores=CINZA,
                   subtitulo="Nomes do GBIF e dos artigos que não entraram em plantas.csv")
    rel.salvar("plantas", fig, "descartados_motivo", "Nomes descartados, por motivo",
               "Pares de palavras, animais, microrganismos e registros só de gênero retirados antes das "
               "etapas seguintes. O motivo completo de cada nome está em plantas_descartados.csv.", c)
    d["n"] = numero(d["n_artigos"]).fillna(0).astype(int)
    t = d[d["n"] > 0].sort_values("n", ascending=False).head(top)
    if len(t) >= 3:
        fig = barras_h(t["nome"].tolist(), t["n"].tolist(),
                       f"Os {len(t)} nomes descartados mais citados nos artigos", "número de artigos",
                       italico=True, cores=CINZA,
                       subtitulo="Confira: uma planta real com erro de grafia no artigo pode estar aqui")
        rel.salvar("plantas", fig, "descartados_mais_citados", "Nomes descartados mais citados",
                   "Nomes que apareceram em muitos artigos sobre a região, mas que nenhuma base reconheceu "
                   "como planta. Se algum for uma planta de verdade, acrescente o nome correto à sua lista.",
                   t[["nome", "fonte", "motivo", "n"]].rename(columns={"n": "artigos"}))


# =============================================================================
# Etapa 3: bioativos
# =============================================================================
ORDEM_BASES = ["COCONUT", "NPASS", "LOTUS", "DUKE", "FOODB"]


def ler_bioativos(ler: Leitor) -> pd.DataFrame | None:
    df = ler.csv("especies_com_compostos_bioativos.csv",
                 ["composto_nome", "composto_id", "composto_inchikey", "base", "nome_cientifico",
                  "familia", "np_classifier_pathway", "np_classifier_superclass", "chemical_class",
                  "qed_drug_likeliness", "np_likeness", "parte_planta_duke", "atividade_ou_alvo",
                  "composto_smiles", "fonte_smiles", "conferencia_smiles", "na_regiao"])
    if df is not None and not df.empty:
        # os gráficos retratam a PROSPECÇÃO da região: com [bioativos]
        # escopo = completo, as plantas de fora ficam fora deles (continuam no
        # banco/, que é o produto publicável)
        if "na_regiao" in df.columns:
            fora = df["na_regiao"].fillna("").str.strip().str.lower() == "não"
            if fora.any():
                print(f"  [bioativos] {fora.sum()} linha(s) de plantas de fora da região "
                      "ficam fora dos gráficos (escopo = completo)")
                df = df[~fora]
        df["_chave"] = chave_composto(df)
    return df


def etapa_bioativos(rel: Relatorio, ler: Leitor, top: int, bio):
    df = bio
    if df is None or df.empty:
        rel.aviso("bioativos", "especies_com_compostos_bioativos.csv não encontrado ou vazio.")
        return
    comp = df.drop_duplicates("_chave")
    com_ik = comp["_chave"].str.match(RE_INCHIKEY).sum()
    rel.stat("bioativos", "pares planta × composto", fmt(len(df)))
    rel.stat("bioativos", "plantas com compostos", fmt(df["nome_cientifico"].nunique()))
    rel.stat("bioativos", "compostos distintos", fmt(len(comp)), f"{pct(com_ik, len(comp))} com InChIKey")
    qed = numero(comp["qed_drug_likeliness"])
    if qed.notna().any():
        rel.stat("bioativos", "compostos com QED ≥ 0,5", fmt((qed >= 0.5).sum()),
                 "semelhantes a fármacos orais")
    npass = comp["atividade_ou_alvo"].notna().sum()
    rel.stat("bioativos", "com atividade no NPASS", fmt(npass), pct(npass, len(comp)))

    # pares e compostos por base
    b = df[["base", "_chave"]].assign(base=df["base"].fillna("")).copy()
    b = b.assign(base=b["base"].str.split(r"\s*;\s*")).explode("base")
    b = b[b["base"].ne("")]
    pares = b["base"].value_counts()
    comps = b.drop_duplicates(["base", "_chave"])["base"].value_counts()
    ordem = [x for x in ORDEM_BASES if x in pares] + [x for x in pares.index if x not in ORDEM_BASES]
    fig = barras_agrupadas_h(ordem, {"pares planta × composto": [int(pares.get(x, 0)) for x in ordem],
                                     "compostos distintos": [int(comps.get(x, 0)) for x in ordem]},
                             "Contribuição de cada base de compostos", "contagem",
                             subtitulo="Um par encontrado em duas bases conta nas duas")
    so_uma = df.loc[~df["base"].fillna("").str.contains(";"), "base"].value_counts()
    tab = pd.DataFrame({"base": ordem, "pares": [int(pares.get(x, 0)) for x in ordem],
                        "compostos_distintos": [int(comps.get(x, 0)) for x in ordem],
                        "pares_so_nesta_base": [int(so_uma.get(x, 0)) for x in ordem]})
    rel.salvar("bioativos", fig, "por_base", "Contribuição de cada base",
               "Pares planta × composto e compostos distintos encontrados em cada base. A tabela "
               "também traz quantos pares só existem naquela base (contribuição exclusiva).", tab)

    # estrutura (SMILES): quantos compostos têm e de onde veio
    # por composto: tem SMILES se alguma das suas linhas tem (planilhas antigas,
    # sem a propagação por InChIKey, podem ter o SMILES só em parte das linhas)
    smi = df[["_chave", "composto_smiles", "fonte_smiles"]].copy()
    smi["_tem"] = smi["composto_smiles"].fillna("").astype(str).str.strip() != ""
    smi = smi.sort_values("_tem", ascending=False).drop_duplicates("_chave")
    tem_smi = smi["_tem"]
    rel.stat("bioativos", "compostos com SMILES", fmt(int(tem_smi.sum())), pct(int(tem_smi.sum()), len(comp)))
    if tem_smi.any():
        origem = smi["fonte_smiles"].where(tem_smi, "sem SMILES")
        origem = origem.fillna("origem não registrada (planilha anterior à 3.8)").astype(str).str.strip()
        ordem_smi = ["COCONUT", "NPASS", "LOTUS", "PubChem"]
        c = origem.value_counts()
        rotulos = ([x for x in ordem_smi if x in c]
                   + [x for x in c.index if x not in ordem_smi + ["sem SMILES"]]
                   + (["sem SMILES"] if "sem SMILES" in c else []))
        valores = [int(c[x]) for x in rotulos]
        fig = barras_h(rotulos, valores, "Origem da estrutura (SMILES) dos compostos",
                       "compostos distintos",
                       cores=[CINZA if r == "sem SMILES" or r.startswith("origem não registrada") else SERIE[0]
                              for r in rotulos],
                       subtitulo=f"{pct(int(tem_smi.sum()), len(comp))} dos {fmt(len(comp))} compostos "
                                 "com estrutura; COCONUT e NPASS têm prioridade")
        sem = smi[~tem_smi]
        tab = pd.DataFrame({"origem": rotulos, "compostos": valores,
                            "percentual": [round(100 * v / len(comp), 1) for v in valores]})
        conf = (df[["_chave", "conferencia_smiles"]].dropna().drop_duplicates("_chave")
                ["conferencia_smiles"].astype(str))
        if not conf.empty:
            tipo = conf.str.split(":").str[0].str.strip()
            ordem_c = ["mesma molécula", "estereoquímica diferente", "estruturas diferentes",
                       "SMILES inválido"]
            ct = tipo.value_counts()
            rot = [x for x in ordem_c if x in ct] + [x for x in ct.index if x not in ordem_c]
            fig_c = barras_h(rot, [int(ct[x]) for x in rot],
                             "Conferência dos SMILES entre as fontes", "compostos distintos",
                             cores=[SERIE[2] if r == "mesma molécula" else SERIE[3]
                                    if r == "estereoquímica diferente" else SERIE[7] for r in rot],
                             subtitulo=f"{fmt(len(conf))} compostos com SMILES em 2 ou mais fontes "
                                       "(NPASS, COCONUT, LOTUS, PubChem), comparados pela estrutura")
            pares = conf[tipo != "mesma molécula"].str.split(":", n=1).str[1].str.strip().value_counts()
            tab_c = pd.DataFrame({"resultado": rot, "compostos": [int(ct[x]) for x in rot]})
            if not pares.empty:
                tab_c = pd.concat([tab_c, pd.DataFrame({"resultado": "divergência: " + pares.index,
                                                        "compostos": pares.values})])
            rel.salvar("bioativos", fig_c, "conferencia_smiles", "Conferência dos SMILES entre as fontes",
                       "Compara a estrutura (não o texto) que cada fonte dá ao composto. 'Mesma "
                       "molécula' não precisa de conferência; as divergências estão na coluna "
                       "conferencia_smiles da planilha, e a tabela deste gráfico conta quais fontes "
                       "discordam de quais.", tab_c)
        rel.salvar("bioativos", fig, "origem_smiles", "Origem da estrutura (SMILES)",
                   "De onde veio o SMILES de cada composto: COCONUT e NPASS primeiro; LOTUS e PubChem "
                   "só completam os que eles não têm. Os sem SMILES são, em geral, compostos do "
                   f"Dr. Duke sem InChIKey (nomes genéricos ou de misturas): {fmt(len(sem))} no total.",
                   tab)

    pl = df.groupby("nome_cientifico")["_chave"].nunique().sort_values(ascending=False)
    t = pl.head(top)
    fig = barras_h(t.index.tolist(), t.tolist(), f"As {len(t)} plantas com mais compostos conhecidos",
                   "compostos distintos", italico=True,
                   subtitulo=f"Mediana entre as {fmt(len(pl))} plantas com compostos: {fmt(pl.median())}")
    rel.salvar("bioativos", fig, "plantas_mais_compostos", "Plantas com mais compostos",
               "Plantas quimicamente mais estudadas. Pouco composto pode significar só pouca pesquisa.",
               pl.rename_axis("planta").reset_index(name="compostos"))

    via = partes(comp["np_classifier_pathway"].fillna("sem classificação"), r"\s*[|;]\s*")
    c = contar(via, 10)
    fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Compostos por via biossintética",
                   "compostos distintos", cores=[CINZA if r.startswith("sem") else SERIE[0]
                                                 for r in c["rotulo"]],
                   subtitulo="NP Classifier (COCONUT); um composto pode ter mais de uma via")
    rel.salvar("bioativos", fig, "vias_biossinteticas", "Vias biossintéticas",
               "Perfil químico do conjunto: terpenoides, alcaloides, chiquimatos/fenilpropanoides etc.", c)

    sup = partes(comp["np_classifier_superclass"], r"\s*[|;]\s*")
    if not sup.empty:
        c = contar(sup, top)
        fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), f"As {min(top, len(c))} superclasses mais frequentes",
                       "compostos distintos")
        rel.salvar("bioativos", fig, "superclasses", "Superclasses químicas",
                   "Superclasse do NP Classifier (ex.: flavonoides, diterpenoides, alcaloides indólicos).", c)

    # famílias x vias (proporção dentro da família)
    fv = df[["familia", "_chave", "np_classifier_pathway"]].dropna(subset=["familia"]).drop_duplicates(
        ["familia", "_chave"])
    fv = fv.assign(via=fv["np_classifier_pathway"].fillna("").str.split(r"\s*[|;]\s*")).explode("via")
    fv = fv[fv["via"].ne("")]
    if not fv.empty:
        fams = fv.groupby("familia")["_chave"].nunique().sort_values(ascending=False).head(min(top, 20)).index
        vias = fv["via"].value_counts().head(8).index
        m = (fv[fv["familia"].isin(fams) & fv["via"].isin(vias)]
             .groupby(["familia", "via"])["_chave"].nunique().unstack(fill_value=0)
             .reindex(index=fams, columns=vias, fill_value=0))
        totais = fv[fv["familia"].isin(fams)].groupby("familia")["_chave"].nunique().reindex(fams)
        prop = m.div(totais, axis=0).fillna(0) * 100
        prop.index = [f"{f} ({fmt(n)})" for f, n in totais.items()]
        fig = mapa_calor(prop, "Perfil químico das famílias", "% dos compostos da família",
                         fmt_cel="{:.0f}",
                         subtitulo="Linhas: famílias com mais compostos (total entre parênteses)")
        rel.salvar("bioativos", fig, "familias_x_vias", "Famílias × vias biossintéticas",
                   "Porcentagem dos compostos de cada família em cada via. Mostra a 'assinatura' "
                   "química das famílias (ex.: alcaloides em Apocynaceae, terpenoides em Lamiaceae).",
                   prop.round(1).rename_axis("familia").reset_index())

    cp = df.groupby("_chave").agg(nome=("composto_nome", "first"), plantas=("nome_cientifico", "nunique"))
    t = cp.sort_values("plantas", ascending=False).head(top)
    fig = barras_h([cortar(n if not vazio(n) else k, 40) for n, k in zip(t["nome"], t.index)],
                   t["plantas"].tolist(), f"Os {len(t)} compostos presentes em mais plantas",
                   "número de plantas")
    rel.salvar("bioativos", fig, "compostos_mais_frequentes", "Compostos mais frequentes",
               "Compostos de distribuição ampla (ex.: ácidos fenólicos, esteróis) aparecem em muitas "
               "plantas; os raros podem ser marcadores de espécie.",
               t.rename_axis("chave").reset_index())

    npl = numero(comp["np_likeness"])
    ok = qed.notna() & npl.notna()
    if ok.sum() >= 20:
        fig, ax = plt.subplots(figsize=(8, 5))
        hb = ax.hexbin(npl[ok], qed[ok], gridsize=40, cmap=CMAP_AZUL, mincnt=1, linewidths=0.2,
                       edgecolors=FUNDO)
        ax.axhline(0.5, color=TEXTO2, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(0.01, 0.515, f"QED ≥ 0,5: {fmt((qed[ok] >= 0.5).sum())} compostos",
                transform=ax.get_yaxis_transform(), va="bottom", fontsize=8.5, color=TEXTO,
                bbox={"facecolor": FUNDO, "edgecolor": "none", "alpha": 0.85, "pad": 2})
        cb = fig.colorbar(hb, ax=ax, fraction=0.04, pad=0.02)
        cb.ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        cb.set_label("número de compostos", color=TEXTO2)
        cb.outline.set_visible(False)
        ax.set_xlabel("NP-likeness (mais alto = mais típico de produto natural)")
        ax.set_ylabel("QED (semelhança com fármaco, 0 a 1)")
        ax.set_ylim(0, 1)
        ax.set_title("Espaço químico: semelhança com fármacos × com produtos naturais")
        rel.salvar("bioativos", fig, "qed_x_np_likeness", "QED × NP-likeness",
                   "Cada hexágono reúne compostos com valores parecidos (cor = quantos). Acima da linha "
                   "tracejada estão os compostos com propriedades mais próximas de fármacos orais.",
                   pd.DataFrame({"chave": comp.loc[ok, "_chave"], "nome": comp.loc[ok, "composto_nome"],
                                 "qed": qed[ok], "np_likeness": npl[ok]}))

    parte = partes(df["parte_planta_duke"])
    if not parte.empty:
        c = contar(parte, top)
        fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(),
                       "Partes da planta com compostos registrados (Dr. Duke)", "pares planta × composto")
        rel.salvar("bioativos", fig, "partes_duke", "Partes da planta (Dr. Duke)",
                   "Em que parte da planta cada composto foi registrado, segundo o Dr. Duke.", c)


# =============================================================================
# Etapa 4: chembl
# =============================================================================
def status_chembl(v, corresp) -> str:
    v = "" if vazio(v) else str(v)
    if v == "consulta pendente (rode de novo)":
        return "consulta pendente"
    if v == "composto não encontrado no ChEMBL":
        return "não encontrado no ChEMBL"
    if v.startswith("no ChEMBL, sem atividade"):
        return "no ChEMBL, sem registro ativo"
    if v == "sem InChIKey válido":
        return "sem InChIKey válido"
    if not v or v == "não consultado no ChEMBL":
        return "não consultado"
    return ("com atividade (estereoisômero)" if str(corresp).startswith("estereo")
            else "com atividade (InChIKey exato)")


ORDEM_CHEMBL = ["com atividade (InChIKey exato)", "com atividade (estereoisômero)",
                "no ChEMBL, sem registro ativo", "não encontrado no ChEMBL",
                "sem InChIKey válido", "consulta pendente", "não consultado"]
COR_CHEMBL = [SERIE[0], "#86b6ef", SERIE[1], CINZA, CINZA, CINZA, CINZA]
TIPO_ENSAIO = {"B": "ligação (B)", "F": "funcional (F)", "A": "ADME (A)", "T": "toxicidade (T)",
               "P": "físico-químico (P)", "U": "não classificado (U)"}


def etapa_chembl(rel: Relatorio, ler: Leitor, top: int):
    df = ler.csv("compostos_chembl.csv", ["InChIKey", "chembl_id", "correspondencia_chembl",
                                          "atividades_chembl"])
    if df is None:
        rel.aviso("chembl", "compostos_chembl.csv não encontrado: a etapa 4 ainda não terminou.")
        return
    if df.empty:
        rel.aviso("chembl", "compostos_chembl.csv vazio ([chembl] ativar = false?).")
        return
    st = pd.Series([status_chembl(v, c) for v, c in zip(df["atividades_chembl"],
                                                        df["correspondencia_chembl"])])
    cnt = st.value_counts()
    ativos = int(cnt.get(ORDEM_CHEMBL[0], 0) + cnt.get(ORDEM_CHEMBL[1], 0))
    no_chembl = df["chembl_id"].notna().sum()
    rel.stat("chembl", "compostos consultados", fmt(len(df)))
    rel.stat("chembl", "encontrados no ChEMBL", fmt(no_chembl), pct(no_chembl, len(df)))
    rel.stat("chembl", "com atividade medida como ativa", fmt(ativos), pct(ativos, len(df)))
    if cnt.get("consulta pendente"):
        rel.stat("chembl", "consultas pendentes", fmt(cnt["consulta pendente"]),
                 "rode --a-partir-de chembl")
    ordem = [s for s in ORDEM_CHEMBL if cnt.get(s)]
    fig = barras_h(ordem, [int(cnt[s]) for s in ordem], "O que o ChEMBL tem sobre os compostos",
                   "número de compostos", cores=[COR_CHEMBL[ORDEM_CHEMBL.index(s)] for s in ordem],
                   extra=[pct(cnt[s], len(df)) for s in ordem])
    rel.salvar("chembl", fig, "situacao_compostos", "Situação dos compostos no ChEMBL",
               "Compostos com registro ativo (pChEMBL ≥ mínimo do input) para as suas atividades. "
               "Estereoisômero = mesma conectividade, configuração diferente: indicativo, não prova.",
               pd.DataFrame({"situacao": ordem, "compostos": [int(cnt[s]) for s in ordem]}))

    ev = ler.csv("evidencias_chembl.csv", ["InChIKey", "composto", "atividade", "correspondencia",
                                           "alvo", "organismo_alvo", "tipo_ensaio", "medida",
                                           "pchembl", "ano", "PMID"])
    if ev is None or ev.empty:
        rel.aviso("chembl", "evidencias_chembl.csv vazio: nenhum registro de ensaio ativo.")
        return
    proprias = ev[~ev["correspondencia"].fillna("").str.startswith("prevista")]
    rel.stat("chembl", "registros de ensaio ativos", fmt(len(proprias)),
             f"{pct(proprias['PMID'].notna().sum(), len(proprias))} com PMID")
    prev = len(ev) - len(proprias)
    if prev:
        rel.stat("chembl", "registros previstos por similaridade", fmt(prev), "hipótese, não evidência")
    ev = proprias
    if ev.empty:
        return

    a = ev.groupby("atividade").agg(compostos=("InChIKey", "nunique"), registros=("InChIKey", "size")) \
        .sort_values("compostos", ascending=False).head(top)
    fig = barras_h(a.index.tolist(), a["compostos"].tolist(),
                   "Compostos com atividade medida, por atividade", "compostos distintos",
                   extra=[f"({fmt(r)} registros)" for r in a["registros"]])
    rel.salvar("chembl", fig, "atividades", "Atividades com mais compostos ativos",
               "Quantos compostos das suas plantas têm ensaio ativo para cada atividade (ou alvo, "
               "se [termos_pubmed] estiver vazio).", a.reset_index())

    alvo = ev.assign(alvo_org=ev["alvo"].fillna("?") + " — " + ev["organismo_alvo"].fillna("?"))
    a = alvo.groupby("alvo_org")["InChIKey"].nunique().sort_values(ascending=False).head(top)
    fig = barras_h(a.index.tolist(), a.tolist(), f"Os {len(a)} alvos com mais compostos ativos",
                   "compostos distintos")
    rel.salvar("chembl", fig, "alvos", "Alvos mais frequentes",
               "Alvo biológico (proteína, célula ou organismo) e espécie do alvo dos ensaios ativos.",
               a.rename_axis("alvo — organismo").reset_index(name="compostos"))

    p = numero(ev["pchembl"]).dropna()
    if len(p) >= 5:
        fig = histograma(p, "Potência dos registros ativos (pChEMBL)",
                         "pChEMBL (= −log10 da concentração molar; mais alto = mais potente)",
                         bins=[x / 4 for x in range(int(p.min() * 4), int(p.max() * 4) + 2)],
                         linhas_ref=[(5, "10 µM"), (6, "1 µM"), (7, "100 nM"), (8, "10 nM")],
                         subtitulo=f"{fmt(len(p))} registros com pChEMBL · mediana {p.median():.1f}".replace(".", ","))
        rel.salvar("chembl", fig, "pchembl", "Distribuição de potência",
                   "pChEMBL 6 = 1 µM; 7 = 100 nM. Compostos de produtos naturais raramente passam de 7; "
                   "valores altos merecem atenção (e conferência no artigo).",
                   pd.DataFrame({"pchembl": p.values}))

        top_at = ev["atividade"].value_counts().head(10).index
        grupos = [(at, numero(ev.loc[ev["atividade"] == at, "pchembl"]).dropna()) for at in top_at]
        grupos = [(at, g) for at, g in grupos if len(g) >= 3][::-1]
        if len(grupos) >= 2:
            fig, ax = plt.subplots(figsize=(9, _altura(len(grupos), por=0.42)))
            boxplot_h(ax, [g.values for _, g in grupos], widths=0.55, patch_artist=True,
                            medianprops={"color": TEXTO, "linewidth": 1.6},
                            boxprops={"facecolor": "#b7d3f6", "edgecolor": SERIE[0]},
                            whiskerprops={"color": SERIE[0]}, capprops={"color": SERIE[0]},
                            flierprops={"marker": "o", "markersize": 3, "markerfacecolor": SERIE[0],
                                        "markeredgecolor": FUNDO, "alpha": 0.6})
            ax.set_yticks(range(1, len(grupos) + 1),
                          [f"{cortar(at, 40)} (n={fmt(len(g))})" for at, g in grupos], color=TEXTO)
            ax.tick_params(axis="y", length=0)
            ax.spines["left"].set_visible(False)
            ax.grid(True, axis="x")
            ax.set_axisbelow(True)
            ax.set_xlabel("pChEMBL")
            ax.set_title("Potência por atividade")
            rel.salvar("chembl", fig, "pchembl_por_atividade", "Potência por atividade",
                       "Caixa = metade central dos registros; traço = mediana. Compare a potência típica "
                       "entre as atividades com mais registros.",
                       pd.concat([pd.DataFrame({"atividade": at, "pchembl": g.values}) for at, g in grupos]))

    m = contar(ev["medida"].fillna("(sem tipo)"), 12)
    fig = barras_h(m["rotulo"].tolist(), m["n"].tolist(), "Tipos de medida nos registros ativos",
                   "registros")
    rel.salvar("chembl", fig, "tipos_medida", "Tipos de medida",
               "IC50, Ki, EC50, % de inibição, CIM... Medidas diferentes não são diretamente comparáveis.", m)

    if ev["tipo_ensaio"].notna().any():
        t = contar(ev["tipo_ensaio"].map(lambda x: TIPO_ENSAIO.get(str(x), str(x))))
        fig = barras_h(t["rotulo"].tolist(), t["n"].tolist(), "Tipos de ensaio", "registros")
        rel.salvar("chembl", fig, "tipos_ensaio", "Tipos de ensaio",
                   "B = ligação ao alvo; F = efeito funcional (célula, organismo); A = ADME; T = toxicidade.", t)

    anos = numero(ev.drop_duplicates(["PMID"])["ano"]).dropna().astype(int)
    if len(anos) >= 3:
        s = anos.value_counts().sort_index()
        fig = linhas_tempo({"artigos de origem": s}, "Artigos de origem dos registros ativos, por ano",
                           "artigos")
        rel.salvar("chembl", fig, "artigos_por_ano", "Artigos de origem por ano",
                   "Ano de publicação dos documentos do ChEMBL de onde vêm os registros ativos.",
                   s.rename_axis("ano").reset_index(name="artigos"))


# =============================================================================
# Etapa 5: pubmed
# =============================================================================
STATUS_PUBMED = [  # (início da mensagem, rótulo curto, é cinza?)
    ("nenhuma relação causal positiva", "artigos lidos, nenhum positivo", False),
    ("nenhum artigo encontrado", "nenhum artigo encontrado", True),
    ("artigos encontrados; leitura pelo modelo pendente", "leitura pelo modelo pendente", True),
    ("artigos encontrados; leitura pelo Llama pendente", "leitura pelo modelo pendente", True),   # planilhas antigas
    ("busca pendente", "busca pendente (rode de novo)", True),
    ("não pesquisado: táxon sem nível de espécie", "não pesquisado: só gênero", True),
    ("não pesquisado: nome não reconhecido", "não pesquisado: nome não reconhecido", True),
    ("não pesquisado: plantas_pesquisadas", "não pesquisado: sem compostos", True),
    ("não pesquisado: fora do limite", "não pesquisado: acima do limite max_*", True),
    ("não pesquisado: sem vínculo no PubChem", "não pesquisado: sem vínculo/nome", True),
]
POSITIVO = "atividade demonstrada"


def status_pubmed(texto, n_pos) -> str:
    if n_pos and n_pos > 0:
        return POSITIVO
    t = "" if vazio(texto) else str(texto)
    for inicio, rot, _ in STATUS_PUBMED:
        if t.startswith(inicio):
            return rot
    return POSITIVO if t else "sem informação"


def grafico_status(rel, etapa, slug, serie_status, total, entidade):
    cnt = serie_status.value_counts()
    ordem = [POSITIVO] + [r for _, r, _ in STATUS_PUBMED] + ["sem informação"]
    ordem = [o for o in ordem if cnt.get(o)]
    cinza = {r for _, r, c in STATUS_PUBMED if c} | {"sem informação"}
    cores = [SERIE[0] if o == POSITIVO else (CINZA if o in cinza else SERIE[1]) for o in ordem]
    leg = [Patch(color=SERIE[0], label="com artigo positivo"),
           Patch(color=SERIE[1], label="artigos lidos, sem positivo"),
           Patch(color=CINZA, label="sem artigo, pendente ou não pesquisado")]
    fig = barras_h(ordem, [int(cnt[o]) for o in ordem], f"Resultado da busca de atividades: {entidade}",
                   f"número de {entidade}", cores=cores, extra=[pct(cnt[o], total) for o in ordem],
                   legenda=leg)
    rel.salvar(etapa, fig, slug, f"Resultado da busca: {entidade}",
               f"Situação de cada {entidade[:-1] if entidade.endswith('s') else entidade} na etapa 5. "
               "'Busca pendente' e 'leitura pendente' se resolvem rodando de novo; 'nenhum artigo' "
               "costuma indicar só pouca pesquisa.",
               pd.DataFrame({"situacao": ordem, "n": [int(cnt[o]) for o in ordem]}))


def barras_evidencia(rel, etapa, slug, nomes, n_art, melhor, titulo, descr, italico, tabela):
    cores = [COR_EVIDENCIA.get(m if not vazio(m) else "não informado", CINZA) for m in melhor]
    presentes = [e for e in EVIDENCIAS if e in set(m if not vazio(m) else "não informado" for m in melhor)]
    leg = [Patch(color=COR_EVIDENCIA[e], label=e) for e in presentes]
    fig = barras_h(nomes, n_art, titulo, "artigos com resultado positivo", cores=cores,
                   italico=italico, legenda=leg,
                   subtitulo="Cor = melhor evidência (escuro = mais forte: clínico > in vivo > ex vivo > in vitro)")
    rel.salvar(etapa, fig, slug, titulo, descr, tabela)


def etapa_pubmed(rel: Relatorio, ler: Leitor, top: int, parcial: bool):
    pl = ler.csv("atividades_plantas.csv", ["nome_cientifico", "familia", "nome_popular_pt",
                                            "n_compostos", "atividades_relatadas_planta",
                                            "melhor_evidencia_planta", "n_artigos_positivos"])
    co = ler.csv("atividades_compostos.csv", ["composto_nome", "nome_pubchem", "InChIKey", "n_plantas",
                                              "atividades_relatadas_composto", "melhor_evidencia_composto",
                                              "n_artigos_positivos", "atividades_duke",
                                              "atividades_chembl"])
    ev = ler.csv("evidencias_pubmed.csv", ["tipo_entidade", "entidade", "PMID", "ano", "atividades",
                                           "tipo_estudo", "parte_planta", "via_busca"])
    if pl is None and co is None:
        dica = f" (rode {RODAR} parcial e depois {GRAFICOS} --parcial)" if not parcial else \
            f" (rode {RODAR} parcial antes)"
        rel.aviso("pubmed", "atividades_plantas.csv / atividades_compostos.csv não encontrados: "
                            "a etapa 5 ainda não terminou" + dica + ".")
    llm_progresso(rel, top)
    if pl is None and co is None:
        return

    if pl is not None and not pl.empty:
        pl["n_pos"] = numero(pl["n_artigos_positivos"]).fillna(0).astype(int)
        pl["status"] = [status_pubmed(t, n) for t, n in zip(pl["atividades_relatadas_planta"], pl["n_pos"])]
        pesquisadas = ~pl["status"].str.startswith("não pesquisado")
        pos = (pl["n_pos"] > 0).sum()
        rel.stat("pubmed", "plantas com atividade demonstrada", fmt(pos),
                 f"{pct(pos, pesquisadas.sum())} das {fmt(pesquisadas.sum())} pesquisadas")
        grafico_status(rel, "pubmed", "status_plantas", pl["status"], len(pl), "plantas")
        t = pl[pl["n_pos"] > 0].sort_values(["n_pos", "nome_cientifico"], ascending=[False, True]).head(top)
        if not t.empty:
            barras_evidencia(rel, "pubmed", "plantas_mais_artigos", t["nome_cientifico"].tolist(),
                             t["n_pos"].tolist(), t["melhor_evidencia_planta"].tolist(),
                             f"As {len(t)} plantas com mais artigos positivos",
                             "Plantas com mais artigos que demonstram experimentalmente uma atividade "
                             "(extrato, fração, óleo ou substância isolada da planta).", True,
                             t[["nome_cientifico", "familia", "nome_popular_pt", "n_pos",
                                "melhor_evidencia_planta"]].rename(columns={"n_pos": "artigos_positivos"}))
        oportunidades(rel, pl, top)

    if co is not None and not co.empty:
        co["n_pos"] = numero(co["n_artigos_positivos"]).fillna(0).astype(int)
        co["status"] = [status_pubmed(t, n) for t, n in zip(co["atividades_relatadas_composto"], co["n_pos"])]
        pos = (co["n_pos"] > 0).sum()
        rel.stat("pubmed", "compostos com atividade demonstrada", fmt(pos), pct(pos, len(co)))
        grafico_status(rel, "pubmed", "status_compostos", co["status"], len(co), "compostos")
        t = co[co["n_pos"] > 0].sort_values("n_pos", ascending=False).head(top)
        if not t.empty:
            nomes = [n if not vazio(n) else (p if not vazio(p) else ik)
                     for n, p, ik in zip(t["composto_nome"], t["nome_pubchem"], t["InChIKey"])]
            barras_evidencia(rel, "pubmed", "compostos_mais_artigos", nomes, t["n_pos"].tolist(),
                             t["melhor_evidencia_composto"].tolist(),
                             f"Os {len(t)} compostos com mais artigos positivos",
                             "Compostos muito estudados em geral (ex.: quercetina) lideram: o artigo trata do "
                             "composto, não necessariamente da sua planta.", False,
                             t[["composto_nome", "nome_pubchem", "InChIKey", "n_plantas", "n_pos",
                                "melhor_evidencia_composto"]].rename(columns={"n_pos": "artigos_positivos"}))
        fontes_atividade(rel, co)

    if ev is None or ev.empty:
        rel.aviso("pubmed", "evidencias_pubmed.csv vazio: ainda nenhum artigo positivo.")
        return
    rel.stat("pubmed", "artigos positivos distintos", fmt(ev["PMID"].nunique()))
    ev = ev.assign(tipo_entidade=ev["tipo_entidade"].fillna("?"))

    # atividades por tipo de entidade
    a = ev.assign(atividade=ev["atividades"].fillna("").str.split(r"\s*;\s*")).explode("atividade")
    a["atividade"] = a["atividade"].str.strip().str.lower()
    a = a[a["atividade"].ne("")]
    if not a.empty:
        tab = (a.drop_duplicates(["tipo_entidade", "entidade", "PMID", "atividade"])
               .groupby(["atividade", "tipo_entidade"])["PMID"].nunique().unstack(fill_value=0))
        for c in ("planta", "composto"):
            if c not in tab:
                tab[c] = 0
        tab = tab.assign(total=tab["planta"] + tab["composto"]).sort_values("total", ascending=False).head(top)
        fig = barras_agrupadas_h(tab.index.tolist(), {"plantas": tab["planta"].tolist(),
                                                      "compostos": tab["composto"].tolist()},
                                 "Atividades demonstradas nos artigos", "artigos positivos")
        rel.salvar("pubmed", fig, "atividades", "Atividades mais demonstradas",
                   "Artigos positivos por atividade (rótulo dado pelo modelo), separados entre artigos sobre "
                   "plantas e sobre compostos.", tab.rename_axis("atividade").reset_index())

        # mapa planta x atividade
        ap = a[a["tipo_entidade"] == "planta"]
        if ap["entidade"].nunique() >= 2 and ap["atividade"].nunique() >= 2:
            plantas_top = ap.groupby("entidade")["PMID"].nunique().sort_values(ascending=False) \
                .head(min(top, 25)).index
            ativ_top = ap["atividade"].value_counts().head(12).index
            m = (ap[ap["entidade"].isin(plantas_top) & ap["atividade"].isin(ativ_top)]
                 .groupby(["entidade", "atividade"])["PMID"].nunique().unstack(fill_value=0)
                 .reindex(index=plantas_top, columns=ativ_top, fill_value=0))
            fig = mapa_calor(m, "Plantas × atividades demonstradas", "artigos positivos",
                             italico_linhas=True)
            rel.salvar("pubmed", fig, "plantas_x_atividades", "Plantas × atividades",
                       "Quantos artigos positivos ligam cada planta a cada atividade. Células vazias numa "
                       "planta muito estudada podem ser lacunas a explorar.",
                       m.rename_axis("planta").reset_index())

    # tipo de estudo
    e = ev.assign(estudo=ev["tipo_estudo"].fillna("não informado").str.split(r"\s*;\s*")).explode("estudo")
    e = e.drop_duplicates(["tipo_entidade", "entidade", "PMID", "estudo"])
    tab = e.groupby(["estudo", "tipo_entidade"]).size().unstack(fill_value=0)
    ordem = [x for x in EVIDENCIAS if x in tab.index] + [x for x in tab.index if x not in EVIDENCIAS]
    tab = tab.reindex(ordem)
    series = {("plantas" if c == "planta" else "compostos" if c == "composto" else c): tab[c].tolist()
              for c in ("planta", "composto") if c in tab}
    if series:
        fig = barras_agrupadas_h(ordem, series, "Tipo de estudo dos artigos positivos", "artigos",
                                 subtitulo="Da evidência mais forte (em cima) à mais fraca")
        rel.salvar("pubmed", fig, "tipos_estudo", "Tipo de estudo",
                   "In vitro predomina; estudos in vivo e clínicos são os que mais pesam numa prospecção.",
                   tab.rename_axis("tipo_estudo").reset_index())

    # partes da planta
    pp = ev[ev["tipo_entidade"] == "planta"]
    pp = pp.assign(parte=pp["parte_planta"].fillna("não informado").str.split(r"\s*;\s*")).explode("parte")
    pp = pp.drop_duplicates(["entidade", "PMID", "parte"])
    if not pp.empty:
        c = contar(pp["parte"])
        coleta = [COLETA.get(r, "indefinida") for r in c["rotulo"]]
        c["coleta"] = coleta
        leg = [Patch(color=COR_COLETA[k], label=f"coleta {k}") for k in COR_COLETA if k in coleta]
        fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Parte da planta usada nos artigos positivos",
                       "artigos (planta × artigo)", cores=[COR_COLETA[k] for k in coleta], legenda=leg)
        rel.salvar("pubmed", fig, "partes_planta", "Partes da planta",
                   "Folha, fruto, semente, flor e exsudatos permitem coleta sem matar a planta; raiz, casca, "
                   "caule e planta inteira, em geral, não.", c)

    # por ano
    ev["ano_n"] = numero(ev["ano"])
    anos = ev.dropna(subset=["ano_n"]).drop_duplicates(["tipo_entidade", "PMID"])
    if anos["ano_n"].nunique() >= 3:
        series = {("plantas" if t == "planta" else "compostos"): g.groupby(g["ano_n"].astype(int)).size()
                  for t, g in anos.groupby("tipo_entidade") if t in ("planta", "composto")}
        fig = linhas_tempo(series, "Artigos positivos por ano de publicação", "artigos")
        rel.salvar("pubmed", fig, "artigos_por_ano", "Artigos positivos por ano",
                   "Interesse da pesquisa ao longo do tempo. Lembre que só os artigos mais relevantes de cada "
                   "busca são lidos (max_artigos_por_*).",
                   pd.DataFrame(series).fillna(0).astype(int).rename_axis("ano").reset_index())

    v = ev[ev["tipo_entidade"] == "composto"]["via_busca"].dropna()
    if not v.empty:
        c = contar(v)
        fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Como os artigos positivos de compostos foram achados",
                       "artigos", subtitulo="InChIKey = vínculo estrutural no PubChem · nome = busca textual")
        rel.salvar("pubmed", fig, "via_busca", "Via de busca dos compostos",
                   "Se a via InChIKey traz pouco, os compostos são raros no PubChem; a busca pelo nome "
                   "compensa (busca_composto_por_nome).", c)


def oportunidades(rel, pl, top):
    """Plantas com atividade: compostos conhecidos × artigos positivos."""
    d = pl[pl["n_pos"] > 0].copy()
    if len(d) < 5:
        return
    d["nc"] = numero(d["n_compostos"]).fillna(0)
    grupo = {"clínico": "clínico ou in vivo", "in vivo": "clínico ou in vivo",
             "ex vivo": "ex vivo ou in vitro", "in vitro": "ex vivo ou in vitro"}
    d["grupo"] = d["melhor_evidencia_planta"].map(grupo).fillna("não informado")
    cores = {"clínico ou in vivo": SERIE[0], "ex vivo ou in vitro": SERIE[1], "não informado": SERIE[2]}
    # leve deslocamento vertical (determinístico) para separar plantas com o mesmo nº de artigos
    jit = pd.Series([((zlib.crc32(str(n).encode()) % 1000) / 1000 - 0.5) * 0.16 for n in d["nome_cientifico"]], index=d.index)
    d["y"] = d["n_pos"] * (1 + jit)
    fig, ax = plt.subplots(figsize=(9, 5.8))
    for g in ["ex vivo ou in vitro", "não informado", "clínico ou in vivo"]:   # o mais forte por cima
        s = d[d["grupo"] == g]
        if len(s):
            ax.scatter(s["nc"] + 1, s["y"], s=34, color=cores[g], edgecolors=FUNDO, linewidths=1.2,
                       alpha=0.9, zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    _eixo_log(ax)
    ax.set_xlabel("compostos conhecidos + 1 (escala log)")
    ax.set_ylabel("artigos positivos (escala log)")
    # destaque: evidência forte, poucos artigos e química pouco conhecida
    alvo = d[(d["grupo"] == "clínico ou in vivo") & (d["n_pos"] <= 3)].sort_values(["nc", "n_pos"]).head(8)
    fig.canvas.draw()
    ocupados = []                          # rótulos já postos (coordenadas de tela) - evita sobrepor
    for _, r in alvo.iterrows():
        px, py = ax.transData.transform((r["nc"] + 1, r["y"]))
        dy = 4
        while any(abs(px - ox) < 150 and abs(py + dy - oy) < 11 for ox, oy in ocupados):
            dy += 11
        ocupados.append((px, py + dy))
        ax.annotate(cortar(r["nome_cientifico"], 28), (r["nc"] + 1, r["y"]), xytext=(6, dy),
                    textcoords="offset points", fontsize=7.5, fontstyle="italic", color=TEXTO,
                    arrowprops={"arrowstyle": "-", "color": TEXTO3, "linewidth": 0.6} if dy > 4 else None)
    ordem_leg = ["clínico ou in vivo", "ex vivo ou in vitro", "não informado"]
    ax.legend(handles=[Line2D([], [], marker="o", linestyle="", color=cores[g], markersize=6,
                              label=f"{g} ({fmt((d['grupo'] == g).sum())})")
                       for g in ordem_leg if (d["grupo"] == g).any()],
              title="melhor evidência", loc="upper left", title_fontsize=9)
    ax.set_title("Mapa de oportunidades: química conhecida × evidência")
    rel.salvar("pubmed", fig, "mapa_oportunidades", "Mapa de oportunidades",
               "Cada ponto é uma planta com atividade demonstrada. Embaixo à esquerda (azul): evidência "
               "in vivo/clínica, poucos artigos e poucos compostos conhecidos - candidatas pouco "
               "exploradas (as com nome escrito).",
               d[["nome_cientifico", "familia", "nc", "n_pos", "melhor_evidencia_planta"]]
               .rename(columns={"nc": "n_compostos", "n_pos": "artigos_positivos"})
               .sort_values(["artigos_positivos", "n_compostos"]))


def fontes_atividade(rel, co):
    """Combinações das três fontes de atividade de cada composto."""
    st_chembl = co["atividades_chembl"].map(lambda v: status_chembl(v, ""))
    f = pd.DataFrame({
        "PubMed": co["n_pos"] > 0,
        "ChEMBL": st_chembl.str.startswith("com atividade"),
        "Dr. Duke": co["atividades_duke"].map(lambda v: not vazio(v)),
    })
    combo = f.apply(lambda r: " + ".join(k for k, v in r.items() if v) or "nenhuma", axis=1)
    c = contar(combo)
    c = pd.concat([c[c["rotulo"] != "nenhuma"], c[c["rotulo"] == "nenhuma"]])
    if c[c["rotulo"] != "nenhuma"].empty:
        return
    tres = int((f.sum(axis=1) == 3).sum())
    pc = int((f["PubMed"] & f["ChEMBL"]).sum())
    rel.stat("pubmed", "compostos com PubMed + ChEMBL", fmt(pc), "os mais bem sustentados")
    cores = [CINZA if r == "nenhuma" else SERIE[0] if r.count("+") == 2 else
             "#5598e7" if "+" in r else "#9ec5f4" for r in c["rotulo"]]
    fig = barras_h(c["rotulo"].tolist(), c["n"].tolist(), "Fontes de atividade de cada composto",
                   "número de compostos", cores=cores, extra=[pct(n, len(co)) for n in c["n"]],
                   subtitulo=f"Mais escuro = mais fontes concordando ({fmt(tres)} compostos nas três)")
    rel.salvar("pubmed", fig, "fontes_atividade", "Fontes de atividade dos compostos",
               "PubMed (artigos lidos pelo modelo), ChEMBL (ensaios medidos) e Dr. Duke (compilação). "
               "Compostos com atividade em mais de uma fonte são os mais bem sustentados.",
               c.rename(columns={"rotulo": "fontes", "n": "compostos"}))


def llm_progresso(rel, top):
    """Andamento do modelo a partir do cache (útil com a etapa 5 em andamento)."""
    cache = _C.CACHE / "cache_llm_classificacao.jsonl"
    if not cache.exists():
        return
    cont = Counter()
    with open(cache, encoding="utf-8", errors="replace") as f:
        for linha in f:
            try:
                x = json.loads(linha)
            except ValueError:
                continue
            ch = str(x.get("chave", "")).split("|")
            tipo = ch[3] if len(ch) >= 6 else "?"
            cont[(tipo, bool(x.get("positivo")))] += 1
    if not cont:
        return
    total = sum(cont.values())
    pos = sum(v for (t, p), v in cont.items() if p)
    rel.stat("pubmed", "resumos já julgados pelo modelo", fmt(total), f"{pct(pos, total)} positivos")
    tipos = [t for t in ("planta", "composto") if any(k[0] == t for k in cont)]
    if not tipos:
        return
    linhas = ["plantas" if t == "planta" else "compostos" for t in tipos]
    matriz = [[cont[(t, True)], cont[(t, False)]] for t in tipos]
    fig = empilhadas_100(linhas, ["positivo", "negativo"], matriz, [SERIE[0], CINZA],
                         "Julgamentos do modelo (cache)",
                         subtitulo=" · ".join(f"{l}: {fmt(sum(m))} pares" for l, m in zip(linhas, matriz)))
    rel.salvar("pubmed", fig, "julgamentos_modelo", "Julgamentos do modelo",
               "Proporção de pares entidade × resumo que o modelo considerou resultado experimental positivo. "
               "Vem do cache: inclui rodadas anteriores e cresce enquanto a etapa 5 roda.",
               pd.DataFrame([{"tipo": l, "positivos": m[0], "negativos": m[1]} for l, m in zip(linhas, matriz)]))


# =============================================================================
# Visão geral: funis
# =============================================================================
def funil(ax, passos, cor):
    """passos: [(rótulo, valor, rótulo do passo de referência ou None)]."""
    rotulos = [r for r, _, _ in passos]
    valores = [v for _, v, _ in passos]
    ref = {r: v for r, v, _ in passos}
    y = list(range(len(rotulos)))[::-1]
    vmax = max(valores) or 1
    ax.barh(y, valores, color=cor, height=0.62, edgecolor=FUNDO)
    for yi, (r, v, base) in zip(y, passos):
        txt = fmt(v) + (f"  ({pct(v, ref[base])} de: {base})" if base in ref and ref[base] else "")
        ax.text(v + vmax * 0.01, yi, txt, va="center", fontsize=8.5, color=TEXTO2)
    ax.set_yticks(y, rotulos, color=TEXTO)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(0, vmax * 1.45)
    _eixo_valores(ax)


def etapa_geral(rel: Relatorio, ler: Leitor, bio):
    pl = ler.csv("plantas.csv", ["nome_cientifico", "situacao_nome"])
    apl = ler.csv("atividades_plantas.csv", ["atividades_relatadas_planta", "n_artigos_positivos"])
    ch = ler.csv("compostos_chembl.csv", ["chembl_id", "atividades_chembl", "correspondencia_chembl"])
    aco = ler.csv("atividades_compostos.csv", ["n_artigos_positivos"])
    gb = ler.csv("especies_gbif.csv", ["nome_cientifico"])

    # cada passo: (rótulo, valor, passo de referência para a porcentagem)
    fp = []
    if gb is not None and not gb.empty:
        fp.append(("espécies na região (GBIF)", len(gb), None))
    if pl is not None and not pl.empty:
        fp.append(("plantas na lista final", len(pl), None))
        rec = (pl["nome_cientifico"].fillna("").str.split().str.len() >= 2) & \
              pl["situacao_nome"].fillna("").ne("não reconhecido")
        fp.append(("espécies reconhecidas", int(rec.sum()), "plantas na lista final"))
    if bio is not None and not bio.empty:
        fp.append(("com compostos conhecidos", bio["nome_cientifico"].nunique(), "espécies reconhecidas"))
    if apl is not None and not apl.empty:
        n = numero(apl["n_artigos_positivos"]).fillna(0)
        st = [status_pubmed(t, k) for t, k in zip(apl["atividades_relatadas_planta"], n)]
        fp.append(("pesquisadas no PubMed", sum(not s.startswith("não pesquisado") for s in st),
                   "espécies reconhecidas"))
        fp.append(("com atividade demonstrada", int((n > 0).sum()), "pesquisadas no PubMed"))

    fc = []
    if bio is not None and not bio.empty:
        fc.append(("compostos distintos", bio["_chave"].nunique(), None))
        fc.append(("com InChIKey", int(bio.drop_duplicates("_chave")["_chave"].str.match(RE_INCHIKEY).sum()),
                   "compostos distintos"))
    if ch is not None and not ch.empty:
        fc.append(("encontrados no ChEMBL", int(ch["chembl_id"].notna().sum()), "com InChIKey"))
        st = [status_chembl(v, c) for v, c in zip(ch["atividades_chembl"], ch["correspondencia_chembl"])]
        fc.append(("com atividade no ChEMBL", sum(s.startswith("com atividade") for s in st),
                   "encontrados no ChEMBL"))
    if aco is not None and not aco.empty:
        fc.append(("com atividade no PubMed", int((numero(aco["n_artigos_positivos"]).fillna(0) > 0).sum()),
                   "compostos distintos"))

    paineis = [(t, d, c) for t, d, c in [("Plantas", fp, SERIE[0]), ("Compostos", fc, SERIE[1])] if len(d) >= 2]
    if not paineis:
        rel.aviso("geral", "Ainda não há etapas suficientes concluídas para a visão geral.")
        return
    alturas = [len(d) for _, d, _ in paineis]
    fig, axes = plt.subplots(len(paineis), 1, figsize=(9, 1.4 + 0.42 * sum(alturas) + 0.9 * len(paineis)),
                             gridspec_kw={"height_ratios": alturas})
    axes = [axes] if len(paineis) == 1 else list(axes)
    for ax, (t, d, cor) in zip(axes, paineis):
        funil(ax, d, cor)
        ax.set_title(t, fontsize=11)
    fig.suptitle("Do levantamento às evidências", x=0.02, ha="left", fontsize=13,
                 fontweight="bold", color=TEXTO)
    fig.tight_layout()
    tab = pd.DataFrame([{"entidade": t, "passo": r, "n": v, "referencia_da_porcentagem": b}
                        for t, d, _ in paineis for r, v, b in d])
    rel.salvar("geral", fig, "funil", "Do levantamento às evidências",
               "Quantas plantas e quantos compostos passam por cada filtro do pipeline. Cada porcentagem "
               "diz a que passo se refere. A lista final pode passar do GBIF, porque soma a sua lista e "
               "as plantas dos artigos.", tab)
    for t, d, _ in paineis:
        ult, base = d[-1], next((x for x in d if x[0] == d[-1][2]), d[0])
        rel.stat("geral", f"{t.lower()}: {ult[0]}", fmt(ult[1]), f"de {fmt(base[1])} {base[0]}")


# =============================================================================
def main():
    p = argparse.ArgumentParser(description="Gráficos dos resultados do pipeline (pasta graficos/)")
    p.add_argument("--etapas", default="todas",
                   help="lista separada por vírgulas: " + ", ".join(ETAPAS) + " (padrão: todas)")
    p.add_argument("--parcial", action="store_true",
                   help=f"etapa 5 a partir dos *_parcial.csv (gerados por {RODAR} parcial)")
    p.add_argument("--top", type=int, default=25, help="itens nos rankings (padrão: 25)")
    p.add_argument("--formato", choices=["png", "svg", "pdf"], default="png",
                   help="formato dos arquivos de gráfico (padrão: png)")
    p.add_argument("--dpi", type=int, default=150, help="resolução dos PNG (padrão: 150)")
    p.add_argument("--pasta", default="graficos", help="pasta de saída (padrão: graficos)")
    a = p.parse_args()

    escolhidas = ETAPAS if a.etapas == "todas" else [e.strip() for e in a.etapas.split(",") if e.strip()]
    invalidas = [e for e in escolhidas if e not in ETAPAS]
    if invalidas:
        sys.exit(f"Etapa(s) desconhecida(s): {', '.join(invalidas)}. Use: {', '.join(ETAPAS)}")
    top = max(5, a.top)

    pasta = Path(a.pasta)
    if not pasta.is_absolute():
        pasta = PASTA / pasta
    # remove os gráficos antigos das etapas escolhidas (só arquivos que este script cria)
    if pasta.exists():
        padrao = re.compile(r"^(%s)[a-z]_(%s)_" % ("|".join(NUMERO_ETAPA[e] for e in escolhidas),
                                                  "|".join(escolhidas)))
        for f in list(pasta.glob("*.*")) + list((pasta / "dados").glob("*.csv")):
            if f.suffix in (".png", ".svg", ".pdf", ".csv") and padrao.match(f.name):
                f.unlink()

    rel = Relatorio(pasta, a.formato, a.dpi)
    ler = Leitor(a.parcial)
    print(f"Gráficos do pipeline -> {pasta}" + ("  (modo parcial)" if a.parcial else ""))

    bio = None
    if {"bioativos", "geral"} & set(escolhidas):
        bio = ler_bioativos(ler)

    funcoes = {
        "geral": lambda: etapa_geral(rel, ler, bio),
        "downloads": lambda: etapa_downloads(rel, ler, top),
        "gbif": lambda: etapa_gbif(rel, ler, top),
        "plantas": lambda: etapa_plantas(rel, ler, top),
        "bioativos": lambda: etapa_bioativos(rel, ler, top, bio),
        "chembl": lambda: etapa_chembl(rel, ler, top),
        "pubmed": lambda: etapa_pubmed(rel, ler, top, a.parcial),
    }
    for e in ETAPAS:
        if e not in escolhidas:
            continue
        print(f"\n[{e}] {TITULO_ETAPA[e]}")
        try:
            funcoes[e]()
        except Exception as erro:  # noqa: BLE001 - um gráfico com problema não derruba os outros
            plt.close("all")
            rel.aviso(e, f"erro ao gerar os gráficos desta etapa: {type(erro).__name__}: {erro}")
        if e == "pubmed":
            rel.secoes[e]["parcial"] = a.parcial

    # as etapas não refeitas agora continuam no relatório, com os gráficos de antes
    rel.incorporar_anteriores(escolhidas, ler)
    rel.gravar_estado(ler)
    destino = rel.html(ler, a.parcial)
    n = sum(len(rel.secoes[e]["figs"]) for e in escolhidas)
    total = sum(len(s["figs"]) for s in rel.secoes.values())
    print(f"\n{n} gráfico(s) gerado(s) agora; {total} no relatório. Abra: {destino}")


if __name__ == "__main__":
    main()
