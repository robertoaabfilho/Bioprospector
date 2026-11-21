"""
quimio.py - Módulo compartilhado (não é executado diretamente) das etapas
"normalizacao", "banco" e "qualidade" (v3.17).

Reúne:
  - Cache em JSONL (uma consulta concluída por linha, gravada na hora);
  - RDKit (opcional, recomendado): leitura e padronização de estruturas,
    InChIKey calculado a partir do SMILES, descritores e alertas (ADMET);
  - PubChem (PUG REST, PUG View e SDQ): identificadores, propriedades,
    sinônimos, vias metabólicas e dados espectrais;
  - ClassyFire (Wishart lab): classificação estrutural pelo InChIKey.

Toda consulta de rede devolve None quando falha (rede/servidor) - o item NÃO
vai para o cache e é refeito na próxima rodada - e um valor vazio ({} / [])
quando a fonte responde que não tem o composto (vai para o cache).
"""

import json
import os
import re
import time

import requests

HEADERS = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/3.17"}
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{}/JSON"
SDQ = "https://pubchem.ncbi.nlm.nih.gov/sdq/sdqagent.cgi"
CLASSYFIRE = "http://classyfire.wishartlab.com"

# propriedades pedidas ao PubChem (nomes de 2025 e os antigos, como alternativa)
PROPRIEDADES = ["InChIKey", "InChI", "SMILES", "ConnectivitySMILES", "MolecularFormula",
                "MolecularWeight", "ExactMass", "MonoisotopicMass", "IUPACName", "Title",
                "XLogP", "TPSA", "HBondDonorCount", "HBondAcceptorCount",
                "RotatableBondCount", "Charge", "HeavyAtomCount", "Complexity"]
PROPRIEDADES_ANTIGAS = [{"SMILES": "IsomericSMILES", "ConnectivitySMILES": "CanonicalSMILES"}
                        .get(p, p) for p in PROPRIEDADES]


