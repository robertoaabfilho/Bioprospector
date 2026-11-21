"""
organizar_pasta.py - passa a pasta do pipeline para o formato organizado (uma vez)

    mods/organizar_pasta.sh             (Linux/macOS)   mostra o plano e pede confirmação
    mods\\organizar_pasta.bat           (Windows)
    python mods/organizar_pasta.py --simular    só mostra o plano
    python mods/organizar_pasta.py --sim        executa sem perguntar

Antes (tudo na raiz)                    Depois
  cache_*.jsonl                     ->  cache/
  dados_bioativos/, dados_chembl/…  ->  dados/bioativos/, dados/chembl/…
  bases_baixadas.txt                ->  dados/   (caminhos atualizados)
  *.csv, banco/, graficos/, *.log   ->  resultados/  (logs em resultados/logs/)
  requirements.txt                  ->  mods/
  rodar.sh, painel.py, graficos.py,
  README.md… (cópias antigas: as
  novas já estão em mods/)          ->  _para_apagar/
  *_parcial.csv (refeitos sozinhos
  pelo painel), listas e zips de
  envio                             ->  _para_apagar/

Nada é apagado: o que não é mais necessário vai para _para_apagar/, com um
LEIA-ME.txt explicando cada item. Confira e apague a pasta você mesmo.
Só move arquivos (mesmo disco: instantâneo); não baixa nem refaz nada.
Recusa-se a rodar com o pipeline, a geração de parciais ou o painel abertos.
Pode ser rodado de novo: o que já está no lugar fica como está.
"""
import datetime
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos as C  # noqa: E402
import processos as P  # noqa: E402

RAIZ = C.RAIZ
LIXO = RAIZ / "_para_apagar"

# cópias antigas de arquivos que agora ficam em mods/
CODIGO_ANTIGO = {"rodar.sh", "rodar.bat", "painel.sh", "painel.bat", "painel.py", "graficos.sh", "graficos.bat",
                 "graficos.py", "instalar.sh", "instalar.bat", "diagnostico_leitura.py", "README.md",
                 "EXTENSAO.md"}
# arquivos que não fazem mais falta (com o motivo)
DESCARTAVEIS = {
    "diagnostico_leitura_pendentes.csv": "lista gerada pelo diagnóstico de leitura; o painel refaz",
    "lista_pasta.txt": "lista da pasta feita para a reorganização",
    "codigo_atual.zip": "cópia do código feita para a reorganização",
}


