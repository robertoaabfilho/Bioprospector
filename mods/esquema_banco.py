"""
esquema_banco.py - Esquema do banco relacional (v3.20), em um lugar só.

Daqui saem: a ordem das colunas de cada CSV da pasta banco/, o dicionário de
dados (banco/dicionario_dados.csv), o esquema legível (banco/ESQUEMA.md) e o
descritor Frictionless Data (banco/datapackage.json), com chaves primárias e
estrangeiras.

Todas as tabelas de dados de compostos se ligam pelo InChIKey canônico
(compostos.inchikey). As tabelas de organismos se ligam pelo nome científico
(organismos.nome_cientifico), e a origem biológica liga as duas.
"""

import json

# (coluna, tipo, descrição). Tipos do Table Schema: string, integer, number, boolean
T = "string"
I = "integer"
N = "number"
B = "boolean"

TABELAS = {
    "compostos": {
        "descricao": "Identidade química: um composto por InChIKey canônico (deduplicado entre "
                     "todas as bases), com identificadores normalizados pelo PubChem e "
                     "classificação estrutural ClassyFire.",
        "chave": ["inchikey"],
        "colunas": [
            ("inchikey", T, "InChIKey canônico (identificador universal; chave de todo o banco)"),
            ("inchikey_conectividade", T, "1º bloco do InChIKey (14 caracteres): esqueleto sem estereoquímica"),
            ("nome_preferido", T, "título do PubChem; sem ele, o nome mais frequente nas bases"),
            ("nome_iupac", T, "nome IUPAC (PubChem)"),
            ("pubchem_cid", I, "PubChem CID do InChIKey canônico"),
            ("status_pubchem", T, "confirmado | ausente no PubChem | PubChem não consultado"),
            ("inchi", T, "InChI padrão (PubChem)"),
            ("smiles_isomerico", T, "SMILES com estereoquímica (PubChem; sem ele, o da base de maior prioridade)"),
            ("smiles_canonico", T, "SMILES canônico calculado pelo RDKit a partir de smiles_isomerico"),
            ("smiles_conectividade", T, "SMILES sem estereoquímica (PubChem)"),
            ("fonte_estrutura", T, "de onde veio a estrutura: PubChem ou a base"),
            ("formula_molecular", T, "fórmula molecular (PubChem; sem ela, calculada pelo RDKit)"),
            ("massa_molecular", N, "massa molecular média (g/mol, PubChem)"),
            ("massa_exata", N, "massa monoisotópica (Da, PubChem)"),
            ("carga", I, "carga formal líquida (PubChem)"),
            ("xlogp_pubchem", N, "XLogP3 (PubChem)"),
            ("tpsa_pubchem", N, "área polar topológica (Å², PubChem)"),
            ("complexidade_pubchem", N, "complexidade de Bertz/Hendrickson (PubChem)"),
            ("inchikey_parental", T, "InChIKey da forma parental (sem contraíon, neutralizada; RDKit)"),
            ("forma_parental_diferente", B, "true = o registro é sal ou forma carregada"),
            ("classyfire_kingdom", T, "ClassyFire: reino"),
            ("classyfire_superclass", T, "ClassyFire: superclasse"),
            ("classyfire_class", T, "ClassyFire: classe"),
            ("classyfire_subclass", T, "ClassyFire: subclasse"),
            ("classyfire_direct_parent", T, "ClassyFire: pai direto"),
            ("classyfire_framework", T, "ClassyFire: arcabouço molecular"),
            ("classyfire_fonte", T, "ClassyFire (API) ou COCONUT (ClassyFire pré-calculado)"),
            ("np_classifier_pathway", T, "NPClassifier: via biossintética (COCONUT)"),
            ("np_classifier_superclass", T, "NPClassifier: superclasse (COCONUT)"),
            ("np_classifier_class", T, "NPClassifier: classe (COCONUT)"),
            ("bases", T, "bases em que o composto aparece (separadas por '; ')"),
            ("n_bases", I, "número de bases distintas"),
            ("ids_nas_bases", T, "identificadores do composto em cada base"),
            ("n_ocorrencias", I, "registros de base x organismo (linhas em fontes.csv)"),
            ("n_plantas", I, "organismos produtores distintos"),
            ("n_sinonimos", I, "sinônimos registrados"),
            ("n_conflitos", I, "conflitos entre bases envolvendo o composto"),
            ("tipos_conflito", T, "tipos de conflito (ver conflitos.csv)"),
            ("n_bioatividades", I, "registros em bioatividade.csv"),
            ("n_bioatividades_quantitativas", I, "registros com valor numérico medido"),
            ("n_vias", I, "registros em vias_metabolicas.csv"),
            ("n_espectros", I, "registros experimentais/compilados em dados_espectrais.csv"),
            ("tem_admet", B, "true = perfil calculado em perfil_admet.csv"),
        ],
    },
    "fontes": {
        "descricao": "Rastreabilidade: cada registro de cada base (base x composto x organismo), "
                     "com o que AQUELA base informa e como se chegou ao InChIKey canônico.",
        "chave": ["id_ocorrencia"],
        "estrangeiras": [("inchikey", "compostos", "inchikey"),
                         ("nome_cientifico", "organismos", "nome_cientifico")],
        "colunas": [
            ("id_ocorrencia", T, "identificador do registro (OC0000001...)"),
            ("inchikey", T, "InChIKey canônico (vazio = registro sem estrutura)"),
            ("base", T, "COCONUT | NPASS | LOTUS | FOODB | DUKE"),
            ("id_na_base", T, "identificador do composto na base"),
            ("url_registro", T, "página do composto na base, quando existe"),
            ("nome_na_base", T, "nome do composto como está na base"),
            ("inchikey_declarado", T, "InChIKey informado pela base (válido)"),
            ("inchikey_calculado", T, "InChIKey calculado pelo RDKit do SMILES da base"),
            ("metodo_identificacao", T, "regra que definiu o InChIKey canônico"),
            ("smiles_na_base", T, "SMILES informado pela base"),
            ("smiles_valido", B, "o RDKit leu o SMILES da base"),
            ("pubchem_cid_na_base", T, "CID informado pela base"),
            ("organismo_na_base", T, "nome do organismo como casado na base"),
            ("nome_cientifico", T, "organismo produtor (linha de plantas.csv)"),
            ("atividade_na_base", T, "atividade/alvo informado pela base (NPASS, Dr. Duke)"),
            ("parte_planta", T, "parte da planta (Dr. Duke)"),
            ("teor", T, "teor relatado (Dr. Duke em ppm; FooDB)"),
            ("referencia", T, "referência bibliográfica do par (DOI do LOTUS)"),
        ],
    },
    "sinonimos": {
        "descricao": "Sinônimos e nomes do composto (PubChem e nomes usados em cada base).",
        "chave": ["inchikey", "sinonimo", "fonte"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("inchikey", T, "InChIKey canônico"),
            ("sinonimo", T, "nome"),
            ("tipo", T, "sinônimo | nome IUPAC | nome na base"),
            ("fonte", T, "PubChem ou a base"),
        ],
    },
    "organismos": {
        "descricao": "Organismos produtores (linhas de plantas.csv que têm ao menos um composto), "
                     "com taxonomia e distribuição resumida.",
        "chave": ["nome_cientifico"],
        "colunas": [
            ("nome_cientifico", T, "nome da linha em plantas.csv"),
            ("nome_aceito", T, "nome aceito (Flora do Brasil, WFO, WCVP ou GBIF)"),
            ("categoria_taxonomica", T, "SPECIES, GENUS..."),
            ("reino", T, ""), ("filo", T, ""), ("classe", T, ""), ("ordem", T, ""),
            ("familia", T, ""),
            ("nome_popular_pt", T, "nome popular"),
            ("speciesKey", T, "chave GBIF"),
            ("na_regiao", T, "sim = o organismo ocorre na região da rodada (plantas.csv); "
                             "não = veio das bases químicas, de fora da região"),
            ("estados_br", T, "UFs (siglas)"),
            ("dominios_br", T, "domínios fitogeográficos"),
            ("endemismo_br", T, "endêmica do Brasil / não endêmica"),
            ("origem_br", T, "nativa / exótica"),
            ("fonte_distribuicao", T, "Flora e Funga do Brasil ou GBIF"),
            ("n_compostos", I, "compostos (InChIKey) atribuídos ao organismo"),
        ],
    },
    "origem_biologica": {
        "descricao": "Composto x organismo produtor (uma linha por par), com as bases que o "
                     "registram e os metadados de cada uma.",
        "chave": ["inchikey", "nome_cientifico"],
        "estrangeiras": [("inchikey", "compostos", "inchikey"),
                         ("nome_cientifico", "organismos", "nome_cientifico")],
        "colunas": [
            ("inchikey", T, "InChIKey canônico"),
            ("nome_cientifico", T, "organismo produtor"),
            ("na_regiao", T, "sim = o organismo ocorre na região da rodada; não = de fora dela"),
            ("familia", T, "família do organismo"),
            ("bases", T, "bases que registram o par"),
            ("n_bases", I, "número de bases"),
            ("nomes_organismo_nas_bases", T, "nomes do organismo como aparecem nas bases"),
            ("parte_planta", T, "parte da planta (Dr. Duke)"),
            ("teor", T, "teor (Dr. Duke, FooDB)"),
            ("referencias", T, "referências (LOTUS)"),
            ("ids_ocorrencias", T, "registros de fontes.csv que sustentam o par"),
        ],
    },
    "distribuicao_geografica": {
        "descricao": "Distribuição geográfica do composto pelos organismos que o produzem: "
                     "composto x organismo x UF (Flora e Funga do Brasil; GBIF como 2ª camada).",
        "chave": ["inchikey", "nome_cientifico", "uf"],
        "estrangeiras": [("inchikey", "compostos", "inchikey"),
                         ("nome_cientifico", "organismos", "nome_cientifico")],
        "colunas": [
            ("inchikey", T, "InChIKey canônico"),
            ("nome_cientifico", T, "organismo produtor"),
            ("uf", T, "sigla da UF; vazio = distribuição desconhecida"),
            ("dominios_br", T, "domínios do organismo"),
            ("endemismo_br", T, ""), ("origem_br", T, ""),
            ("fonte_distribuicao", T, "Flora e Funga do Brasil ou GBIF"),
            ("registros_gbif_uf", I, "nº de registros GBIF na UF (só quando a fonte é o GBIF)"),
        ],
    },
    "bioatividade": {
        "descricao": "Bioatividade: medidas quantitativas (ChEMBL, NPASS) e relatos qualitativos "
                     "em artigos lidos pelo modelo (PubMed).",
        "chave": ["id_bioatividade"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("id_bioatividade", T, "identificador (BA0000001...)"),
            ("inchikey", T, "InChIKey canônico"),
            ("fonte", T, "ChEMBL | NPASS | PubMed"),
            ("natureza", T, "quantitativa | qualitativa"),
            ("correspondencia", T, "exata | estereoisômero | prevista (similaridade) | -"),
            ("molecula_ensaiada", T, "ID da molécula ensaiada na fonte (ChEMBL/NPASS)"),
            ("atividade_input", T, "atividade do input.txt a que o registro foi ligado"),
            ("alvo", T, "alvo molecular, célula ou organismo"),
            ("organismo_alvo", T, "organismo do alvo"),
            ("tipo_ensaio", T, "B, F, A, T... (ChEMBL) ou tipo de estudo (PubMed)"),
            ("descricao_ensaio", T, "descrição do ensaio ou justificativa do modelo"),
            ("tipo_medida", T, "IC50, Ki, MIC, Inhibition..."),
            ("relacao", T, "=, <, >, <=, >="),
            ("valor", N, "valor numérico"),
            ("unidade", T, "unidade do valor"),
            ("pvalor", N, "-log10(molar) para IC50/EC50/Ki/Kd... em unidade molar (pChEMBL quando existe)"),
            ("ativo", B, "pvalor >= pchembl_minimo do input.txt, ou marcado como ativo pela fonte"),
            ("pmid", T, "PMID"), ("doi", T, "DOI"), ("ano", I, "ano da publicação"),
            ("id_registro_fonte", T, "documento/registro na fonte"),
        ],
    },
    "vias_metabolicas": {
        "descricao": "Vias metabólicas e de sinalização associadas ao composto (PubChem: "
                     "Reactome, WikiPathways, KEGG, PlantCyc, PathBank...) e a via biossintética "
                     "prevista pelo NPClassifier.",
        "chave": ["inchikey", "fonte", "via_id"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("inchikey", T, "InChIKey canônico"),
            ("tipo", T, "via (base de vias) | via biossintética (NPClassifier)"),
            ("via_id", T, "identificador da via na fonte"),
            ("via_nome", T, "nome da via"),
            ("fonte", T, "fonte da via"),
            ("categoria", T, "categoria da via"),
            ("organismo", T, "organismo da via"),
            ("url", T, "link"),
        ],
    },
    "dados_espectrais": {
        "descricao": "Dados espectrais: registros compilados no PubChem (MS, MS/MS, GC-MS, "
                     "LC-MS, RMN, IV, UV) e m/z teóricos dos adutos mais comuns (RDKit).",
        "chave": ["id_espectro"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("id_espectro", T, "identificador (ES0000001...)"),
            ("inchikey", T, "InChIKey canônico"),
            ("origem", T, "experimental (PubChem) | teórico (RDKit)"),
            ("tipo", T, "Mass Spectrometry, NMR Spectra, IR Spectra, UV Spectra..."),
            ("subtipo", T, "GC-MS, MS-MS, 1D NMR, [M+H]+ ..."),
            ("valor", N, "m/z teórico (só origem teórica)"),
            ("descricao", T, "picos, instrumento, condições (texto do PubChem)"),
            ("fonte", T, "depositante (MassBank, HMDB, SpectraBase, NIST...)"),
            ("id_fonte", T, "identificador no depositante"),
            ("url", T, "link"),
        ],
    },
    "perfil_admet": {
        "descricao": "Drogabilidade e perfil ADMET básico calculados localmente (RDKit, módulo "
                     "quimio.py) para todo composto com SMILES canônico. São PREVISÕES por regra, "
                     "não medidas.",
        "chave": ["inchikey"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("inchikey", T, "InChIKey canônico"),
            ("smiles_canonico", T, "SMILES usado no cálculo"),
            ("status_admet", T, "calculado | SMILES inválido"),
            ("massa_molecular_rdkit", N, "massa molecular (g/mol)"),
            ("massa_monoisotopica_rdkit", N, "massa monoisotópica (Da)"),
            ("logp_crippen", N, "logP de Wildman-Crippen"),
            ("refratividade_molar", N, "refratividade molar (Crippen)"),
            ("tpsa", N, "área polar topológica (Å², Ertl)"),
            ("doadores_h", I, "doadores de ligação de H (Lipinski)"),
            ("aceptores_h", I, "aceptores de ligação de H (Lipinski)"),
            ("ligacoes_rotaveis", I, "ligações rotáveis"),
            ("aneis", I, "anéis"), ("aneis_aromaticos", I, "anéis aromáticos"),
            ("atomos_pesados", I, "átomos pesados"),
            ("fracao_csp3", N, "fração de carbonos sp3"),
            ("carga_formal", I, "carga formal"),
            ("centros_estereo", I, "centros estereogênicos (inclusive não atribuídos)"),
            ("qed", N, "Quantitative Estimate of Drug-likeness (Bickerton 2012), 0-1"),
            ("violacoes_lipinski", I, "violações da regra dos 5"),
            ("lipinski_ok", B, "<= 1 violação"),
            ("veber_ok", B, "rotáveis <= 10 e TPSA <= 140"),
            ("ghose_ok", B, "filtro de Ghose"),
            ("egan_ok", B, "filtro de Egan"),
            ("muegge_ok", B, "filtro de Muegge"),
            ("absorcao_gi_provavel", B, "absorção gastrointestinal provável (BOILED-Egg simplificado)"),
            ("permeacao_bhe_provavel", B, "permeação da barreira hematoencefálica provável (BOILED-Egg simplificado)"),
            ("alertas_pains", T, "subestruturas PAINS (interferência em ensaios)"),
            ("alertas_brenk", T, "subestruturas indesejáveis/tóxicas (Brenk)"),
            ("metodo", T, "ferramenta e versão"),
        ],
    },
    "conflitos": {
        "descricao": "Conflitos detectados entre as bases (e entre bases e PubChem/ClassyFire), "
                     "com a resolução adotada. Um conflito com vários compostos tem uma linha por "
                     "InChIKey.",
        "chave": ["id_conflito", "inchikey"],
        "estrangeiras": [("inchikey", "compostos", "inchikey")],
        "colunas": [
            ("id_conflito", T, "identificador (CF000001...)"),
            ("inchikey", T, "InChIKey canônico envolvido"),
            ("tipo_conflito", T, "ver ESQUEMA.md"),
            ("severidade", T, "alta | média | baixa | informativa"),
            ("campo", T, "campo em conflito"),
            ("bases_envolvidas", T, "bases"),
            ("valores", T, "valores divergentes"),
            ("ids_ocorrencias", T, "registros de fontes.csv envolvidos"),
            ("resolucao", T, "decisão tomada pelo pipeline"),
        ],
    },
    "mapa_inchikey": {
        "descricao": "De-para dos InChIKeys de origem (declarados pelas bases ou calculados dos "
                     "SMILES delas) para o canônico.",
        "chave": ["inchikey_origem", "inchikey_canonico", "origem"],
        "estrangeiras": [("inchikey_canonico", "compostos", "inchikey")],
        "colunas": [
            ("inchikey_origem", T, "InChIKey como veio"),
            ("inchikey_canonico", T, "InChIKey adotado"),
            ("origem", T, "declarado pela base | calculado do SMILES da base"),
            ("bases", T, "bases"),
            ("n_ocorrencias", I, "registros"),
            ("mudou", B, "true = o de origem foi trocado"),
        ],
    },
}

