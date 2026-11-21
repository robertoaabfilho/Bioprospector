"""
processos.py - acha e interrompe os processos do pipeline desta pasta

Usado pelo painel (aba Rodar o pipeline) e pelo organizar_pasta.py. Funciona
no Linux (lê /proc), no macOS (ps) e no Windows (PowerShell/CIM), sem pacotes
extras.

    processos_do_projeto()          -> [{"pid", "tipo", "cmd", "script"}]
    interromper(pid)                -> como Ctrl+C (Linux/macOS); no Windows, encerra
"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import caminhos as C

NO_WINDOWS = os.name == "nt"

# programas do pipeline, por tipo
SCRIPTS_ETAPAS = {"main.py", "baixar_bases.py", "buscar_especies_gbif.py", "montar_lista_plantas.py",
                  "cruzar_especies_bioativos.py", "consultar_chembl.py", "consultar_atividades_pubmed.py",
                  "normalizar_compostos.py", "gerar_banco.py", "analisar_qualidade.py"}
OUTROS = {"diagnostico_leitura.py": "diagnostico", "diagnostico_pubmed.py": "diagnostico",
          "graficos.py": "graficos", "config_pipeline.py": "config"}


def _sob(caminho: str, raiz: Path) -> bool:
    try:
        return Path(caminho).resolve().is_relative_to(raiz)
    except (OSError, ValueError):
        return False


def _classificar(args: list[str], cwd: str | None, raiz: Path) -> dict | None:
    """Tipo do processo, se for deste projeto: pipeline, parcial, diagnostico,
    graficos, config ou painel. None se não for."""
    if not args:
        return None
    exe = os.path.basename(args[0]).lower()
    if "python" not in exe and not exe.startswith("py"):
        return None
    for i, a in enumerate(args[1:], 1):
        nome = os.path.basename(a.replace("\\", "/"))
        if nome == "painel.py" and "streamlit" in " ".join(args[:i]).lower():
            tipo = "painel"
        elif nome in SCRIPTS_ETAPAS:
            tipo = "parcial" if "--parcial" in args else "pipeline"
        elif nome in OUTROS:
            tipo = OUTROS[nome]
        else:
            continue
        # é deste projeto? caminho absoluto dentro da pasta, ou relativo com a
        # pasta de trabalho dentro dela (sem pasta de trabalho conhecida, como
        # no Windows, um caminho relativo "mods\\main.py" conta como deste projeto)
        if os.path.isabs(a):
            meu = _sob(a, raiz)
        elif cwd:
            meu = _sob(os.path.join(cwd, a), raiz)
        else:
            meu = a.replace("\\", "/").startswith("mods/")
        if meu:
            return {"tipo": tipo, "script": nome}
        return None
    return None


def _linux(raiz: Path) -> list[dict]:
    saida = []
    for d in os.listdir("/proc"):
        if not d.isdigit() or int(d) == os.getpid():
            continue
        try:
            with open(f"/proc/{d}/cmdline", "rb") as f:
                args = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        try:
            cwd = os.readlink(f"/proc/{d}/cwd")
        except OSError:
            cwd = None
        c = _classificar(args, cwd, raiz)
        if c:
            saida.append({"pid": int(d), "cmd": " ".join(args), **c})
    return saida


def _ps(raiz: Path) -> list[dict]:
    try:
        r = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    saida = []
    for linha in r.stdout.splitlines():
        partes = linha.strip().split(None, 1)
        if len(partes) < 2 or int(partes[0]) == os.getpid():
            continue
        args = partes[1].split()
        c = _classificar(args, None, raiz)
        if c:
            saida.append({"pid": int(partes[0]), "cmd": partes[1], **c})
    return saida


def _windows(raiz: Path) -> list[dict]:
    comando = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%' or Name like 'py.exe'\" | "
               "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True,
                           timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dados = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(dados, dict):
        dados = [dados]
    saida = []
    for p in dados:
        cmd = p.get("CommandLine") or ""
        pid = int(p.get("ProcessId") or 0)
        if not cmd or pid == os.getpid():
            continue
        import shlex
        try:
            args = shlex.split(cmd, posix=False)
        except ValueError:
            args = cmd.split()
        args = [a.strip('"') for a in args]
        c = _classificar(args, None, raiz)
        if c:
            saida.append({"pid": pid, "cmd": cmd, **c})
    return saida


def processos_do_projeto(raiz: Path | None = None) -> list[dict]:
    raiz = Path(raiz or C.RAIZ).resolve()
    if NO_WINDOWS:
        return _windows(raiz)
    if os.path.isdir("/proc"):
        return _linux(raiz)
    return _ps(raiz)


def vivo(pid: int) -> bool:
    if not pid:
        return False
    if NO_WINDOWS:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
        if not h:
            return False
        codigo = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(codigo))
        ctypes.windll.kernel32.CloseHandle(h)
        return codigo.value == 259   # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # processo zumbi (já terminou, aguardando o pai) conta como encerrado
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def interromper(pid: int, forcar: bool = False) -> str:
    """Linux/macOS: SIGINT para o grupo do processo (o mesmo que Ctrl+C no
    terminal: a etapa recebe KeyboardInterrupt e para); com forcar, SIGKILL.
    Windows: não há como mandar Ctrl+C para um processo sem console - encerra
    a árvore de processos (taskkill /T /F)."""
    if NO_WINDOWS:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "encerrado" if r.returncode == 0 else (r.stderr or r.stdout).strip()
    sinal = signal.SIGKILL if forcar else signal.SIGINT
    try:
        os.killpg(os.getpgid(pid), sinal)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sinal)
        except ProcessLookupError:
            return "já tinha terminado"
    return "sinal enviado"


def iniciar(args: list[str], log_path: Path, cwd: Path, env_extra: dict | None = None) -> subprocess.Popen:
    """Inicia um processo separado do painel (continua se o painel fechar),
    com a saída num arquivo de registro."""
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", **(env_extra or {}))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "w", encoding="utf-8", errors="replace")
    kw = {}
    if NO_WINDOWS:
        kw["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
    else:
        kw["start_new_session"] = True     # grupo próprio: Ctrl+C no painel não o atinge
    try:
        return subprocess.Popen(args, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, env=env, **kw)
    finally:
        log.close()   # o processo filho mantém a sua cópia


# ---- Ollama: pedidos simultâneos --------------------------------------------
def ollama_bin() -> str | None:
    """Caminho do executável do Ollama: o do PATH ou, se não estiver no PATH,
    o local padrão de instalação (Windows: %LOCALAPPDATA%\\Programs\\Ollama)."""
    import shutil
    b = shutil.which("ollama")
    if b:
        return b
    for c in ([Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"]
              if NO_WINDOWS else [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"),
                                  Path.home() / ".local" / "bin" / "ollama",
                                  Path("/opt/homebrew/bin/ollama"),
                                  Path("/Applications/Ollama.app/Contents/Resources/ollama")]):
        if c.is_file():
            return str(c)
    return None


def env_ollama(paralelo) -> dict:
    """Variáveis para iniciar o `ollama serve`: OLLAMA_NUM_PARALLEL igual ao
    [ollama] paralelo do input.txt, para os pedidos simultâneos do pipeline
    não ficarem na fila. Se a variável já estiver no ambiente, ela vale."""
    if os.environ.get("OLLAMA_NUM_PARALLEL"):
        return {}
    try:
        n = max(1, int(paralelo))
    except (TypeError, ValueError):
        n = 4
    return {"OLLAMA_NUM_PARALLEL": str(n)}


def paralelo_do_ollama() -> int | None:
    """Quantos pedidos simultâneos o `ollama serve` em execução aceita, lido do
    ambiente do processo (só Linux, e só se ele for do mesmo usuário). None se
    não der para saber (Windows/macOS, serviço de outro usuário...)."""
    if NO_WINDOWS or not Path("/proc").is_dir():
        return None
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            args = (d / "cmdline").read_bytes().split(b"\0")
            if len(args) < 2 or not args[0].endswith(b"ollama") or args[1] != b"serve":
                continue
            env = dict(x.split(b"=", 1) for x in (d / "environ").read_bytes().split(b"\0") if b"=" in x)
        except OSError:
            continue
        try:
            return max(1, int(env.get(b"OLLAMA_NUM_PARALLEL", b"1") or 1))
        except ValueError:
            return 1
    return None


if __name__ == "__main__":
    for p in processos_do_projeto():
        print(p["pid"], p["tipo"], p["cmd"][:150])
    sys.exit(0)
