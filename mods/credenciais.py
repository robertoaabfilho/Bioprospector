"""
credenciais.py  -  credenciais do pipeline num único arquivo, para qualquer
sistema operacional (Windows, Linux, macOS): config/credenciais.txt

Formato (uma por linha, "CHAVE = valor"; linhas com # são comentários):
    GBIF_USER = seu_usuario
    GBIF_PWD = sua_senha
    GBIF_EMAIL = seu@email
    NCBI_API_KEY =            (opcional)
    OPENALEX_API_KEY =        (opcional)

Também aceita, sem conversão, linhas no formato dos arquivos antigos
("export GBIF_USER=..." do .env do Linux e "set GBIF_USER=..." do .bat do
Windows), aspas e quebras de linha do Windows (CRLF).

Ordem de prioridade: variável de ambiente já definida > config/credenciais.txt
> config/gbif_credenciais.env/.bat (arquivos antigos, ainda lidos).

Funções:
  carregar()         lê o arquivo e preenche as variáveis de ambiente (silencioso)
  resumo()           texto curto para a tela, com valores mascarados
  garantir_gbif()    chamada quando o GBIF precisa de login: se faltar usuário
                     ou senha, pergunta se já configurou; se não, cria/abre o
                     arquivo no editor do sistema e espera você salvar
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "config" / "credenciais.txt"
ANTIGOS = [RAIZ / "config" / "gbif_credenciais.env", RAIZ / "config" / "gbif_credenciais.bat",
           RAIZ / "gbif_credenciais.env", RAIZ / "gbif_credenciais.bat"]
CHAVES = ["GBIF_USER", "GBIF_PWD", "GBIF_EMAIL", "NCBI_API_KEY", "OPENALEX_API_KEY"]
MARCADORES = {"", "seu_usuario", "sua_senha", "seu@email"}   # valores dos modelos antigos

MODELO = """# =============================================================================
# credenciais.txt - credenciais do pipeline (Windows, Linux e macOS)
# =============================================================================
# Preencha depois do "=", sem aspas, e salve o arquivo.
# NÃO compartilhe este arquivo: as senhas ficam em texto puro.
#
# GBIF (obrigatório só quando o pipeline pede um download novo ao GBIF, ou
# seja, na 1ª vez ou quando a região muda). Conta gratuita:
# https://www.gbif.org -> Login -> Register
GBIF_USER =
GBIF_PWD =
GBIF_EMAIL =

# NCBI (opcional, deixa o PubMed/PubChem ~3x mais rápido). Chave gratuita:
# https://www.ncbi.nlm.nih.gov/account/ -> Account settings -> API Key
NCBI_API_KEY =

