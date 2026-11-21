"""
main.py - Orquestrador do pipeline de prospecção de plantas e bioativos

Estrutura do projeto:
  README.md
  config/   input.txt, lista_de_plantas.txt (opcional), credenciais.txt
  mods/     scripts .py (este arquivo e os das etapas)
  (raiz)    bases baixadas (dados_*), caches (cache_*.jsonl) e resultados (*.csv)

Entrada: config/input.txt  (região, lista de plantas, atividades e parâmetros)

Etapas:
  0) downloads  baixar_bases.py                 -> dados_*/ (bases inteiras, uma vez)
  1) gbif       buscar_especies_gbif.py         -> especies_gbif.csv
  2) plantas    montar_lista_plantas.py         -> plantas.csv
                  (GBIF + lista + descoberta em     plantas_conferencia_taxonomica.csv
                   artigos; conferência em Flora    plantas_artigos_evidencias.csv
                   e Funga do Brasil, WFO e GBIF)
  3) bioativos  cruzar_especies_bioativos.py    -> especies_com_compostos_bioativos.csv
  4) chembl     consultar_chembl.py             -> compostos_chembl.csv
                                                   evidencias_chembl.csv
  5) pubmed     consultar_atividades_pubmed.py  -> atividades_plantas.csv
                                                   atividades_compostos.csv
                                                   especies_atividades.csv
                                                   evidencias_pubmed.csv
  6) normalizacao normalizar_compostos.py       -> compostos_normalizados.csv
                  (PubChem + ClassyFire;            normalizacao_ocorrencias.csv
                   dedup por InChIKey; conflitos)   normalizacao_{sinonimos,conflitos,mapa_inchikey}.csv
  7) banco      gerar_banco.py                   -> banco/ (12 CSVs relacionais,
                  (CSVs relacionais + ADMET)         dicionario_dados.csv, datapackage.json,
                                                     ESQUEMA.md)
  8) qualidade  analisar_qualidade.py            -> banco/qualidade/ (completude,
                                                     espaço químico, taxonomia,
                                                     sobreposição, vieses)

Uso:
  python mods/main.py                          # pipeline completo com config/input.txt
  python mods/main.py --input outra_regiao.txt # outro arquivo de entrada
  python mods/main.py --retomar                # pula etapas cuja saída já existe
  python mods/main.py --a-partir-de bioativos  # começa numa etapa específica
  python mods/main.py --somente pubmed         # roda só uma etapa
  python mods/main.py --sem-gbif               # ignora a região: só a lista do input
  python mods/main.py --gbif-chave 0021558-... # usa um download do GBIF já feito
  python mods/main.py --sem-graficos           # não gera os gráficos ao fim das etapas
  python mods/main.py --pular-downloads        # não roda a etapa de downloads
  python mods/main.py --atualizar-bases        # baixa versões novas das bases
  python mods/main.py --somente downloads      # só baixa/confere as bases

Antes de rodar:
  - credenciais em config/credenciais.txt (se faltarem, o pipeline pergunta e abre o arquivo)
  - Ollama rodando com o modelo definido no input.txt ([ollama]) (ex.: ollama pull qwen3.5:35b-a3b)
  - pip install requests pandas tqdm truststore
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

COMANDO = r"mods\rodar.bat" if os.name == "nt" else "mods/rodar.sh"   # lançador (rodado da raiz)
PASTA_MODS = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA_MODS))
import caminhos as C  # noqa: E402

PASTA = C.RAIZ                     # raiz do projeto
RESULTADOS = C.RESULTADOS          # planilhas, banco/ e graficos/ (pasta de trabalho das etapas)

ETAPAS = [
    {"id": "downloads", "script": "baixar_bases.py",
     "descricao": "Download das bases (Flora do Brasil, WFO, COCONUT, NPASS, ChEMBL, Dr. Duke, LOTUS, FooDB)",
     "saida": os.path.join(str(C.DADOS), "bases_baixadas.txt")},
    {"id": "gbif", "script": "buscar_especies_gbif.py",
     "descricao": "Levantamento das plantas da região no GBIF",
     "saida": "especies_gbif.csv"},
    {"id": "plantas", "script": "montar_lista_plantas.py",
     "descricao": "Lista de plantas: sua lista (intacta) + GBIF + plantas de artigos, sem não-plantas e sem duplicatas",
     "saida": "plantas.csv"},
    {"id": "bioativos", "script": "cruzar_especies_bioativos.py",
     "descricao": "Compostos das plantas no COCONUT, NPASS, Dr. Duke, LOTUS e FooDB",
     "saida": "especies_com_compostos_bioativos.csv"},
    {"id": "chembl", "script": "consultar_chembl.py",
     "descricao": "Atividades medidas no ChEMBL (pelo InChIKey), complemento ao PubMed",
     "saida": "compostos_chembl.csv"},
    {"id": "pubmed", "script": "consultar_atividades_pubmed.py",
     "descricao": "Atividades relatadas no PubMed, filtradas pelo modelo (Ollama)",
     "saida": "especies_atividades.csv"},
    {"id": "normalizacao", "script": "normalizar_compostos.py",
     "descricao": "Normaliza identificadores (PubChem), classifica (ClassyFire) e "
                  "deduplica por InChIKey, com rastreabilidade e conflitos",
     "saida": "compostos_normalizados.csv"},
    {"id": "banco", "script": "gerar_banco.py",
     "descricao": "CSVs relacionais interligados por InChIKey + perfil ADMET (RDKit), "
                  "com dicionário de dados e datapackage.json",
     "saida": "banco_compostos.csv"},
    {"id": "qualidade", "script": "analisar_qualidade.py",
     "descricao": "Qualidade e cobertura: completude, espaço químico, taxonomia, "
                  "sobreposição entre bases e vieses de curadoria",
     "saida": os.path.join("banco", "qualidade", "completude_campos.csv")},
]


def duracao(seg: float) -> str:
    m, s = divmod(int(seg), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s" if m else f"{s}s"


def validar_input(caminho: Path):
    os.environ["PIPELINE_INPUT"] = str(caminho)
    sys.path.insert(0, str(PASTA_MODS))
    from config_pipeline import geometria_da_regiao, ler_input
    try:
        dados = ler_input(caminho)
        geo = geometria_da_regiao(dados)
    except (FileNotFoundError, ValueError) as e:
        sys.exit(f"Problema no arquivo de entrada:\n  {e}")
    import credenciais
    print(f"Sistema: {credenciais.sistema()}")
    print("Credenciais: " + credenciais.resumo(dados["config"]["pubmed"].get("ncbi_api_key", ""),
                                              dados["config"]["artigos"].get("openalex_api_key", "")))
    print(f"Entrada: {caminho}")
    print(f"  Região: {geo['descricao']}"
          + (f"; só registros de {', '.join(dados['paises'])}" if dados.get("paises") else ""))
    amostra = ", ".join(dados["taxons"][:10]) + (" ..." if len(dados["taxons"]) > 10 else "")
    print(f"  Táxons do usuário ({len(dados['taxons'])}, de {dados['fonte_taxons']}): "
          f"{amostra or '(nenhum)'}")


def rodar(etapa: dict) -> float:
    print(f"\n{'=' * 70}\nETAPA [{etapa['id']}]: {etapa['descricao']}\n"
          f"Script: {etapa['script']}\n{'=' * 70}\n")
    inicio = time.time()
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")          # Windows: UTF-8 em arquivos e na tela
    env.setdefault("PYTHONUNBUFFERED", "1")
    r = subprocess.run([sys.executable, str(PASTA_MODS / etapa["script"])],
                       cwd=str(RESULTADOS), env=env)
    tempo = time.time() - inicio
    if r.returncode != 0:
        print(f"\nERRO: a etapa '{etapa['id']}' falhou (código {r.returncode}) "
              f"após {duracao(tempo)}.\nCorrija e retome com: "
              f"{COMANDO} --a-partir-de {etapa['id']}")
        sys.exit(r.returncode)
    print(f"\nEtapa '{etapa['id']}' concluída em {duracao(tempo)}.")
    return tempo


ETAPAS_COM_GRAFICOS = {"plantas", "bioativos", "chembl", "pubmed"}
GRAFICOS = PASTA_MODS / "graficos.py"


def gerar_graficos(etapa_id: str) -> None:
    """Gráficos da etapa que acabou de terminar (e da visão geral), com o
    graficos.py da raiz do projeto. Nunca interrompe o pipeline: um erro aqui
    vira só um aviso."""
    if not GRAFICOS.exists():
        return
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    try:
        sem_mpl = subprocess.run([sys.executable, "-c", "import matplotlib"], cwd=str(PASTA),
                                 env=env, capture_output=True).returncode != 0
    except OSError:
        return
    if sem_mpl:
        instalador = r"mods\instalar.bat" if os.name == "nt" else "mods/instalar.sh"
        print(f"\nAVISO: gráficos da etapa '{etapa_id}' não gerados - falta o matplotlib. "
              f"Rode {instalador} de novo (ou --sem-graficos para não ver este aviso).")
        return
    print(f"\n--- Gráficos da etapa '{etapa_id}' (resultados/graficos/relatorio.html) ---")
    inicio = time.time()
    r = subprocess.run([sys.executable, str(GRAFICOS), "--etapas", f"{etapa_id},geral"],
                       cwd=str(RESULTADOS), env=env)
    if r.returncode != 0:
        print(f"AVISO: os gráficos da etapa '{etapa_id}' falharam (código {r.returncode}); "
              "o pipeline segue. Para tentar de novo: "
              + (r"mods\graficos.bat" if os.name == "nt" else "mods/graficos.sh")
              + f" --etapas {etapa_id},geral")
    else:
        print(f"Gráficos prontos em {duracao(time.time() - inicio)}.")


def resumo(tempos: dict):
    print(f"\n{'=' * 70}\nRESUMO\n{'=' * 70}")
    for e in ETAPAS:
        caminho = RESULTADOS / e["saida"]
        if e["id"] not in tempos:
            status = "não executada nesta rodada"
        elif caminho.exists():
            with open(caminho, encoding="utf-8-sig") as f:
                n = max(sum(1 for _ in f) - 1, 0)
            status = f"{e['saida']} ({n} linhas) [{duracao(tempos[e['id']])}]"
        else:
            status = "executada, mas sem arquivo de saída"
        print(f"  [{e['id']:9}] {status}")
    if tempos:
        print(f"\nTempo total: {duracao(sum(tempos.values()))}")


def gbif_sem_chaves(caminho: Path) -> bool:
    """True se o especies_gbif.csv existe, tem linhas e nenhuma speciesKey."""
    import csv
    if not caminho.exists():
        return False
    try:
        with open(caminho, encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f)
            if "speciesKey" not in (leitor.fieldnames or []):
                return False
            linhas = 0
            for linha in leitor:
                linhas += 1
                if (linha.get("speciesKey") or "").strip():
                    return False
            return linhas > 0
    except (OSError, csv.Error):
        return False


def main():
    ids = [e["id"] for e in ETAPAS]
    p = argparse.ArgumentParser(description="Pipeline de prospecção de plantas e bioativos")
    p.add_argument("--input", default="config/input.txt",
                   help="arquivo de entrada (padrão: config/input.txt)")
    p.add_argument("--retomar", action="store_true", help="pula etapas cuja saída já existe")
    p.add_argument("--a-partir-de", dest="a_partir_de", choices=ids)
    p.add_argument("--somente", choices=ids)
    p.add_argument("--pular-downloads", action="store_true",
                   help="não roda a etapa de downloads (bases já baixadas)")
    p.add_argument("--atualizar-bases", action="store_true",
                   help="na etapa de downloads, procura versões novas e baixa de novo")
    p.add_argument("--sem-gbif", action="store_true",
                   help="não levanta a região no GBIF; usa só a lista do input.txt")
    p.add_argument("--sem-graficos", dest="sem_graficos", action="store_true",
                   help="não gera os gráficos ao fim das etapas (já é o padrão)")
    p.add_argument("--com-graficos", dest="com_graficos", action="store_true",
                   help="gera os gráficos (graficos.py) ao fim das etapas plantas, bioativos, chembl e "
                        "pubmed (o mesmo que [graficos] automatico = sim no input.txt)")
    p.add_argument("--gbif-chave", dest="gbif_chave", metavar="CHAVE",
                   help="usa este download do GBIF (ex.: 0021558-261023074918325) "
                        "em vez de pedir um novo; vale igual no Windows e no Linux")
    args = p.parse_args()
    if args.gbif_chave:
        os.environ["GBIF_DOWNLOAD_KEY"] = args.gbif_chave.strip()

    caminho = Path(args.input)
    if not caminho.is_absolute():
        # procura: pasta de onde o comando foi chamado (os lançadores a informam
        # em PIPELINE_CWD), pasta atual, raiz do projeto e config/
        bases = [Path(os.environ["PIPELINE_CWD"])] if os.environ.get("PIPELINE_CWD") else []
        bases += [Path.cwd(), PASTA, PASTA / "config"]
        caminho = next((b / caminho for b in bases if (b / caminho).exists()), PASTA / caminho)
    if not caminho.exists() and args.input == "config/input.txt" and (PASTA / "input.txt").exists():
        print("AVISO: usando input.txt da raiz do projeto. Mova-o para a pasta config/.")
        caminho = PASTA / "input.txt"
    validar_input(caminho)

    etapas = ETAPAS
    if args.somente:
        etapas = [e for e in ETAPAS if e["id"] == args.somente]
    elif args.a_partir_de:
        etapas = ETAPAS[ids.index(args.a_partir_de):]
    if args.pular_downloads:
        etapas = [e for e in etapas if e["id"] != "downloads"]
    if args.atualizar_bases:
        os.environ["PIPELINE_ATUALIZAR_BASES"] = "1"
        if not any(e["id"] == "downloads" for e in etapas):
            etapas = [ETAPAS[0]] + etapas
    if args.sem_gbif:
        etapas = [e for e in etapas if e["id"] != "gbif"]
        saida_gbif = RESULTADOS / "especies_gbif.csv"
        if saida_gbif.exists():
            saida_gbif.replace(saida_gbif.with_suffix(".csv.ignorado"))
            print("\n--sem-gbif: especies_gbif.csv renomeado para "
                  "especies_gbif.csv.ignorado")

    # especies_gbif.csv gravado pela v3 não tem speciesKey: com --retomar, as
    # etapas gbif e plantas são refeitas mesmo que as saídas existam
    refazer = set()
    if args.retomar and gbif_sem_chaves(RESULTADOS / "especies_gbif.csv"):
        refazer = {"gbif", "plantas"}
        print("\nAVISO: especies_gbif.csv está sem speciesKey (gerado pela v3) - as etapas "
              "'gbif' e 'plantas' serão refeitas (o download do GBIF já baixado é reaproveitado).")

    from config_pipeline import carregar_config_graficos
    graficos_auto = (args.com_graficos or carregar_config_graficos()["automatico"]) and not args.sem_graficos
    tempos = {}
    for e in etapas:
        forcar = (e["id"] == "downloads" and args.atualizar_bases) or e["id"] in refazer
        if args.retomar and (RESULTADOS / e["saida"]).exists() and not forcar:
            print(f"\n[Pulando '{e['id']}': {e['saida']} já existe (--retomar)]")
            continue
        tempos[e["id"]] = rodar(e)
        if e["id"] in ETAPAS_COM_GRAFICOS and graficos_auto:
            gerar_graficos(e["id"])
    resumo(tempos)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrompido (Ctrl+C ou botão Interromper do painel). O que já foi gravado nos caches "
              f"fica; para continuar: {COMANDO} --a-partir-de <etapa>")
        sys.exit(130)