# colunas extras do ADMET-AI (opcional) entram em perfil_admet com o prefixo:
PREFIXO_ADMET_AI = "admetai_"

TIPOS_CONFLITO = {
    "inchikey_declarado_x_smiles": "o InChIKey que a base declara não é o do SMILES que ela mesma dá",
    "smiles_invalido": "o RDKit não lê o SMILES da base",
    "estrutura_entre_bases": "bases dão estruturas diferentes ao mesmo composto",
    "formula_entre_bases": "fórmula da base diferente da do PubChem",
    "cid_entre_bases": "o CID que a base informa não é o do InChIKey canônico",
    "classificacao_classyfire": "classe ClassyFire do COCONUT diferente da API atual",
    "id_x_estrutura": "o mesmo identificador da base aponta para estruturas diferentes",
    "nome_x_estrutura": "o mesmo nome aponta para esqueletos diferentes em bases diferentes",
    "variantes_estereo": "mesma conectividade, estereoquímica diferente (informativo)",
    "sal_ou_forma_carregada": "o registro é sal/forma carregada da parental (informativo)",
}


def colunas(tabela: str) -> list:
    return [c for c, *_ in TABELAS[tabela]["colunas"]]


# ---------------------------------------------------------------------------
# Nomes em inglês (banco publicável)
# ---------------------------------------------------------------------------
# O banco de banco/ é o produto que vai para o repositório permanente e para o
# data paper, e por isso sai em inglês: arquivos, colunas e a chave universal
# (compound_uid = InChIKey canônico). As planilhas de trabalho na raiz
# (plantas.csv, especies_com_compostos_bioativos.csv...) seguem em português.
# [banco] idioma_banco = pt devolve o banco com os nomes em português.
IDIOMA = "en"