# OpenAlex (opcional, para a descoberta de plantas em artigos). Chave gratuita:
# https://openalex.org -> criar conta
OPENALEX_API_KEY =
"""


def sistema() -> str:
    s = platform.system()
    return {"Windows": "Windows", "Linux": "Linux", "Darwin": "macOS"}.get(s, s or "?")


def _ler(caminho: Path) -> dict:
    """{CHAVE: valor} de um arquivo de credenciais (novo ou antigo)."""
    try:
        bruto = caminho.read_bytes()
    except OSError:
        return {}
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("cp1252", errors="replace")
    valores = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", "REM ", "rem ", "::", "@")):
            continue
        for prefixo in ("export ", "set ", "SET "):
            if linha.startswith(prefixo):
                linha = linha[len(prefixo):].strip()
        if "=" not in linha:
            continue
        chave, valor = (x.strip() for x in linha.split("=", 1))
        valor = valor.strip().strip('"').strip("'").strip()
        if chave.upper() in CHAVES and valor:
            valores[chave.upper()] = valor
    return valores


def fonte() -> Path | None:
    if ARQUIVO.exists():
        return ARQUIVO
    return next((a for a in ANTIGOS if a.exists()), None)


def carregar() -> dict:
    """Preenche as variáveis de ambiente que ainda não estão definidas.
    Devolve o que foi lido do arquivo."""
    origem = fonte()
    valores = _ler(origem) if origem else {}
    for chave, valor in valores.items():
        if not os.environ.get(chave):
            os.environ[chave] = valor
    return valores


def gbif_ok() -> bool:
    u = (os.environ.get("GBIF_USER") or "").strip()
    p = (os.environ.get("GBIF_PWD") or "").strip()
    return u.lower() not in MARCADORES and p.lower() not in MARCADORES


def _mascarar(v: str) -> str:
    return v[:3] + "***" if len(v) > 4 else "***"


def resumo(ncbi_no_input: str = "", openalex_no_input: str = "") -> str:
    """Situação das credenciais. As chaves do NCBI e do OpenAlex também
    podem estar no input.txt (versões anteriores): passe-as para contar."""
    origem = fonte()
    gbif = ("ok (usuário " + _mascarar(os.environ["GBIF_USER"]) + ")" if gbif_ok()
            else "não configurado (só é pedido se precisar de um download novo)")
    partes = [f"GBIF {gbif}",
              f"NCBI {'ok' if os.environ.get('NCBI_API_KEY') or ncbi_no_input else 'sem chave'}",
              f"OpenAlex {'ok' if os.environ.get('OPENALEX_API_KEY') or openalex_no_input else 'sem chave'}"]
    de = f" (de {origem.relative_to(RAIZ)})" if origem else ""
    return "; ".join(partes) + de


def criar_modelo():
    if not ARQUIVO.exists():
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        # aproveita valores de arquivos antigos (.env/.bat), se houver
        antigo = next((a for a in ANTIGOS if a.exists()), None)
        texto = MODELO
        if antigo:
            for chave, valor in _ler(antigo).items():
                texto = texto.replace(f"\n{chave} =\n", f"\n{chave} = {valor}\n")
        ARQUIVO.write_text(texto, encoding="utf-8")
        try:
            os.chmod(ARQUIVO, 0o600)    # só o dono lê (Linux/macOS)
        except OSError:
            pass


def abrir_no_editor(caminho: Path) -> bool:
    """Abre o arquivo no editor do sistema. True = o editor já foi fechado
    (editor de terminal); False = abriu numa janela à parte (é preciso
    esperar o usuário salvar)."""
    so = sistema()
    try:
        if so == "Windows":
            os.startfile(str(caminho))             # Bloco de Notas (ou o padrão para .txt)
            return False
        if so == "macOS":
            subprocess.Popen(["open", "-t", str(caminho)])
            return False
        grafico = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        if grafico and shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(caminho)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return False
        editor = os.environ.get("EDITOR") or next(
            (e for e in ("nano", "vim", "vi") if shutil.which(e)), None)
        if editor:
            subprocess.call([editor, str(caminho)])  # editor no próprio terminal
            return True
    except OSError:
        pass
    print(f"  Não consegui abrir um editor. Abra e edite à mão: {caminho}")
    return False


def _perguntar(texto: str) -> str:
    try:
        return input(texto).strip().lower()
    except EOFError:
        return ""


def garantir_gbif():
    """Garante usuário e senha do GBIF antes de um pedido de download.
    Encerra o programa com instruções se não for possível obtê-los."""
    carregar()
    if gbif_ok():
        return
    so = sistema()
    print(f"\nO GBIF precisa de login para um download novo. Sistema detectado: {so}.")
    if not sys.stdin.isatty():   # rodando sem terminal (nohup, agendamento): não dá para perguntar
        criar_modelo()
        sys.exit(f"Credenciais do GBIF não configuradas. Preencha {ARQUIVO} e rode de novo.")
    for _ in range(3):
        resp = _perguntar("Você já configurou as credenciais do GBIF? [s/n] ")
        if resp.startswith("s"):
            print(f"  Não encontrei usuário e senha preenchidos em {ARQUIVO}.")
            resp = "n"
        if resp.startswith("n"):
            criar_modelo()
            print(f"  Abrindo {ARQUIVO.relative_to(RAIZ)} - preencha GBIF_USER, GBIF_PWD e "
                  "GBIF_EMAIL (e, se quiser, as chaves do NCBI e do OpenAlex) e salve.")
            if not abrir_no_editor(ARQUIVO):
                _perguntar("  Depois de salvar o arquivo, pressione Enter para continuar... ")
            carregar()
            for chave, valor in _ler(ARQUIVO).items():   # vale o que acabou de salvar
                os.environ[chave] = valor
            if gbif_ok():
                print(f"  Credenciais carregadas: {resumo()}")
                return
            print("  Usuário ou senha do GBIF continuam vazios.")
    sys.exit(f"Sem credenciais do GBIF. Preencha {ARQUIVO} e rode de novo.")


if __name__ == "__main__":
    carregar()
    print(f"Sistema: {sistema()}")
    print(f"Credenciais: {resumo()}")
    if not gbif_ok():
        garantir_gbif()