def tamanho(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB".replace(".", ",") if n >= 1e8 else f"{n / 1e6:.1f} MB".replace(".", ",")


def plano() -> tuple[list, list]:
    """[(origem, destino, motivo)] e [nomes deixados como estão]."""
    mover, ficam = [], []
    for item in sorted(RAIZ.iterdir(), key=lambda p: p.name.lower()):
        n = item.name
        if n.startswith(".") or n in ("config", "mods", "dados", "cache", "resultados", "_para_apagar") \
                or n.startswith("Painel do pipeline"):
            continue
        if n.startswith("cache_") and n.endswith((".jsonl", ".json")):
            mover.append((item, C.CACHE / n, "cache"))
        elif n in C.PASTAS_DADOS and item.is_dir():
            mover.append((item, C.DADOS / C.PASTAS_DADOS[n], "base baixada"))
        elif n == "bases_baixadas.txt":
            mover.append((item, C.DADOS / n, "registro das bases"))
        elif n.endswith("_parcial.csv"):
            mover.append((item, LIXO / n, "resultado parcial da etapa 5: o painel refaz ao abrir "
                                          "(ou mods/rodar.sh parcial)"))
        elif n in DESCARTAVEIS:
            mover.append((item, LIXO / n, DESCARTAVEIS[n]))
        elif n in CODIGO_ANTIGO:
            mover.append((item, LIXO / "codigo_antigo" / n, "cópia antiga; a versão nova está em mods/"))
        elif n == "requirements.txt":
            mover.append((item, C.MODS / n, "lista de pacotes (usada pelo instalar)"))
        elif n.endswith((".csv", ".csv.ignorado")) or n in ("banco", "graficos", "diagnostico_pubmed.txt"):
            mover.append((item, C.RESULTADOS / n, "resultado"))
        elif n.endswith((".log", ".out")) or n == "nohup.out":
            mover.append((item, C.LOGS / n, "registro de execução"))
        elif n == "__pycache__":
            mover.append((item, LIXO / "__pycache__", "arquivos temporários do Python"))
        else:
            ficam.append(n)
    return mover, ficam


def atualizar_registro_bases(arq: Path):
    """bases_baixadas.txt: dados_bioativos/... -> dados/bioativos/..."""
    if not arq.exists():
        return
    texto = arq.read_text(encoding="utf-8", errors="replace")
    novo = texto
    for antigo, atual in C.PASTAS_DADOS.items():
        novo = novo.replace(f"\t{antigo}/", f"\tdados/{atual}/").replace(f"\t{antigo}\\", f"\tdados/{atual}/")
        novo = novo.replace(f"\t{antigo}\t", f"\tdados/{atual}\t")
    if novo != texto:
        arq.write_text(novo, encoding="utf-8")


def ocultar_venv_windows():
    if not P.NO_WINDOWS:
        return
    for v in (".venv", ".venv-win", ".venv-linux"):
        if (RAIZ / v).is_dir():
            subprocess.run(["attrib", "+h", str(RAIZ / v)], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    simular = "--simular" in sys.argv
    sem_perguntar = "--sim" in sys.argv
    print(f"Pasta do projeto: {RAIZ}\n")

    rodando = [p for p in P.processos_do_projeto(RAIZ) if p["tipo"] in
               ("pipeline", "parcial", "diagnostico", "painel", "graficos")]
    if rodando and not simular:
        print("Há programas do pipeline abertos nesta pasta:")
        for p in rodando:
            print(f"  [{p['tipo']}] pid {p['pid']}: {p['cmd'][:110]}")
        sys.exit("\nFeche-os antes (pipeline: botão Interromper do painel ou Ctrl+C; painel: Ctrl+C ou "
                 "Configurações -> Fechar o painel) e rode de novo. Mover arquivos em uso quebraria a rodada.")

    mover, ficam = plano()
    if not mover:
        print("Nada a mover: a pasta já está organizada.")
    grupos = {}
    for o, d, motivo in mover:
        grupos.setdefault(d.parent if d.parent != LIXO / "codigo_antigo" else LIXO, []).append((o, d, motivo))
    total_lixo = 0
    for destino, itens in grupos.items():
        rel = destino.relative_to(RAIZ) if destino.is_relative_to(RAIZ) else destino
        print(f"-> {rel}/")
        for o, d, motivo in itens:
            t = tamanho(o)
            if d.is_relative_to(LIXO):
                total_lixo += t
            nome = o.name if o.name == d.name or d.is_relative_to(LIXO) else f"{o.name} -> {d.name}"
            print(f"     {nome:42} {gb(t):>9}   {motivo}")
    if ficam:
        print("\nFicam onde estão (não reconheci; confira):")
        for n in ficam:
            print(f"     {n}")
    if total_lixo:
        print(f"\nEm _para_apagar/: {gb(total_lixo)} que podem ser apagados depois que você conferir.")
    if simular or not mover:
        return
    if not sem_perguntar:
        try:
            resp = input("\nMover agora? [s/n] ").strip().lower()
        except EOFError:
            resp = ""
        if not resp.startswith("s"):
            sys.exit("Nada foi movido.")

    C.criar_pastas()
    C.LOGS.mkdir(parents=True, exist_ok=True)
    registro = []
    for o, d, motivo in mover:
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():   # já existe no destino: guarda a cópia antiga de lado, sem sobrescrever
            alt = LIXO / "conflitos" / o.name
            alt.parent.mkdir(parents=True, exist_ok=True)
            if alt.exists():
                alt = alt.with_name(f"{o.name}.{datetime.datetime.now():%Y%m%d%H%M%S}")
            if o.name == "requirements.txt" and d.parent == C.MODS:
                shutil.move(str(d), str(alt))       # o requirements.txt do usuário vale mais
            else:
                d = alt
                motivo = f"já existia em {d.parent.name}/; esta é a cópia que estava na raiz"
        shutil.move(str(o), str(d))
        registro.append((o.name, d, motivo))
    atualizar_registro_bases(C.DADOS / "bases_baixadas.txt")
    ocultar_venv_windows()
    for sh in C.MODS.glob("*.sh"):
        try:
            sh.chmod(sh.stat().st_mode | 0o111)
        except OSError:
            pass

    if LIXO.exists():
        leia = LIXO / "LEIA-ME.txt"
        linhas = [f"Itens tirados da pasta do pipeline em {datetime.datetime.now():%Y-%m-%d %H:%M} "
                  "pelo organizar_pasta.py.", "Nenhum é necessário para o pipeline nem para o painel.",
                  "Confira e apague esta pasta quando quiser.", ""]
        for nome, d, motivo in registro:
            if d.is_relative_to(LIXO):
                linhas.append(f"{str(d.relative_to(LIXO)):55} {motivo}")
        with open(leia, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas) + "\n\n")
    print(f"\nPronto: {len(registro)} item(ns) movido(s).")
    print("Daqui em diante, da pasta do projeto: "
          + (r"mods\rodar.bat, mods\painel.bat" if P.NO_WINDOWS else "mods/rodar.sh, mods/painel.sh")
          + " (ou o ícone do painel; para criá-lo: "
          + (r"mods\painel.bat atalho" if P.NO_WINDOWS else "mods/painel.sh atalho") + ").")
    if LIXO.exists():
        print(f"Confira {LIXO.name}/LEIA-ME.txt e apague a pasta {LIXO.name}/ quando quiser.")


if __name__ == "__main__":
    main()