TABELAS_EN = {
    "compostos": "compounds_identity_master",
    "fontes": "compounds_sources",
    "sinonimos": "compounds_synonyms",
    "organismos": "organisms",
    "origem_biologica": "compounds_biological_origin",
    "distribuicao_geografica": "compounds_geographic_distribution",
    "bioatividade": "compounds_bioactivity",
    "vias_metabolicas": "compounds_pathways",
    "dados_espectrais": "compounds_spectra",
    "perfil_admet": "compounds_druglikeness_admet",
    "conflitos": "conflicts",
    "mapa_inchikey": "inchikey_map",
}

# coluna em português -> (coluna em inglês, descrição em inglês)
COLUNAS_EN = {
    # --- identidade química -------------------------------------------------
    "inchikey": ("compound_uid", "Canonical InChIKey: the universal identifier and the key of the whole database"),
    "inchikey_conectividade": ("inchikey_skeleton", "First InChIKey block (14 characters): connectivity, without stereochemistry"),
    "nome_preferido": ("preferred_name", "PubChem title; failing that, the most frequent name across the source databases"),
    "nome_iupac": ("iupac_name", "IUPAC name (PubChem)"),
    "pubchem_cid": ("pubchem_cid", "PubChem CID of the canonical InChIKey"),
    "status_pubchem": ("pubchem_status", "confirmed | absent from PubChem | PubChem not queried"),
    "inchi": ("inchi", "Standard InChI (PubChem)"),
    "smiles_isomerico": ("isomeric_smiles", "SMILES with stereochemistry (PubChem; failing that, from the highest-priority source database)"),
    "smiles_canonico": ("canonical_smiles", "Canonical SMILES computed by RDKit from isomeric_smiles"),
    "smiles_conectividade": ("connectivity_smiles", "SMILES without stereochemistry (PubChem)"),
    "fonte_estrutura": ("structure_source", "Where the structure came from: PubChem or the source database"),
    "formula_molecular": ("molecular_formula", "Molecular formula (PubChem; failing that, computed by RDKit)"),
    "massa_molecular": ("molecular_weight", "Average molecular weight (g/mol, PubChem)"),
    "massa_exata": ("exact_mass", "Monoisotopic mass (Da, PubChem)"),
    "carga": ("charge", "Net formal charge (PubChem)"),
    "xlogp_pubchem": ("xlogp_pubchem", "XLogP3 (PubChem)"),
    "tpsa_pubchem": ("tpsa_pubchem", "Topological polar surface area (A^2, PubChem)"),
    "complexidade_pubchem": ("complexity_pubchem", "Bertz/Hendrickson complexity (PubChem)"),
    "inchikey_parental": ("parent_compound_uid", "InChIKey of the parent form (counterion removed, neutralised; RDKit)"),
    "forma_parental_diferente": ("is_salt_or_charged_form", "true = the record is a salt or a charged form"),
    "classyfire_kingdom": ("classyfire_kingdom", "ClassyFire: kingdom"),
    "classyfire_superclass": ("classyfire_superclass", "ClassyFire: superclass"),
    "classyfire_class": ("classyfire_class", "ClassyFire: class"),
    "classyfire_subclass": ("classyfire_subclass", "ClassyFire: subclass"),
    "classyfire_direct_parent": ("classyfire_direct_parent", "ClassyFire: direct parent"),
    "classyfire_framework": ("classyfire_framework", "ClassyFire: molecular framework"),
    "classyfire_fonte": ("classyfire_source", "ClassyFire (API) or COCONUT (pre-computed ClassyFire)"),
    "np_classifier_pathway": ("np_classifier_pathway", "NPClassifier: biosynthetic pathway (COCONUT)"),
    "np_classifier_superclass": ("np_classifier_superclass", "NPClassifier: superclass (COCONUT)"),
    "np_classifier_class": ("np_classifier_class", "NPClassifier: class (COCONUT)"),
    "bases": ("sources", "Source databases the record appears in (separated by '; ')"),
    "n_bases": ("n_sources", "Number of distinct source databases"),
    "ids_nas_bases": ("source_ids", "Identifiers of the compound in each source database"),
    "n_ocorrencias": ("n_source_records", "Number of source records (rows of compounds_sources)"),
    "n_plantas": ("n_organisms", "Number of producing organisms the compound is attributed to"),
    "n_sinonimos": ("n_synonyms", "Number of synonyms"),
    "n_conflitos": ("n_conflicts", "Number of conflicts involving the compound"),
    "tipos_conflito": ("conflict_types", "Types of conflict involving the compound"),
    "n_bioatividades": ("n_bioactivities", "Number of bioactivity records"),
    "n_bioatividades_quantitativas": ("n_quantitative_bioactivities", "Number of quantitative bioactivity records"),
    "n_vias": ("n_pathways", "Number of pathway records"),
    "n_espectros": ("n_spectra", "Number of spectral records"),
    "tem_admet": ("has_admet", "true = the compound has a druglikeness/ADMET profile"),
    # --- proveniência -------------------------------------------------------
    "id_ocorrencia": ("source_record_id", "Source record identifier (OC0000001...)"),
    "base": ("source_db", "COCONUT | NPASS | LOTUS | FOODB | DUKE"),
    "id_na_base": ("id_in_source", "Identifier of the compound in that source database"),
    "url_registro": ("source_url", "Page of the compound in the source database, where one exists"),
    "nome_na_base": ("name_in_source", "Compound name as the source database gives it"),
    "inchikey_declarado": ("inchikey_reported", "InChIKey reported by the source database (valid)"),
    "inchikey_calculado": ("inchikey_from_smiles", "InChIKey computed by RDKit from the SMILES of that source database"),
    "metodo_identificacao": ("identification_method", "Rule that determined the canonical InChIKey"),
    "smiles_na_base": ("smiles_in_source", "SMILES as the source database gives it"),
    "smiles_valido": ("smiles_parsed", "true = RDKit parsed the SMILES of the source database"),
    "pubchem_cid_na_base": ("pubchem_cid_in_source", "CID reported by the source database"),
    "organismo_na_base": ("organism_in_source", "Organism name as matched in the source database"),
    "nome_cientifico": ("scientific_name", "Producing organism (accepted name used by the pipeline)"),
    "atividade_na_base": ("activity_in_source", "Activity or target reported by the source database (NPASS, Dr. Duke)"),
    "parte_planta": ("plant_part", "Plant part (Dr. Duke)"),
    "teor": ("content", "Reported content (Dr. Duke in ppm; FooDB)"),
    "referencia": ("reference", "Bibliographic reference of the compound-organism pair (LOTUS DOI)"),
    # --- sinônimos ----------------------------------------------------------
    "sinonimo": ("synonym", "Name"),
    "tipo": ("type", "Record type within the table"),
    "fonte": ("source", "Source of the record"),
    # --- organismos e distribuição -----------------------------------------
    "nome_aceito": ("accepted_name", "Accepted name (Flora e Funga do Brasil, WFO, WCVP or GBIF)"),
    "categoria_taxonomica": ("taxon_rank", "SPECIES, GENUS..."),
    "reino": ("kingdom", "Kingdom"),
    "filo": ("phylum", "Phylum"),
    "classe": ("class", "Class"),
    "ordem": ("order", "Order"),
    "familia": ("family", "Family"),
    "nome_popular_pt": ("common_name_pt", "Common name(s) in Portuguese"),
    "speciesKey": ("gbif_species_key", "GBIF speciesKey"),
    "na_regiao": ("in_region", "yes = the organism occurs in the region of the run; no = it came from the source databases, from outside the region"),
    "estados_br": ("br_states", "Brazilian states (two-letter codes) where the organism occurs"),
    "dominios_br": ("br_phytogeographic_domains", "Brazilian phytogeographic domains (Amazonia, Cerrado, Mata Atlantica, Caatinga, Pampa, Pantanal)"),
    "endemismo_br": ("br_endemism", "endemic to Brazil / not endemic"),
    "origem_br": ("br_origin", "native / exotic"),
    "fonte_distribuicao": ("distribution_source", "Flora e Funga do Brasil or GBIF (georeferenced records)"),
    "n_compostos": ("n_compounds", "Compounds (canonical InChIKey) attributed to the organism"),
    "nomes_organismo_nas_bases": ("organism_names_in_sources", "Organism names as they appear in the source databases"),
    "referencias": ("references", "References (LOTUS)"),
    "ids_ocorrencias": ("source_record_ids", "Rows of compounds_sources that support the record"),
    "uf": ("state_code", "Two-letter Brazilian state code; empty = distribution unknown"),
    "registros_gbif_uf": ("gbif_records_in_state", "Number of GBIF records in the state (only when the source is GBIF)"),
    # --- bioatividade -------------------------------------------------------
    "id_bioatividade": ("bioactivity_id", "Bioactivity record identifier (BA0000001...)"),
    "natureza": ("nature", "quantitative (measured assay) | qualitative (reported in an article)"),
    "correspondencia": ("match_type", "exact | stereoisomer | predicted (similarity) | -"),
    "molecula_ensaiada": ("assayed_molecule_id", "Identifier of the assayed molecule in the source (ChEMBL/NPASS)"),
    "atividade_input": ("activity_label", "Activity from the run configuration the record was mapped to"),
    "alvo": ("target", "Molecular target, cell line or organism"),
    "organismo_alvo": ("target_organism", "Organism of the target"),
    "tipo_ensaio": ("assay_type", "B, F, A, T... (ChEMBL) or study type (PubMed)"),
    "descricao_ensaio": ("assay_description", "Assay description, or the model's justification (PubMed)"),
    "tipo_medida": ("measure_type", "IC50, Ki, MIC, Inhibition..."),
    "relacao": ("relation", "=, <, >, <=, >="),
    "valor": ("value", "Numeric value"),
    "unidade": ("units", "Unit of the value"),
    "pvalor": ("p_activity", "-log10(molar) for IC50/EC50/Ki/Kd in molar units (pChEMBL where available). NOT a statistical p-value"),
    "ativo": ("is_active", "true = p_activity >= the threshold set for the run, or flagged as active by the source"),
    "pmid": ("pmid", "PubMed identifier"),
    "doi": ("doi", "DOI"),
    "ano": ("year", "Publication year"),
    "id_registro_fonte": ("source_record_ref", "Document or record in the source database"),
    # --- vias e espectros ---------------------------------------------------
    "via_id": ("pathway_id", "Pathway identifier in the source"),
    "via_nome": ("pathway_name", "Pathway name"),
    "categoria": ("category", "Pathway category"),
    "organismo": ("organism", "Organism of the pathway"),
    "url": ("url", "Link"),
    "id_espectro": ("spectrum_id", "Spectral record identifier (ES0000001...)"),
    "origem": ("origin", "Origin of the record"),
    "subtipo": ("subtype", "GC-MS, MS-MS, 1D NMR, [M+H]+ ..."),
    "descricao": ("description", "Peaks, instrument, conditions (text from the source)"),
    "id_fonte": ("id_in_source", "Identifier at the depositor"),
    # --- ADMET --------------------------------------------------------------
    "status_admet": ("admet_status", "computed | invalid SMILES"),
    "massa_molecular_rdkit": ("molecular_weight_rdkit", "Molecular weight (g/mol, RDKit)"),
    "massa_monoisotopica_rdkit": ("monoisotopic_mass_rdkit", "Monoisotopic mass (Da, RDKit)"),
    "logp_crippen": ("logp_crippen", "Wildman-Crippen logP"),
    "refratividade_molar": ("molar_refractivity", "Molar refractivity (Crippen)"),
    "tpsa": ("tpsa", "Topological polar surface area (A^2, Ertl)"),
    "doadores_h": ("h_bond_donors", "Hydrogen-bond donors (Lipinski)"),
    "aceptores_h": ("h_bond_acceptors", "Hydrogen-bond acceptors (Lipinski)"),
    "ligacoes_rotaveis": ("rotatable_bonds", "Rotatable bonds"),
    "aneis": ("rings", "Rings"),
    "aneis_aromaticos": ("aromatic_rings", "Aromatic rings"),
    "atomos_pesados": ("heavy_atoms", "Heavy atoms"),
    "fracao_csp3": ("fraction_csp3", "Fraction of sp3 carbons"),
    "carga_formal": ("formal_charge", "Formal charge"),
    "centros_estereo": ("stereocenters", "Stereogenic centres (including unassigned)"),
    "qed": ("qed", "Quantitative Estimate of Drug-likeness (Bickerton 2012), 0-1"),
    "violacoes_lipinski": ("lipinski_violations", "Violations of the rule of five"),
    "lipinski_ok": ("lipinski_pass", "true = at most one violation"),
    "veber_ok": ("veber_pass", "true = rotatable bonds <= 10 and TPSA <= 140"),
    "ghose_ok": ("ghose_pass", "true = passes the Ghose filter"),
    "egan_ok": ("egan_pass", "true = passes the Egan filter"),
    "muegge_ok": ("muegge_pass", "true = passes the Muegge filter"),
    "absorcao_gi_provavel": ("gi_absorption_likely", "Gastrointestinal absorption likely (simplified BOILED-Egg)"),
    "permeacao_bhe_provavel": ("bbb_permeation_likely", "Blood-brain barrier permeation likely (simplified BOILED-Egg)"),
    "alertas_pains": ("pains_alerts", "PAINS substructures (assay interference)"),
    "alertas_brenk": ("brenk_alerts", "Unwanted or toxicophoric substructures (Brenk)"),
    "metodo": ("method", "Tool and version used for the calculation"),
    # --- conflitos e mapa ---------------------------------------------------
    "id_conflito": ("conflict_id", "Conflict identifier (CF000001...)"),
    "tipo_conflito": ("conflict_type", "Conflict type (see SCHEMA.md)"),
    "severidade": ("severity", "high | medium | low | informational"),
    "campo": ("field", "Field in conflict"),
    "bases_envolvidas": ("sources_involved", "Source databases involved"),
    "valores": ("values", "Diverging values"),
    "resolucao": ("resolution", "Decision taken by the pipeline"),
    "inchikey_origem": ("inchikey_as_given", "InChIKey as it came from the source"),
    "inchikey_canonico": ("compound_uid", "Canonical InChIKey adopted"),
    "mudou": ("changed", "true = the incoming InChIKey was replaced by the canonical one"),
}