def inchikey_valido(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    v = valor.strip().upper()
    if v.startswith("INCHIKEY="):
        v = v[9:]
    return v if RE_INCHIKEY.match(v) else None


def texto(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v != v:      # NaN
        return None
    t = str(v).strip()
    return t if t and t.lower() not in ("nan", "none", "n.a.", "na") else None


# ---------------------------------------------------------------------------
# Cache JSONL
# ---------------------------------------------------------------------------
class Cache:
    """{chave: valor} lido de um .jsonl; .gravar() acrescenta uma linha na hora."""

    def __init__(self, caminho: str):
        self.caminho = caminho
        self.dados = {}
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                for linha in f:
                    try:
                        item = json.loads(linha)
                        self.dados[item["k"]] = item["v"]
                    except (ValueError, KeyError, TypeError):
                        continue
        self._f = None

    def __contains__(self, k):
        return k in self.dados

    def get(self, k, padrao=None):
        return self.dados.get(k, padrao)

    def gravar(self, k, v):
        self.dados[k] = v
        if self._f is None:
            self._f = open(self.caminho, "a", encoding="utf-8")
        self._f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
        self._f.flush()

    def fechar(self):
        if self._f:
            self._f.close()
            self._f = None


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
class Cliente:
    """Sessão HTTP com limite de ritmo e desistência após falhas seguidas
    (o restante fica para a próxima rodada)."""

    def __init__(self, nome: str, intervalo: float = 0.22, max_falhas: int = 15,
                 timeout=(10, 60)):
        self.nome, self.intervalo, self.max_falhas, self.timeout = nome, intervalo, max_falhas, timeout
        self.sessao = requests.Session()
        self.falhas_seguidas = 0
        self.desistiu = False
        self._ultimo = 0.0

    def _esperar(self):
        dt = time.time() - self._ultimo
        if dt < self.intervalo:
            time.sleep(self.intervalo - dt)
        self._ultimo = time.time()

    def pedir(self, metodo: str, url: str, **kw):
        """Response, ou None se falhou (rede, 429, 5xx)."""
        if self.desistiu:
            return None
        self._esperar()
        kw.setdefault("headers", HEADERS)
        kw.setdefault("timeout", self.timeout)
        for tentativa in range(2):
            try:
                r = self.sessao.request(metodo, url, **kw)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code < 500 and r.status_code != 429:
                self.falhas_seguidas = 0
                return r
            time.sleep(1.5 * (tentativa + 1))
        self.falhas_seguidas += 1
        if self.falhas_seguidas >= self.max_falhas:
            self.desistiu = True
            print(f"  {self.nome}: sem resposta em {self.max_falhas} consultas seguidas - "
                  "o restante fica para a próxima rodada desta etapa.")
        return None


def _json(r):
    try:
        return r.json()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# PubChem
# ---------------------------------------------------------------------------
def pubchem_cids_por_inchikey(cli: Cliente, ik: str):
    """[CIDs] para um InChIKey; [] = não está no PubChem; None = falha."""
    r = cli.pedir("GET", f"{PUG}/compound/inchikey/{ik}/cids/JSON")
    if r is None:
        return None
    if r.status_code in (400, 404):
        return []
    d = _json(r) or {}
    return [int(c) for c in d.get("IdentifierList", {}).get("CID", []) if c]


def _normalizar_props(p: dict) -> dict:
    """Unifica os nomes antigos e novos das propriedades do PubChem."""
    saida = dict(p)
    if not saida.get("SMILES") and p.get("IsomericSMILES"):
        saida["SMILES"] = p["IsomericSMILES"]
    if not saida.get("ConnectivitySMILES") and p.get("CanonicalSMILES"):
        saida["ConnectivitySMILES"] = p["CanonicalSMILES"]
    saida.pop("IsomericSMILES", None)
    saida.pop("CanonicalSMILES", None)
    return saida


def pubchem_propriedades(cli: Cliente, cids: list):
    """{CID(str): {propriedades}} de um lote de CIDs; None = falha."""
    for props in (PROPRIEDADES, PROPRIEDADES_ANTIGAS):
        r = cli.pedir("POST", f"{PUG}/compound/cid/property/{','.join(props)}/JSON",
                      data={"cid": ",".join(str(c) for c in cids)}, timeout=(10, 120))
        if r is None:
            return None
        if r.status_code == 400:
            continue
        if r.status_code == 404:
            return {}
        d = _json(r) or {}
        return {str(p.get("CID")): _normalizar_props(p)
                for p in d.get("PropertyTable", {}).get("Properties", [])}
    return {}


def pubchem_sinonimos(cli: Cliente, cids: list):
    """{CID(str): [sinônimos]} de um lote; None = falha."""
    r = cli.pedir("POST", f"{PUG}/compound/cid/synonyms/JSON",
                  data={"cid": ",".join(str(c) for c in cids)}, timeout=(10, 120))
    if r is None:
        return None
    if r.status_code in (400, 404):
        return {}
    d = _json(r) or {}
    return {str(i.get("CID")): i.get("Synonym", [])
            for i in d.get("InformationList", {}).get("Information", [])}


def _textos_valor(valor: dict) -> list:
    if not isinstance(valor, dict):
        return []
    saida = [s.get("String", "") for s in valor.get("StringWithMarkup", []) if s.get("String")]
    if valor.get("Number"):
        unid = valor.get("Unit", "")
        saida.append(" ".join(str(n) for n in valor["Number"]) + (f" {unid}" if unid else ""))
    return saida


def pubchem_espectros(cli: Cliente, cid):
    """Dados espectrais do PubChem (PUG View, seção "Spectral Information"):
    lista de {tipo, subtipo, fonte, id_fonte, url, descricao}. [] = sem dados;
    None = falha."""
    r = cli.pedir("GET", PUG_VIEW.format(cid), params={"heading": "Spectral Information"},
                  timeout=(10, 90))
    if r is None:
        return None
    if r.status_code in (400, 404):
        return []
    d = _json(r) or {}
    registro = d.get("Record", {})
    refs = {ref.get("ReferenceNumber"): ref for ref in registro.get("Reference", [])}
    saida = []

    def percorrer(secao, caminho):
        titulo = secao.get("TOCHeading", "")
        caminho = caminho + [titulo] if titulo else caminho
        infos = secao.get("Information", [])
        # agrupa por referência: um espectro = os campos de uma mesma referência
        por_ref = {}
        for info in infos:
            por_ref.setdefault(info.get("ReferenceNumber"), []).append(info)
        for ref_n, grupo in por_ref.items():
            ref = refs.get(ref_n, {})
            campos = []
            for info in grupo:
                vals = _textos_valor(info.get("Value", {}))
                if vals:
                    nome = info.get("Name", "")
                    campos.append((f"{nome}: " if nome else "") + " | ".join(vals))
            if not campos:
                continue
            caminho_util = [c for c in caminho if c != "Spectral Information"]
            saida.append({
                "tipo": caminho_util[0] if caminho_util else "Spectral Information",
                "subtipo": " > ".join(caminho_util[1:]) or None,
                "fonte": ref.get("SourceName"),
                "id_fonte": ref.get("SourceID"),
                "url": ref.get("URL"),
                "descricao": "; ".join(campos)[:600],
            })
        for sub in secao.get("Section", []):
            percorrer(sub, caminho)

    for s in registro.get("Section", []):
        percorrer(s, [])
    return saida


def pubchem_vias(cli: Cliente, cid):
    """Vias metabólicas/de sinalização que o PubChem associa ao CID (Reactome,
    WikiPathways, KEGG, PlantCyc, PathBank...). [] = nenhuma; None = falha."""
    consulta = {"download": "*", "collection": "pathway",
                "where": {"ands": [{"cid": str(cid)}]}, "order": ["source,asc"],
                "start": 1, "limit": 500}
    r = cli.pedir("GET", SDQ, params={"infmt": "json", "outfmt": "json",
                                      "query": json.dumps(consulta)}, timeout=(10, 90))
    if r is None:
        return None
    if r.status_code in (400, 404):
        return []
    d = _json(r)
    if isinstance(d, dict) and "SDQOutputSet" in d:
        linhas = (d["SDQOutputSet"] or [{}])[0].get("rows", [])
    elif isinstance(d, list):
        linhas = d
    else:
        return []
    saida = []
    for ln in linhas:
        saida.append({"via_id": ln.get("pwacc") or ln.get("externalid"),
                      "via_nome": ln.get("name"),
                      "fonte": ln.get("source"),
                      "categoria": ln.get("category") or ln.get("pwtype"),
                      "organismo": ln.get("taxname"),
                      "url": ln.get("url")})
    return saida


# ---------------------------------------------------------------------------
# ClassyFire
# ---------------------------------------------------------------------------
NIVEIS_CLASSYFIRE = ["kingdom", "superclass", "class", "subclass", "direct_parent"]


def _resumir_classyfire(d: dict) -> dict:
    saida = {}
    for nivel in NIVEIS_CLASSYFIRE:
        v = d.get(nivel)
        saida[nivel] = v.get("name") if isinstance(v, dict) else None
    saida["molecular_framework"] = d.get("molecular_framework")
    saida["alternative_parents"] = "; ".join(
        a.get("name") for a in (d.get("alternative_parents") or [])[:15] if a.get("name")) or None
    saida["chemont_id"] = (d.get("direct_parent") or {}).get("chemont_id") \
        if isinstance(d.get("direct_parent"), dict) else None
    return saida


def classyfire_por_inchikey(cli: Cliente, ik: str):
    """Classificação já calculada no ClassyFire para o InChIKey. {} = não
    classificado lá; None = falha."""
    r = cli.pedir("GET", f"{CLASSYFIRE}/entities/{ik}.json", timeout=(10, 60))
    if r is None:
        return None
    if r.status_code in (400, 404, 422):
        return {}
    d = _json(r)
    if not isinstance(d, dict) or not d.get("kingdom"):
        return {}
    return _resumir_classyfire(d)


def classyfire_submeter(cli: Cliente, itens: list, rotulo="pipeline_prospeccao"):
    """Envia estruturas (lista de (InChIKey, SMILES)) para classificação. Devolve
    o id da consulta, ou None."""
    entrada = "\n".join(f"{ik}\t{smi}" for ik, smi in itens)
    r = cli.pedir("POST", f"{CLASSYFIRE}/queries.json",
                  json={"label": rotulo, "query_input": entrada, "query_type": "STRUCTURE"},
                  headers={**HEADERS, "Accept": "application/json",
                           "Content-Type": "application/json"}, timeout=(10, 120))
    if r is None or r.status_code >= 400:
        return None
    d = _json(r) or {}
    return d.get("id")


def classyfire_resultado(cli: Cliente, consulta_id):
    """(terminou?, {InChIKey: classificação})."""
    r = cli.pedir("GET", f"{CLASSYFIRE}/queries/{consulta_id}.json", timeout=(10, 120))
    if r is None or r.status_code >= 400:
        return False, {}
    d = _json(r) or {}
    feito = str(d.get("classification_status", "")).lower() == "done"
    saida = {}
    for ent in d.get("entities", []) or []:
        ik = inchikey_valido(ent.get("inchikey") or "")
        if not ik:
            ident = str(ent.get("identifier", "")).split("\t")[0]
            ik = inchikey_valido(ident)
        if ik and ent.get("kingdom"):
            saida[ik] = _resumir_classyfire(ent)
    return feito, saida


# ---------------------------------------------------------------------------
# RDKit (opcional)
# ---------------------------------------------------------------------------
try:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Crippen, Descriptors, Lipinski, QED, rdMolDescriptors
    from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
    from rdkit.Chem.MolStandardize import rdMolStandardize
    RDLogger.DisableLog("rdApp.*")
    TEM_RDKIT = True
except ImportError:      # pragma: no cover
    TEM_RDKIT = False

_PADRONIZADORES = {}


def _padronizadores():
    if not _PADRONIZADORES and TEM_RDKIT:
        _PADRONIZADORES["frag"] = rdMolStandardize.LargestFragmentChooser(preferOrganic=True)
        _PADRONIZADORES["uncharger"] = rdMolStandardize.Uncharger()
    return _PADRONIZADORES


def mol(smiles):
    if not TEM_RDKIT or not texto(smiles):
        return None
    try:
        return Chem.MolFromSmiles(smiles.strip())
    except Exception:
        return None


def inchikey_de_mol(m) -> str | None:
    if m is None:
        return None
    try:
        return inchikey_valido(Chem.MolToInchiKey(m))
    except Exception:
        return None


def parental(m):
    """Forma parental: limpeza, maior fragmento orgânico (sem contraíons e
    solventes) e neutralização. Usada para reconhecer sais e formas carregadas
    do mesmo composto."""
    if m is None:
        return None
    try:
        p = _padronizadores()
        m2 = rdMolStandardize.Cleanup(m)
        m2 = p["frag"].choose(m2)
        m2 = p["uncharger"].uncharge(m2)
        return m2
    except Exception:
        return None


def estrutura(smiles) -> dict:
    """{valido, inchikey_calculado, inchikey_parental, smiles_canonico, formula}."""
    m = mol(smiles)
    if m is None:
        return {"valido": False if (TEM_RDKIT and texto(smiles)) else None}
    p = parental(m)
    try:
        formula = rdMolDescriptors.CalcMolFormula(m)
    except Exception:
        formula = None
    return {"valido": True, "inchikey_calculado": inchikey_de_mol(m),
            "inchikey_parental": inchikey_de_mol(p) if p is not None else None,
            "smiles_canonico": Chem.MolToSmiles(m), "formula": formula}


_CATALOGOS = {}


def _catalogo(nome):
    if nome not in _CATALOGOS:
        params = FilterCatalogParams()
        params.AddCatalog(getattr(FilterCatalogParams.FilterCatalogs, nome))
        _CATALOGOS[nome] = FilterCatalog(params)
    return _CATALOGOS[nome]


def _alertas(m, nome) -> str | None:
    try:
        achados = _catalogo(nome).GetMatches(m)
        return "; ".join(sorted({a.GetDescription() for a in achados})) or None
    except Exception:
        return None


PRECISAO = 4
MASSA_PROTON = 1.007276
MASSA_NA = 22.989218


def descritores_admet(smiles) -> dict:
    """Descritores físico-químicos e regras de semelhança a fármaco calculados
    pelo RDKit. São PREVISÕES por regra, não medidas."""
    m = mol(smiles)
    if m is None:
        return {}
    try:
        mw = Descriptors.MolWt(m)
        mono = Descriptors.ExactMolWt(m)
        logp = Crippen.MolLogP(m)
        mr = Crippen.MolMR(m)
        tpsa = rdMolDescriptors.CalcTPSA(m)
        hbd = Lipinski.NumHDonors(m)
        hba = Lipinski.NumHAcceptors(m)
        rot = rdMolDescriptors.CalcNumRotatableBonds(m)
        arom = rdMolDescriptors.CalcNumAromaticRings(m)
        aneis = rdMolDescriptors.CalcNumRings(m)
        pesados = m.GetNumHeavyAtoms()
        fsp3 = rdMolDescriptors.CalcFractionCSP3(m)
        carga = Chem.GetFormalCharge(m)
        estereo = len(Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False))
        qed = QED.qed(m)
    except Exception:
        return {}
    viol_lip = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
    veber = rot <= 10 and tpsa <= 140
    ghose = 160 <= mw <= 480 and -0.4 <= logp <= 5.6 and 40 <= mr <= 130 and 20 <= m.GetNumAtoms() <= 70
    egan = logp <= 5.88 and tpsa <= 131.6
    muegge = (200 <= mw <= 600 and -2 <= logp <= 5 and tpsa <= 150 and aneis <= 7
              and rot <= 15 and hba <= 10 and hbd <= 5)
    return {
        "massa_molecular_rdkit": round(mw, PRECISAO),
        "massa_monoisotopica_rdkit": round(mono, PRECISAO),
        "mz_M+H": round(mono + MASSA_PROTON, PRECISAO) if carga == 0 else None,
        "mz_M+Na": round(mono + MASSA_NA, PRECISAO) if carga == 0 else None,
        "mz_M-H": round(mono - MASSA_PROTON, PRECISAO) if carga == 0 else None,
        "logp_crippen": round(logp, 3),
        "refratividade_molar": round(mr, 3),
        "tpsa": round(tpsa, 2),
        "doadores_h": hbd,
        "aceptores_h": hba,
        "ligacoes_rotaveis": rot,
        "aneis": aneis,
        "aneis_aromaticos": arom,
        "atomos_pesados": pesados,
        "fracao_csp3": round(fsp3, 3),
        "carga_formal": carga,
        "centros_estereo": estereo,
        "qed": round(qed, 3),
        "violacoes_lipinski": viol_lip,
        "lipinski_ok": viol_lip <= 1,
        "veber_ok": veber,
        "ghose_ok": ghose,
        "egan_ok": egan,
        "muegge_ok": muegge,
        # BOILED-Egg simplificado (Daina & Zoete 2016): elipses aproximadas por limites
        "absorcao_gi_provavel": bool(tpsa <= 142 and -2.3 <= logp <= 6.8),
        "permeacao_bhe_provavel": bool(tpsa <= 79 and 0.4 <= logp <= 6.0),
        "alertas_pains": _alertas(m, "PAINS"),
        "alertas_brenk": _alertas(m, "BRENK"),
    }


def admet_ai(smiles_lista: list):
    """Previsões do ADMET-AI (Swanson et al. 2024), se o pacote admet-ai
    estiver instalado. Devolve DataFrame indexado pelo SMILES, ou None."""
    try:
        from admet_ai import ADMETModel
    except ImportError:
        return None
    try:
        modelo = ADMETModel()
        return modelo.predict(smiles=list(smiles_lista))
    except Exception as e:  # o modelo é pesado: falha não derruba a etapa
        print(f"  ADMET-AI falhou ({e}); seguindo só com os descritores do RDKit.")
        return None
