"""
baixar_bases.py  -  ETAPA 0 ("downloads")

Baixa, de uma vez e antes das etapas longas, as bases usadas inteiras pelo
pipeline:

  Flora e Funga do Brasil  lista oficial de plantas (conferência de nomes)   dados/flora_brasil/
  World Flora Online       lista mundial de plantas (conferência de nomes)   dados/wfo/
  WCVP (Kew)               plantas vasculares do mundo (conferência)        dados/wcvp/
  COCONUT                  produtos naturais e organismos de origem          dados/bioativos/
  NPASS                    compostos, espécies, atividades e alvos           dados/bioativos/
  Dr. Duke (USDA)          composto x planta x parte x teor; atividades      dados/bioativos/
  LOTUS                    composto x organismo x referência (DOI)           dados/bioativos/
  FooDB                    compostos de alimentos, com teor                  dados/bioativos/foodb/
  ChEMBL (estruturas)      InChIKey de todas as moléculas do ChEMBL          dados/chembl/

Só baixa o que ainda não existe: rodar de novo, com tudo baixado, leva
segundos. Bases desligadas no input.txt ([taxonomia], [chembl]) são puladas.

Para ATUALIZAR as bases (versões novas):  python mods/main.py --atualizar-bases
  - COCONUT: baixa de novo só se houver versão nova;
  - Flora, WFO, NPASS e ChEMBL: baixa de novo e descarta as consultas
    guardadas que dependiam da versão anterior.

O GBIF não entra aqui: o download dele depende da região do input.txt e é
feito na etapa "gbif".
"""

import datetime
import os

import caminhos as _C

from config_pipeline import COMANDO, apagar_pasta, trocar
import sys

ATUALIZAR = os.environ.get("PIPELINE_ATUALIZAR_BASES") == "1"
MARCADOR = _C.dados("bases_baixadas.txt")


def _relativo(caminho: str) -> str:
    """Caminho a partir da raiz do projeto, com "/" (vale no Linux e no Windows)."""
    try:
        return os.path.relpath(caminho, _C.RAIZ).replace(os.sep, "/")
    except ValueError:
        return str(caminho)


def tamanho(caminho: str) -> str:
    if os.path.isdir(caminho):
        total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(caminho) for f in fs)
    elif os.path.exists(caminho):
        total = os.path.getsize(caminho)
    else:
        return "-"
    return f"{total / 1e6:,.0f} MB".replace(",", ".")


def _apagar(caminho):
    if os.path.isdir(caminho):
        apagar_pasta(caminho)
    elif os.path.exists(caminho):
        os.remove(caminho)


def substituir(caminhos: list, baixar) -> None:
    """Troca SEGURA para atualização: guarda a versão atual de lado
    (*.anterior), baixa a nova e só então descarta a antiga. Se o download
    falhar, a versão antiga volta ao lugar e o erro é repassado."""
    guardados = []
    for c in caminhos:
        if os.path.exists(c):
            _apagar(c + ".anterior")
            trocar(c, c + ".anterior")
            guardados.append(c)
    try:
        if baixar() is False:
            raise RuntimeError("download falhou")
    except BaseException:
        for c in caminhos:
            if c in guardados:
                _apagar(c)
                trocar(c + ".anterior", c)
        raise
    for c in guardados:
        _apagar(c + ".anterior")