# Colunas cujos VALORES também mudam de idioma (as demais guardam dados, não rótulos)
TIPOS_CONFLITO_EN_VALOR = {
    "inchikey_declarado_x_smiles": "reported_inchikey_vs_smiles",
    "smiles_invalido": "unparseable_smiles",
    "estrutura_entre_bases": "structure_between_sources",
    "formula_entre_bases": "formula_between_sources",
    "cid_entre_bases": "cid_between_sources",
    "classificacao_classyfire": "classyfire_classification",
    "id_x_estrutura": "id_vs_structure",
    "nome_x_estrutura": "name_vs_structure",
    "variantes_estereo": "stereo_variants",
    "sal_ou_forma_carregada": "salt_or_charged_form",
}
SEVERIDADE_EN = {"alta": "high", "média": "medium", "baixa": "low",
                 "informativa": "informational"}
VALORES_EN = {"na_regiao": {"sim": "yes", "não": "no"},
              "tipo_conflito": TIPOS_CONFLITO_EN_VALOR,
              "tipos_conflito": TIPOS_CONFLITO_EN_VALOR,
              "severidade": SEVERIDADE_EN}


# --- nomes dos arquivos de metadados e do relatório de qualidade -----------
ARQ_META_EN = {
    "ESQUEMA.md": "SCHEMA.md",
    "PROVENIENCIA_E_LICENCAS.md": "PROVENANCE_AND_LICENSES.md",
    "LEIA-ME.txt": "README.txt",
    "RELATORIO_QUALIDADE.md": "QUALITY_REPORT.md",
    "dicionario_dados.csv": "data_dictionary.csv",
}

