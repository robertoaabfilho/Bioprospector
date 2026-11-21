"""
abrir_painel.py - abre o painel sem terminal (usado pelos ícones)

    python mods/abrir_painel.py            abre (inicia o painel em segundo plano, se preciso)
    python mods/abrir_painel.py atalho     cria os ícones (Linux: menu e área de trabalho;
                                           Windows: atalho na pasta e na área de trabalho)

Se o painel já estiver aberto, só abre o navegador nele (não cria uma segunda
cópia). Senão, inicia o painel em segundo plano, sem janela, com o registro em
resultados/logs/painel.log, espera ele responder e abre o navegador. Para
fechar o painel: Configurações -> Fechar o painel.
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos as C  # noqa: E402

NO_WINDOWS = os.name == "nt"
ARQ_PORTA = C.LOGS / "painel.porta"          # porta do painel aberto por este projeto
NOME = "Painel do pipeline"
ICONE_PNG = C.MODS / "icone_painel.png"
ICONE_ICO = C.MODS / "icone_painel.ico"


def responde(porta: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{porta}/_stcore/health", timeout=2) as r:
            return r.read().strip() == b"ok"
    except OSError:
        return False


def porta_livre(porta: int) -> bool:
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def abrir():
    try:
        porta = int(ARQ_PORTA.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        porta = 0
    if porta and responde(porta):
        webbrowser.open(f"http://localhost:{porta}")
        return
    porta = next((p for p in range(8501, 8521) if porta_livre(p)), 8501)
    C.LOGS.mkdir(parents=True, exist_ok=True)
    log = open(C.LOGS / "painel.log", "w", encoding="utf-8", errors="replace")
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    kw = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
          if NO_WINDOWS else {"start_new_session": True})
    subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(C.MODS / "painel.py"),
                      "--server.port", str(porta), "--server.headless", "true",
                      "--browser.gatherUsageStats", "false"],
                     cwd=str(C.RAIZ), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     env=env, **kw)
    ARQ_PORTA.write_text(str(porta))
    for _ in range(120):          # até 60 s
        if responde(porta):
            break
        time.sleep(0.5)
    webbrowser.open(f"http://localhost:{porta}")


def _area_de_trabalho() -> Path | None:
    if NO_WINDOWS:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                               capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            p = Path(r.stdout.strip())
            return p if p.is_dir() else None
        except OSError:
            return None
    try:
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
        p = Path(r.stdout.strip())
        if p.is_dir() and p != Path.home():
            return p
    except OSError:
        pass
    for nome in ("Área de Trabalho", "Área de trabalho", "Desktop"):
        if (Path.home() / nome).is_dir():
            return Path.home() / nome
    return None


def atalho_linux():
    # o Python de agora (o do terminal, com conda/venv ativos) fica gravado no
    # ícone: a sessão gráfica não lê o .bashrc e poderia achar outro Python
    texto = "\n".join([
        "[Desktop Entry]", "Type=Application", f"Name={NOME}",
        "Comment=Painel dos resultados do pipeline de prospecção (abre no navegador)",
        f'Exec="{sys.executable}" "{C.MODS / "abrir_painel.py"}"', f"Path={C.RAIZ}", f"Icon={ICONE_PNG}",
        "Terminal=false",
        "Categories=Science;Education;", "StartupNotify=false", ""])
    destinos = [Path.home() / ".local" / "share" / "applications" / "painel-pipeline-prospeccao.desktop"]
    mesa = _area_de_trabalho()
    if mesa:
        destinos.append(mesa / f"{NOME}.desktop")
    for d in destinos:
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(texto, encoding="utf-8")
        d.chmod(0o755)
        # GNOME: marca como confiável (senão pede "Permitir iniciar")
        subprocess.run(["gio", "set", str(d), "metadata::trusted", "true"], capture_output=True)
        print(f"  criado: {d}")
    # na pasta do projeto: um executável pequeno (o gerenciador de arquivos do
    # Ubuntu não abre .desktop nem scripts com dois cliques, mas abre programas)
    import platform
    import shutil
    (C.MODS / ".python_painel").write_text(sys.executable + "\n", encoding="utf-8")
    arq = {"x86_64": "painel_linux_x86_64", "amd64": "painel_linux_x86_64",
           "aarch64": "painel_linux_aarch64", "arm64": "painel_linux_aarch64"}.get(platform.machine().lower())
    antigo = C.RAIZ / f"{NOME} (Linux).desktop"
    if antigo.exists():
        antigo.unlink()
    if arq and (C.MODS / arq).exists():
        lanc = C.RAIZ / f"{NOME} (Linux)"
        shutil.copy2(C.MODS / arq, lanc)
        lanc.chmod(0o755)
        subprocess.run(["gio", "set", str(lanc), "metadata::custom-icon", ICONE_PNG.as_uri()], capture_output=True)
        print(f"  criado: {lanc}  (dois cliques abrem o painel)")
    else:
        print(f"  (sem lançador pronto para este processador: {platform.machine()}; use o menu de aplicativos)")
    print("\nNo GNOME (Ubuntu), se o ícone da área de trabalho aparecer com um X ou pedir permissão:\n"
          "  clique com o botão direito nele -> \"Permitir iniciar\".")


def atalho_windows():
    # pythonw.exe: o mesmo Python, sem janela de console
    exe = Path(sys.executable)
    if (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    destinos = [C.RAIZ / f"{NOME} (Windows).lnk"]
    mesa = _area_de_trabalho()
    if mesa:
        destinos.append(mesa / f"{NOME}.lnk")
    for d in destinos:
        ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{d}'); "
              f"$s.TargetPath = '{exe}'; $s.Arguments = '\"{C.MODS / "abrir_painel.py"}\"'; "
              f"$s.WindowStyle = 7; "
              f"$s.WorkingDirectory = '{C.RAIZ}'; $s.IconLocation = '{ICONE_ICO}'; "
              f"$s.Description = 'Painel dos resultados do pipeline de prospecção'; $s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        print(f"  {'criado' if r.returncode == 0 else 'FALHOU'}: {d}" + ("" if r.returncode == 0 else
                                                                         f"\n    {r.stderr.strip()[:300]}"))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "atalho":
        print(f"Criando os ícones do {NOME}:")
        atalho_windows() if NO_WINDOWS else atalho_linux()
        print("\nPronto. O ícone abre o painel no navegador; para fechar o painel: "
              "Configurações -> Fechar o painel.")
    else:
        abrir()