def main():
    if ATUALIZAR:
        print("--atualizar-bases: procurando versões novas e baixando de novo "
              "(a versão atual só é descartada se a nova chegar inteira).\n")
    resultados = []   # (base, caminho, ok, mensagem)

    # --- listas taxonômicas -------------------------------------------------
    import taxonomia as T
    listas = T.listas_baixadas()
    print("== Listas taxonômicas ==" if listas else
          "Listas taxonômicas desligadas em [taxonomia] - puladas.")
    for base, lista in listas.items():
        try:
            if ATUALIZAR:
                substituir([lista.zip_path], lambda: T._baixar(lista.url, lista.zip_path, lista.rotulo))
                _apagar(lista.cache_path)   # conferências feitas com a versão anterior
            elif os.path.exists(lista.zip_path) and os.path.getsize(lista.zip_path) > 0:
                print(f"{lista.rotulo}: já baixado")
            else:
                T._baixar(lista.url, lista.zip_path, lista.rotulo)
            resultados.append((lista.rotulo, lista.zip_path, True, ""))
        except Exception as e:
            ainda = os.path.exists(lista.zip_path)
            resultados.append((lista.rotulo, lista.zip_path, ainda,
                               f"atualização falhou, mantida a versão anterior ({e})" if ainda else str(e)))

    # --- COCONUT e NPASS --------------------------------------------------
    print("\n== Bases de produtos naturais ==")
    import cruzar_especies_bioativos as B
    pasta_coconut = os.path.join(B.PASTA_DADOS, "coconut_extraido")
    npass = [B.arquivo_npass(k) for k in B.ARQUIVOS_NPASS]
    try:
        if ATUALIZAR:
            instalada = B.versao_coconut_instalada()
            nova = B.url_coconut()
            if instalada and instalada != nova:
                print(f"COCONUT: versão nova disponível ({os.path.basename(nova)})")
                substituir(B.arquivos_coconut(), B.preparar_bases)
            else:
                print("COCONUT: já está na versão mais recente")
            print("NPASS: baixando de novo (o NPASS não informa versão)")
            substituir(npass, B.preparar_bases)
        else:
            B.preparar_bases()
        resultados.append(("COCONUT", pasta_coconut, True, ""))
        resultados.append(("NPASS", os.path.dirname(npass[0]), True, ""))
    except Exception as e:
        ainda = os.path.exists(pasta_coconut) and all(os.path.exists(n) for n in npass)
        resultados.append(("COCONUT / NPASS", B.PASTA_DADOS, ainda,
                           f"atualização falhou, mantida a versão anterior ({e})" if ainda else str(e)))

    # --- bases complementares de produtos naturais (Dr. Duke, LOTUS, FooDB) ---
    import duke as D
    import foodb as F
    import lotus as L
    for chave, modulo, rotulo, local in [("usar_duke", D, "Dr. Duke", D.PASTA_EXTRAIDA),
                                         ("usar_lotus", L, "LOTUS", L.ARQUIVO),
                                         ("usar_foodb", F, "FooDB", F.PASTA)]:
        if not D.cfg().get(chave):
            print(f"{rotulo}: desligado em [bioativos] - pulado.")
            continue
        try:
            if ATUALIZAR:
                print(f"{rotulo}: baixando de novo")
                substituir(modulo.arquivos(), modulo.baixar)
            else:
                modulo.baixar()
            resultados.append((rotulo, local, True, ""))
        except Exception as e:
            ainda = os.path.exists(local)
            resultados.append((rotulo, local, ainda,
                               f"atualização falhou, mantida a versão anterior ({e})" if ainda else
                               f"download falhou ({e}) - a etapa 'bioativos' segue sem esta base"))

    # --- ChEMBL -------------------------------------------------------------
    print("\n== ChEMBL ==")
    import consultar_chembl as C
    if C.CFG["ativar"]:
        arq = C.ARQUIVO_ESTRUTURAS
        try:
            if ATUALIZAR:
                substituir([arq], lambda: bool(C.baixar_estruturas(C.criar_sessao())))
                for cache in C.CACHES_CHEMBL:      # consultas feitas com a versão anterior
                    _apagar(cache)
            elif os.path.exists(arq) and os.path.getsize(arq) > 0:
                print("ChEMBL: arquivo de estruturas já baixado")
            elif not C.baixar_estruturas(C.criar_sessao()):
                raise RuntimeError("download falhou")
            resultados.append(("ChEMBL (estruturas)", arq, True, ""))
        except Exception as e:
            ainda = os.path.exists(arq)
            resultados.append(("ChEMBL (estruturas)", arq, ainda,
                               f"atualização falhou, mantida a versão anterior ({e})" if ainda else
                               "download falhou - a etapa 'chembl' usará a API (mais lenta)"))
    else:
        print("ChEMBL desligado em [chembl] - pulado.")

    # --- resumo ---------------------------------------------------------------
    print(f"\n{'=' * 70}\nBases do pipeline\n{'=' * 70}")
    for base, caminho, ok, msg in resultados:
        print(f"  [{'OK' if ok else 'FALHOU':6}] {base:24} {tamanho(caminho):>9}  {_relativo(caminho)}"
              + (f"\n           {msg}" if msg else ""))
    with open(MARCADOR, "w", encoding="utf-8") as f:
        f.write(f"Bases verificadas em {datetime.datetime.now():%Y-%m-%d %H:%M}\n")
        for base, caminho, ok, msg in resultados:
            f.write(f"{'OK' if ok else 'FALHOU'}\t{base}\t{_relativo(caminho)}\t{msg}\n")
    opcionais = ("ChEMBL", "Dr. Duke", "LOTUS", "FooDB", "WCVP")
    essenciais = [r for r in resultados if not r[2] and not r[0].startswith(opcionais)]
    if essenciais:
        print("\nAlguma base não pôde ser baixada. Verifique a conexão e rode de novo:\n"
              f"  {COMANDO} --somente downloads")
        os.remove(MARCADOR)   # sem o marcador, o --retomar não pula esta etapa
        sys.exit(1)
    print("\nTudo pronto. Nas próximas rodadas esta etapa só confere os arquivos "
          "(ou pule-a com --pular-downloads).")


if __name__ == "__main__":
    main()