# --- pasta banco/qualidade/ (análise de qualidade e cobertura) -------------
ARQ_QUALIDADE_EN = {
    "completude_campos.csv": "field_completeness.csv",
    "completude_por_base.csv": "field_completeness_by_source.csv",
    "compostos_por_n_bases.csv": "compounds_by_number_of_sources.csv",
    "cobertura_universo_resumo.csv": "taxonomic_coverage_summary.csv",
    "cobertura_universo_por_familia.csv": "taxonomic_coverage_by_family.csv",
    "espaco_quimico_classyfire_classe.csv": "chemical_space_classyfire_class.csv",
    "espaco_quimico_npclassifier_superclasse.csv": "chemical_space_npclassifier_superclass.csv",
    "espaco_quimico_npclassifier_via.csv": "chemical_space_npclassifier_pathway.csv",
    "espaco_quimico_umap.csv": "chemical_space_umap.csv",
    "sobreposicao_bases.csv": "source_overlap.csv",
    "sobreposicao_jaccard.csv": "source_overlap_jaccard.csv",
    "taxonomia_resumo.csv": "taxonomy_summary.csv",
    "taxonomia_reino.csv": "taxonomy_by_kingdom.csv",
    "taxonomia_classe.csv": "taxonomy_by_class.csv",
    "taxonomia_ordem.csv": "taxonomy_by_order.csv",
    "taxonomia_familia.csv": "taxonomy_by_family.csv",
    "vieses_curadoria.csv": "curation_bias.csv",
    "g_completude_por_base.png": "g_field_completeness_by_source.png",
    "g_espaco_quimico.png": "g_chemical_space.png",
    "g_espaco_quimico_umap.png": "g_chemical_space_umap.png",
    "g_sobreposicao_bases.png": "g_source_overlap.png",
    "g_cobertura_familias.png": "g_coverage_by_family.png",
}

COLS_QUALIDADE_EN = {
    "tabela": "table", "coluna": "column", "n_linhas": "n_rows",
    "preenchidos": "n_filled", "completude_pct": "completeness_pct",
    "base": "source_db", "n_registros": "n_records", "n_compostos": "n_compounds",
    "n_organismos": "n_organisms", "n_bases": "n_sources", "compostos": "n_compounds",
    "compartilhados": "shared", "exclusivos": "exclusive",
    "exclusivos_pct": "exclusive_pct", "pct": "pct", "valor": "value",
    "metrica": "metric", "dimensao": "dimension", "observacao": "note",
    "reino": "kingdom", "classe": "class", "ordem": "order", "familia": "family",
    "familias": "n_families", "ordens": "n_orders",
    "especies_alvo": "target_species", "com_composto": "with_compound",
    "sem_composto": "without_compound", "cobertura_pct": "coverage_pct",
    "organismos_com_composto": "organisms_with_compound",
    "com_distribuicao_conhecida": "with_known_distribution",
    "nativas_br": "native_br", "endemicas_br": "endemic_br",
    "classyfire_classe": "classyfire_class",
    "npclassifier_superclasse": "np_classifier_superclass",
    "npclassifier_via": "np_classifier_pathway",
    # a projeção UMAP usa a chave do banco, como as outras tabelas
    "inchikey": "compound_uid", "nome_preferido": "preferred_name",
    "umap_x": "umap_x", "umap_y": "umap_y",
}

# rótulos dos campos medidos na completude por base (viram colunas <rótulo>_pct)
ROTULOS_CAMPO_EN = {
    "nome": "name", "InChIKey declarado": "reported InChIKey", "SMILES": "SMILES",
    "CID": "CID", "organismo": "organism", "atividade/alvo": "activity or target",
    "parte da planta": "plant part", "teor": "content", "referência": "reference",
    "SMILES válido": "parseable SMILES", "TODAS": "ALL",
}


# descrições em inglês das tabelas e dos tipos de conflito (SCHEMA.md)
TABELAS_DESC_EN = {
    "compostos": "Chemical identity: one compound per canonical InChIKey (deduplicated "
                 "across every source), with identifiers normalised by PubChem and "
                 "ClassyFire structural classification.",
    "fontes": "Traceability: every record of every source (source x compound x organism), "
              "with what THAT source states and how the canonical InChIKey was reached.",
    "sinonimos": "Synonyms and names of the compound (PubChem, and the names used by each "
                 "source).",
    "organismos": "Producing organisms (the species of the run that have at least one "
                  "compound), with taxonomy and a summary of their distribution.",
    "origem_biologica": "Compound x producing organism (one row per pair), with the sources "
                        "that record it and the metadata each one provides.",
    "distribuicao_geografica": "Geographic distribution of the compound through the "
                               "organisms that produce it: compound x organism x Brazilian "
                               "state (Flora e Funga do Brasil; GBIF as a second layer).",
    "bioatividade": "Bioactivity: quantitative measurements (ChEMBL, NPASS) and qualitative "
                    "reports from articles read by a language model (PubMed).",
    "vias_metabolicas": "Metabolic and signalling pathways associated with the compound "
                        "(PubChem: Reactome, WikiPathways, KEGG, PlantCyc, PathBank...) and "
                        "the biosynthetic pathway predicted by NPClassifier.",
    "dados_espectrais": "Spectral metadata: records compiled by PubChem (MS, MS/MS, GC-MS, "
                        "LC-MS, NMR, IR, UV) and theoretical m/z of the commonest adducts "
                        "(RDKit).",
    "perfil_admet": "Druglikeness and basic ADMET computed locally (RDKit) for every "
                    "compound with a canonical SMILES. These are rule-based PREDICTIONS, "
                    "not measurements.",
    "conflitos": "Conflicts detected between sources (and between a source and "
                 "PubChem/ClassyFire), with the resolution adopted. A conflict involving "
                 "several compounds has one row per InChIKey.",
    "mapa_inchikey": "Mapping from incoming InChIKeys (reported by the sources, or computed "
                     "from their SMILES) to the canonical one.",
}

TIPOS_CONFLITO_EN = {
    "inchikey_declarado_x_smiles": "the InChIKey the source reports is not the one of the "
                                   "SMILES it gives itself",
    "smiles_invalido": "RDKit cannot parse the SMILES of the source",
    "estrutura_entre_bases": "sources give different structures for the same compound",
    "formula_entre_bases": "the formula of the source differs from PubChem's",
    "cid_entre_bases": "the CID reported by the source is not the one of the canonical "
                       "InChIKey",
    "classificacao_classyfire": "the ClassyFire class from COCONUT differs from the current "
                                "API",
    "id_x_estrutura": "the same source identifier points to different structures",
    "nome_x_estrutura": "the same name points to different skeletons in different sources",
    "variantes_estereo": "same connectivity, different stereochemistry (informational)",
    "sal_ou_forma_carregada": "the record is a salt or charged form of the parent "
                              "(informational)",
}


def descricao_tabela(tabela: str) -> str:
    if IDIOMA == "en" and tabela in TABELAS_DESC_EN:
        return TABELAS_DESC_EN[tabela]
    return TABELAS[tabela]["descricao"]


def descricao_conflito(tipo: str) -> str:
    if IDIOMA == "en" and tipo in TIPOS_CONFLITO_EN:
        return TIPOS_CONFLITO_EN[tipo]
    return TIPOS_CONFLITO.get(tipo, "")


def nome_meta(arquivo: str) -> str:
    """Nome de um arquivo de metadados no idioma do banco."""
    return ARQ_META_EN.get(arquivo, arquivo) if IDIOMA == "en" else arquivo


def nome_qualidade(arquivo: str) -> str:
    """Nome de um arquivo de banco/qualidade/ no idioma do banco."""
    return ARQ_QUALIDADE_EN.get(arquivo, arquivo) if IDIOMA == "en" else arquivo


def rotulo_campo(rotulo: str) -> str:
    return ROTULOS_CAMPO_EN.get(rotulo, rotulo) if IDIOMA == "en" else rotulo


def traduzir_qualidade(df):
    """Cabeçalhos de uma tabela de banco/qualidade/ no idioma do banco. Nomes
    de bases usados como coluna (matriz de Jaccard) passam intactos."""
    if IDIOMA != "en" or df is None or not len(df.columns):
        return df
    def nome(c):
        if c in COLS_QUALIDADE_EN:
            return COLS_QUALIDADE_EN[c]
        if c.endswith("_pct"):                 # <rótulo do campo>_pct
            return rotulo_campo(c[:-4]).replace(" ", "_") + "_pct"
        return c
    return df.rename(columns={c: nome(c) for c in df.columns})


def nome_tabela(tabela: str) -> str:
    """Nome do arquivo da tabela, sem .csv, no idioma do banco."""
    return TABELAS_EN.get(tabela, tabela) if IDIOMA == "en" else tabela


def nome_coluna(coluna: str) -> str:
    par = COLUNAS_EN.get(coluna)
    return par[0] if par and IDIOMA == "en" else coluna


def descricao_coluna(coluna: str, descricao_pt: str) -> str:
    par = COLUNAS_EN.get(coluna)
    return par[1] if par and IDIOMA == "en" else descricao_pt


def colunas_idioma(tabela: str) -> list:
    return [nome_coluna(c) for c in colunas(tabela)]


def _traduzir_valor(v, mapa: dict):
    """Traduz um valor de enum. Colunas que guardam vários valores separados
    por "; " (ex.: tipos_conflito) são traduzidas item a item."""
    if not isinstance(v, str):
        return v
    if v in mapa:
        return mapa[v]
    if "; " in v:
        return "; ".join(mapa.get(x, x) for x in v.split("; "))
    return v


def traduzir(df, tabela: str | None = None):
    """Renomeia as colunas (e traduz os poucos valores que são rótulos) para o
    idioma do banco, na gravação."""
    if IDIOMA != "en" or df is None or not len(df.columns):
        return df
    for coluna, mapa in VALORES_EN.items():
        if coluna in df.columns:
            df = df.copy()
            df[coluna] = df[coluna].map(lambda v: _traduzir_valor(v, mapa))
    return df.rename(columns={c: nome_coluna(c) for c in df.columns})


def destraduzir(df, tabela: str | None = None):
    """Volta os nomes para português (na leitura, pela etapa "qualidade")."""
    if df is None or not len(df.columns):
        return df
    # mapa_inchikey usa compound_uid para o canônico; nas outras é "inchikey"
    volta = {}
    for pt, (en, _) in COLUNAS_EN.items():
        volta.setdefault(en, pt)
    if tabela == "mapa_inchikey":
        volta["compound_uid"] = "inchikey_canonico"
    df = df.rename(columns={c: volta[c] for c in df.columns if c in volta})
    for coluna, mapa in VALORES_EN.items():
        if coluna in df.columns:
            para_pt = {v: k for k, v in mapa.items()}
            df = df.copy()
            df[coluna] = df[coluna].map(lambda v: _traduzir_valor(v, para_pt))
    return df


def dicionario():
    """Dicionário de dados, bilíngue: o nome de cada coluna no idioma do banco,
    o nome em português usado no pipeline, e a descrição nos dois idiomas."""
    linhas = []
    for nome, t in TABELAS.items():
        estr = {c: f"{nome_tabela(tab)}.{nome_coluna(ref)}"
                for c, tab, ref in t.get("estrangeiras", [])}
        for c, tipo, desc in t["colunas"]:
            linhas.append({"tabela": f"{nome_tabela(nome)}.csv", "tabela_pt": f"{nome}.csv",
                           "coluna": nome_coluna(c), "coluna_pt": c, "tipo": tipo,
                           "chave_primaria": c in t["chave"],
                           "chave_estrangeira": estr.get(c, ""),
                           "description_en": descricao_coluna(c, desc), "descricao_pt": desc})
    return linhas


# Bases de origem (FAIR: proveniência e licença). Os termos de licença mudam
# entre versões de cada base e DEVEM ser confirmados na data da coleta; aqui
# fica o que é de conhecimento geral, com essa ressalva.
FONTES_META = [
    {"nome": "COCONUT", "titulo": "COCONUT – COllection of Open Natural ProdUcts",
     "url": "https://coconut.naturalproducts.net",
     "licenca": "aberta (confirmar CC0/CC-BY na versão usada)"},
    {"nome": "NPASS", "titulo": "NPASS – Natural Product Activity & Species Source",
     "url": "https://bidd.group/NPASS/",
     "licenca": "uso acadêmico (confirmar termos no site)"},
    {"nome": "LOTUS", "titulo": "LOTUS – Natural Products Online (via Wikidata)",
     "url": "https://lotus.naturalproducts.net",
     "licenca": "CC0-1.0 (dados no Wikidata)"},
    {"nome": "DUKE", "titulo": "Dr. Duke's Phytochemical and Ethnobotanical Databases (USDA-ARS)",
     "url": "https://phytochem.nal.usda.gov",
     "licenca": "domínio público (obra do governo dos EUA)"},
    {"nome": "FOODB", "titulo": "FooDB",
     "url": "https://foodb.ca",
     "licenca": "uso livre (confirmar termos no site)"},
    {"nome": "ChEMBL", "titulo": "ChEMBL (EMBL-EBI)",
     "url": "https://www.ebi.ac.uk/chembl/",
     "licenca": "CC-BY-SA-3.0"},
    {"nome": "PubChem", "titulo": "PubChem (NCBI/NLM)",
     "url": "https://pubchem.ncbi.nlm.nih.gov",
     "licenca": "trabalho livre; registros de depositantes podem ter termos próprios"},
    {"nome": "ClassyFire", "titulo": "ClassyFire (Wishart Lab)",
     "url": "http://classyfire.wishartlab.com",
     "licenca": "confirmar termos no site"},
    {"nome": "NPClassifier", "titulo": "NPClassifier (via COCONUT)",
     "url": "https://npclassifier.gnps2.org",
     "licenca": "ver COCONUT"},
]

PALAVRAS_CHAVE = ["produtos naturais", "compostos bioativos", "plantas", "fitoquímica",
                  "quimioinformática", "InChIKey", "ADMET", "drogabilidade", "ClassyFire",
                  "bioprospecção", "Brasil"]


def datapackage(nome="banco_bioativos", versao="3.20", extras: dict | None = None,
                licenca="CC-BY-SA-4.0", criado: str | None = None) -> str:
    recursos = []
    for tab, t in TABELAS.items():
        campos = [{"name": nome_coluna(c), "type": tipo, "description": descricao_coluna(c, d)}
                  for c, tipo, d in t["colunas"]]
        for c in (extras or {}).get(tab, []):
            campos.append({"name": c, "type": "any", "description": "ADMET-AI (optional)"})
        esquema = {"fields": campos, "primaryKey": [nome_coluna(c) for c in t["chave"]]}
        if t.get("estrangeiras"):
            esquema["foreignKeys"] = [
                {"fields": nome_coluna(c),
                 "reference": {"resource": nome_tabela(tab_ref), "fields": nome_coluna(ref)}}
                for c, tab_ref, ref in t["estrangeiras"]]
        recursos.append({"name": nome_tabela(tab), "path": f"{nome_tabela(tab)}.csv",
                         "profile": "tabular-data-resource",
                         "format": "csv", "encoding": "utf-8-sig", "description": t["descricao"],
                         "schema": esquema})
    licencas = {"CC-BY-SA-4.0": ("Creative Commons Attribution-ShareAlike 4.0 International",
                                 "https://creativecommons.org/licenses/by-sa/4.0/"),
                "CC-BY-4.0": ("Creative Commons Attribution 4.0 International",
                              "https://creativecommons.org/licenses/by/4.0/")}
    titulo_lic, path_lic = licencas.get(licenca, (licenca, ""))
    pacote = {
        "name": nome,
        "id": f"urn:prospeccao-bioativos:{versao}",
        "version": versao,
        "profile": "tabular-data-package",
        "title": ("Bioactive plant natural products database (prospecting pipeline)"
                  if IDIOMA == "en" else
                  "Banco de compostos bioativos de plantas (pipeline de prospecção)"),
        "description": ("Bioactive plant natural products integrated from public databases "
                        "and deduplicated by canonical InChIKey (compound_uid), with chemical "
                        "identity, provenance, biological origin, geographic distribution, "
                        "bioactivity, metabolic pathways, spectral metadata, druglikeness/ADMET "
                        "profile and conflicts between sources." if IDIOMA == "en" else
                        "Compostos bioativos de plantas integrados de bases públicas, "
                        "deduplicados por InChIKey canônico, com identidade química, "
                        "proveniência, origem biológica, distribuição, bioatividade, vias, "
                        "espectros, perfil ADMET e conflitos entre bases."),
        "keywords": PALAVRAS_CHAVE,
        "created": criado or "",
        "licenses": [{"name": licenca, "title": titulo_lic, "path": path_lic}] if licenca else [],
        "sources": [{"title": f"{f['titulo']} — licença: {f['licenca']}", "path": f["url"]}
                    for f in FONTES_META],
        "contributors": [{"title": "Projeto de prospecção de plantas e bioativos",
                          "role": "author"}],
        "resources": recursos,
    }
    return json.dumps(pacote, ensure_ascii=False, indent=2)


def proveniencia_md(versao="3.20", licenca="CC-BY-SA-4.0", criado: str | None = None) -> str:
    if IDIOMA == "en":
        return _provenance_md(versao, licenca, criado)
    out = ["# Proveniência e licenças", "",
           f"Banco gerado pelo pipeline de prospecção, versão {versao}"
           + (f", em {criado}" if criado else "") + ".", "",
           "## Licença do banco agregado", "",
           f"**{licenca}** (Creative Commons Attribution-ShareAlike 4.0). Ao redistribuir, "
           "cite as bases de origem (abaixo) e mantenha a mesma licença.", "",
           "> A licença do agregado é limitada pela fonte **mais restritiva** usada. O ChEMBL "
           "é CC-BY-SA; por isso CC-BY-SA-4.0 é a escolha compatível. Se você remover o ChEMBL "
           "(tabela `bioatividade.csv`, linhas com `fonte = ChEMBL`), pode reavaliar para uma "
           "licença menos restritiva.", "",
           "## Como citar", "",
           "Cite este banco **e** cada base de origem efetivamente usada na sua coleta "
           "(ver a coluna `base`/`fonte` nas tabelas e os registros em `fontes.csv`).", "",
           "## Bases de origem", "",
           "| Base | Descrição | Licença (confirmar na data da coleta) | Endereço |",
           "|---|---|---|---|"]
    for f in FONTES_META:
        out.append(f"| {f['nome']} | {f['titulo']} | {f['licenca']} | {f['url']} |")
    out += ["", "## Rastreabilidade", "",
            "Cada registro de cada base está em `fontes.csv` (coluna `base`, `id_na_base`, "
            "`url_registro`, `metodo_identificacao`), e o de-para dos InChIKeys de origem para "
            "o canônico está em `mapa_inchikey.csv`. Os conflitos entre bases, e como foram "
            "resolvidos, estão em `conflitos.csv`.", "",
            "> As licenças acima são de conhecimento geral e **mudam entre versões** de cada "
            "base. Confirme os termos vigentes no site de cada fonte na data em que você "
            "executou o pipeline."]
    return "\n".join(out) + "\n"


def _provenance_md(versao: str, licenca: str, criado: str | None) -> str:
    """Provenance and licences, in English (banco/ in its published form)."""
    out = ["# Provenance and licences", "",
           f"Database built by the bioprospecting pipeline, version {versao}"
           + (f", on {criado}" if criado else "") + ".", "",
           "## Licence of the aggregated database", "",
           f"**{licenca}** (Creative Commons Attribution-ShareAlike 4.0). When "
           "redistributing, cite the source databases listed below and keep the same "
           "licence.", "",
           "> The licence of the aggregate is bounded by the **most restrictive** source "
           "used. ChEMBL is CC-BY-SA, which is why CC-BY-SA-4.0 is the compatible choice. "
           "If you remove ChEMBL (table `compounds_bioactivity.csv`, rows with "
           "`source = ChEMBL`), you may reassess for a less restrictive licence.", "",
           "## How to cite", "",
           "Cite this database **and** every source database actually used in your run "
           "(see the `source_db` / `source` columns in the tables and the records in "
           f"`{nome_tabela('fontes')}.csv`).", "",
           "## Source databases", "",
           "| Database | Title | Licence (confirm on the date of collection) | Address |",
           "|---|---|---|---|"]
    for f in FONTES_META:
        out.append(f"| {f['nome']} | {f['titulo']} | {f['licenca']} | {f['url']} |")
    out += ["", "## Traceability", "",
            f"Every record of every source database is in `{nome_tabela('fontes')}.csv` "
            "(columns `source_db`, `id_in_source`, `source_url`, `identification_method`), "
            "and the mapping from incoming InChIKeys to the canonical one is in "
            f"`{nome_tabela('mapa_inchikey')}.csv`. Conflicts between sources, and how each "
            f"was resolved, are in `{nome_tabela('conflitos')}.csv`.", "",
            "> The licences above are general knowledge and **change between versions** of "
            "each database. Confirm the terms in force on the website of each source, for "
            "the date on which you ran the pipeline."]
    return "\n".join(out) + "\n"


def leia_me() -> str:
    """Texto do LEIA-ME.txt / README.txt, no idioma do banco."""
    t = {n: nome_tabela(n) for n in TABELAS}
    if IDIOMA == "en":
        linhas = [
            "BIOACTIVE PLANT NATURAL PRODUCTS DATABASE",
            "=========================================", "",
            "This folder is a tabular data package (Frictionless Data). Every CSV is",
            "UTF-8 with BOM, and they join on the canonical InChIKey",
            f"({t['compostos']}.{nome_coluna('inchikey')}); organisms join on",
            f"{nome_coluna('nome_cientifico')}.", "",
            "Start here:",
            f"  {nome_meta('ESQUEMA.md'):<30}  readable schema, with a diagram and every column",
            f"  {nome_meta('dicionario_dados.csv'):<30}  data dictionary (table, column, type,",
            "                                  keys, description in English and in Portuguese)",
            f"  {'datapackage.json':<30}  Frictionless descriptor (FAIR metadata,",
            "                                  licence, sources, primary and foreign keys)",
            f"  {nome_meta('PROVENIENCIA_E_LICENCAS.md'):<30}  licence of this database and of"
            " each",
            "                                  source; how to cite", "",
            "Tables:",
            f"  {t['compostos']}.csv          chemical identity (one row per InChIKey)",
            f"  {t['fontes']}.csv                  traceability: each record of each source",
            f"  {t['sinonimos']}.csv                 synonyms and names",
            f"  {t['organismos']}.csv                        producing organisms (taxonomy, distribution)",
            f"  {t['origem_biologica']}.csv   compound x organism",
            f"  {t['distribuicao_geografica']}.csv  compound x organism x Brazilian state",
            f"  {t['bioatividade']}.csv            measurements (ChEMBL/NPASS) and reports (PubMed)",
            f"  {t['vias_metabolicas']}.csv               pathways (PubChem) and biosynthetic pathway",
            "                                             (NPClassifier)",
            f"  {t['dados_espectrais']}.csv                spectral metadata (PubChem) and theoretical",
            "                                             m/z (RDKit)",
            f"  {t['perfil_admet']}.csv  druglikeness and basic ADMET (RDKit) - PREDICTIONS",
            f"  {t['conflitos']}.csv                          conflicts between sources and the",
            "                                             resolution adopted",
            f"  {t['mapa_inchikey']}.csv                       incoming InChIKey -> canonical", "",
            "The folder qualidade/ holds the quality and coverage analysis of the database",
            "(field completeness by source, chemical space, taxonomic coverage, overlap",
            f"between sources and signs of curation bias), with {nome_meta('RELATORIO_QUALIDADE.md')}.",
            "", "Validation (optional):",
            "  pip install frictionless && frictionless validate datapackage.json",
            f'In Python/pandas: pd.read_csv("banco/{t["compostos"]}.csv")', "",
            "The ADMET profile is computed from physico-chemical rules (RDKit): these are",
            "estimates for triage and do not replace assays.", ""]
        return "\n".join(linhas)
    linhas = [
        "BANCO DE COMPOSTOS BIOATIVOS DE PLANTAS",
        "=======================================", "",
        "Esta pasta é um pacote de dados tabular (Frictionless Data). Todos os CSVs são",
        f"UTF-8 com BOM e se interligam pelo InChIKey canônico ({t['compostos']}.inchikey);",
        "os organismos se ligam pelo nome_cientifico.", "",
        "Comece por:",
        "  ESQUEMA.md                 esquema legível, com diagrama e a lista de colunas",
        "  dicionario_dados.csv       dicionário de dados (tabela, coluna, tipo, chaves,",
        "                             descrição em português e em inglês)",
        "  datapackage.json           descritor Frictionless (metadados FAIR, licença,",
        "                             fontes, chaves)",
        "  PROVENIENCIA_E_LICENCAS.md licença do banco e das bases de origem; como citar", "",
        "Tabelas:",
        f"  {t['compostos']}.csv                identidade química (uma linha por InChIKey)",
        f"  {t['fontes']}.csv                   rastreabilidade: cada registro de cada base",
        f"  {t['sinonimos']}.csv                sinônimos e nomes",
        f"  {t['organismos']}.csv               organismos produtores (taxonomia, distribuição)",
        f"  {t['origem_biologica']}.csv         composto x organismo",
        f"  {t['distribuicao_geografica']}.csv  composto x organismo x UF",
        f"  {t['bioatividade']}.csv             medidas (ChEMBL/NPASS) e relatos (PubMed)",
        f"  {t['vias_metabolicas']}.csv         vias (PubChem) e via biossintética (NPClassifier)",
        f"  {t['dados_espectrais']}.csv         espectros (PubChem) e m/z teóricos (RDKit)",
        f"  {t['perfil_admet']}.csv             drogabilidade e ADMET básico (RDKit) - PREVISÕES",
        f"  {t['conflitos']}.csv                conflitos entre bases e a resolução adotada",
        f"  {t['mapa_inchikey']}.csv            de-para dos InChIKeys de origem para o canônico", "",
        "A pasta qualidade/ traz a análise de qualidade e cobertura do banco (completude",
        "por base, espaço químico, cobertura taxonômica, sobreposição entre bases e sinais",
        "de viés de curadoria), com RELATORIO_QUALIDADE.md.", "",
        "Validação (opcional):",
        "  pip install frictionless && frictionless validate datapackage.json",
        f'Em Python/pandas: pd.read_csv("banco/{t["compostos"]}.csv")', "",
        "O perfil ADMET é calculado por regras físico-químicas (RDKit): são estimativas",
        "para triagem, não substituem ensaios.", ""]
    return "\n".join(linhas)


def esquema_md(contagens: dict | None = None) -> str:
    contagens = contagens or {}
    chave = f"`{nome_tabela('compostos')}.{nome_coluna('inchikey')}`"
    if IDIOMA == "en":
        out = ["# Schema of the bioactive natural products database", "",
               "CSV files (UTF-8 with BOM) joined by the **canonical InChIKey** "
               f"({chave}). Organisms join on `{nome_coluna('nome_cientifico')}`. "
               "The same schema is in `datapackage.json` (Frictionless Data) and in "
               f"`{nome_meta('dicionario_dados.csv')}`.", "",
               "**FAIR**: a universal canonical identifier (InChIKey) and standardised "
               "external identifiers (PubChem CID, ChEMBL, ClassyFire, NPClassifier); open "
               "format; machine-readable schema and dictionary (`datapackage.json`); "
               f"per-record provenance in `{nome_tabela('fontes')}.csv`; licences and source "
               f"databases in `{nome_meta('PROVENIENCIA_E_LICENCAS.md')}`.", "",
               "```mermaid", "erDiagram"]
    else:
        out = ["# Esquema do banco de compostos bioativos", "",
               "Arquivos CSV (UTF-8 com BOM) interligados pelo **InChIKey canônico** "
               f"({chave}). Os organismos se ligam "
               f"pelo `{nome_coluna('nome_cientifico')}`. "
               "O mesmo esquema está em `datapackage.json` (Frictionless Data) e em "
               "`dicionario_dados.csv`.", "",
               "**FAIR**: identificador canônico universal (InChIKey) e identificadores "
               "externos padronizados (PubChem CID, ChEMBL, ClassyFire, NPClassifier); formato "
               "aberto; esquema e dicionário legíveis por máquina (`datapackage.json`); "
               f"proveniência por registro em `{nome_tabela('fontes')}.csv`; licenças e bases de origem em "
               "`PROVENIENCIA_E_LICENCAS.md`.", "", "```mermaid", "erDiagram"]
    for tab, t in TABELAS.items():
        for c, tab_ref, ref in t.get("estrangeiras", []):
            out.append(f"    {nome_tabela(tab_ref)} ||--o{{ {nome_tabela(tab)} : "
                       f"\"{nome_coluna(c)}\"")
    out += ["```", ""]
    en = IDIOMA == "en"
    rot = {"linhas": "rows" if en else "linhas",
           "chave": "Key" if en else "Chave",
           "refs": "References" if en else "Referências",
           "cab": "| Column | Type | Description |" if en else "| Coluna | Tipo | Descrição |",
           "conf": "## Conflict types" if en else "## Tipos de conflito",
           "conf_cab": "| Type | Meaning |" if en else "| Tipo | Significado |"}
    for tab, t in TABELAS.items():
        n = contagens.get(tab)
        out += [f"## {nome_tabela(tab)}.csv"
                + (f" ({n} {rot['linhas']})" if n is not None else ""), "",
                descricao_tabela(tab), "",
                f"{rot['chave']}: `{', '.join(nome_coluna(c) for c in t['chave'])}`"]
        if t.get("estrangeiras"):
            out.append(f"{rot['refs']}: " + "; ".join(
                f"`{nome_coluna(c)}` → `{nome_tabela(tr)}.{nome_coluna(r)}`"
                for c, tr, r in t["estrangeiras"]))
        out += ["", rot["cab"], "|---|---|---|"]
        out += [f"| `{nome_coluna(c)}` | {tipo} | {descricao_coluna(c, d)} |"
                for c, tipo, d in t["colunas"]]
        out.append("")
    out += [rot["conf"], "", rot["conf_cab"], "|---|---|"]
    out += [f"| `{TIPOS_CONFLITO_EN_VALOR.get(k, k) if en else k}` | "
            f"{descricao_conflito(k)} |" for k in TIPOS_CONFLITO]
    return "\n".join(out) + "\n"
