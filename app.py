"""
AdControl Web - API e telas para gestao de publicidade digital
Projeto Integrador II - FATEC Ipiranga

Modulos ja implementados:
  - Campanhas (RF02)
  - Anuncios (RF03): ligam um Produto a uma Campanha
  - Produtos (RF04)
  - Investimentos (RF01)
  - Metricas (RF05)
  - Indicadores calculados automaticamente (RF06): CTR, CPC, taxa de
    conversao, custo por venda e ROAS (formulas em analise.py)
  - Dashboard com graficos (RF07)
  - Filtros por campanha e periodo (RF08)
  - Comparacao de campanhas, anuncios e periodos (RF09)
  - Historico de resultados por dia
  - Tela de Indicadores, Relatorios gerenciais e exportacao CSV (Excel e Power BI)
  - Edicao de campanhas, produtos e anuncios; exclusao de investimentos e metricas
  - Acesso restrito por login (RNF03): senha com hash, protecao CSRF e chave de API opcional
"""

import hmac
import math
import os
import secrets
import time
from datetime import datetime

from flask import Flask, Response, render_template, request, redirect, session, url_for, jsonify, flash
from werkzeug.security import check_password_hash, generate_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from bson.errors import InvalidId

import relatorios
from analise import (
    calcular_resumo, comparar_periodos, dividir, geometria_linhas,
    montar_funil, no_periodo, serie_diaria,
)

app = Flask(__name__)

# Chave usada pelo Flask para guardar as mensagens de aviso da tela.
# Em uso real, defina a variavel de ambiente SECRET_KEY com um valor proprio.
app.secret_key = os.environ.get("SECRET_KEY", "dev-adcontrol-troque-esta-chave")

# Endereco do MongoDB. Por padrao aponta para um MongoDB local.
# Para usar o MongoDB Atlas (gratuito, na nuvem), defina a variavel de
# ambiente MONGO_URI com a string de conexao fornecida pelo Atlas.
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/adcontrol_web")

# ---------- SEGURANCA (RNF03) ----------
# Os dois recursos ficam ligados por padrao. Os testes automaticos desligam para cada bloco.
app.config.update(
    AUTENTICACAO_ATIVA=os.environ.get("AUTENTICACAO", "ligada") != "desligada",
    CSRF_ATIVO=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIES_SEGUROS") == "1",   # use 1 quando o site estiver em https
)

client = MongoClient(MONGO_URI)
db = client.get_default_database()
campanhas_collection = db["campanhas"]
produtos_collection = db["produtos"]
anuncios_collection = db["anuncios"]
investimentos_collection = db["investimentos"]
metricas_collection = db["metricas"]
usuarios_collection = db["usuarios"]


# ---------- LOGIN, SESSAO E CSRF (RNF03) ----------

ENDPOINTS_LIVRES = {"static", "login", "primeiro_acesso"}
TENTATIVAS_LOGIN = {}          # (usuario, ip) -> (quantidade, instante da primeira falha)
MAX_TENTATIVAS, JANELA_SEGUNDOS = 5, 300


def ha_usuarios():
    return usuarios_collection.find_one() is not None


def chave_api_valida():
    """Clientes como Excel e Power BI podem usar a variavel API_KEY no cabecalho X-API-Key."""
    esperada = os.environ.get("API_KEY", "")
    enviada = request.headers.get("X-API-Key", "")
    return bool(esperada) and hmac.compare_digest(esperada, enviada)


def gerar_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = gerar_csrf


@app.before_request
def proteger_acesso():
    """Exige login em todas as telas e na API; confere o token CSRF em todo POST de formulario."""
    if request.endpoint is None:
        return None
    eh_api = request.path.startswith("/api/")

    if app.config["AUTENTICACAO_ATIVA"] and request.endpoint not in ENDPOINTS_LIVRES:
        autenticado = bool(session.get("usuario_id")) or (eh_api and chave_api_valida())
        if not autenticado:
            if eh_api:
                return jsonify({"erro": "Não autenticado. Entre no sistema ou envie o cabeçalho X-API-Key."}), 401
            if not ha_usuarios():
                return redirect(url_for("primeiro_acesso"))
            proximo = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("login", proximo=proximo))

    if app.config["CSRF_ATIVO"] and request.method == "POST" and not eh_api:
        esperado = session.get("csrf", "")
        enviado = request.form.get("_csrf", "")
        if not esperado or not hmac.compare_digest(esperado, enviado):
            flash("A sessão expirou ou o formulário é inválido. Tente novamente.", "erro")
            return redirect(request.referrer or url_for("home"))
    return None


def destino_seguro(destino):
    """So aceita caminhos internos (evita redirecionar para outro site)."""
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return url_for("home")


def entrar(usuario):
    session.clear()
    session["usuario_id"] = str(usuario["_id"])
    session["usuario_nome"] = usuario.get("nome", "")
    gerar_csrf()


@app.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    """Cria o primeiro usuario. Depois que existir um usuario, esta tela deixa de funcionar."""
    if ha_usuarios():
        return redirect(url_for("login"))
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        usuario = request.form.get("usuario", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmacao = request.form.get("confirmacao", "")
        if not nome or not usuario:
            flash("Informe o seu nome e um nome de usuário.", "erro")
        elif len(senha) < 8:
            flash("A senha precisa ter pelo menos 8 caracteres.", "erro")
        elif senha != confirmacao:
            flash("A confirmação não confere com a senha.", "erro")
        else:
            doc = {"nome": nome, "usuario": usuario, "criado_em": datetime.utcnow(),
                   "senha_hash": generate_password_hash(senha, method="pbkdf2:sha256")}
            doc["_id"] = usuarios_collection.insert_one(doc).inserted_id
            entrar(doc)
            flash(f"Bem-vindo, {nome}. Seu acesso foi criado.", "sucesso")
            return redirect(url_for("home"))
    return render_template("primeiro_acesso.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ha_usuarios():
        return redirect(url_for("primeiro_acesso"))
    proximo = request.values.get("proximo", "")
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip().lower()
        chave = (usuario, request.remote_addr)
        qtd, inicio = TENTATIVAS_LOGIN.get(chave, (0, time.time()))
        if time.time() - inicio > JANELA_SEGUNDOS:
            qtd, inicio = 0, time.time()
        if qtd >= MAX_TENTATIVAS:
            flash("Muitas tentativas seguidas. Aguarde alguns minutos e tente de novo.", "erro")
            return render_template("login.html", proximo=proximo), 429
        doc = usuarios_collection.find_one({"usuario": usuario})
        if doc and check_password_hash(doc.get("senha_hash", ""), request.form.get("senha", "")):
            TENTATIVAS_LOGIN.pop(chave, None)
            entrar(doc)
            return redirect(destino_seguro(proximo))
        TENTATIVAS_LOGIN[chave] = (qtd + 1, inicio)
        flash("Usuário ou senha incorretos.", "erro")
    return render_template("login.html", proximo=proximo)


@app.route("/sair", methods=["POST"])
def sair():
    session.clear()
    flash("Você saiu do sistema.", "sucesso")
    return redirect(url_for("login"))


# ---------- FORMATACAO PARA AS TELAS (padrao brasileiro) ----------

def _formatar(valor, casas):
    """1234.5 -> '1.234,50' (separador de milhar com ponto, decimal com virgula)."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


@app.template_filter("brl")
def filtro_brl(valor):
    return "R$ " + _formatar(valor or 0, 2)


@app.template_filter("decimal")
def filtro_decimal(valor, casas=2):
    return _formatar(valor or 0, casas)


@app.template_filter("numero")
def filtro_numero(valor):
    return _formatar(int(valor or 0), 0)


@app.template_filter("data_br")
def filtro_data_br(valor):
    """'2026-11-20' -> '20/11/2026'."""
    if not valor:
        return "—"
    try:
        return datetime.strptime(valor, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return valor


# ---------- FUNCOES AUXILIARES ----------

def para_numero(valor, padrao=0.0):
    """
    Converte texto em numero. Aceita '1500', '1500.50' e '1500,50'.
    Campo vazio devolve o padrao. Devolve None se for invalido ou negativo
    (RNF04 - integridade dos dados).
    """
    if valor is None:
        return padrao
    texto = str(valor).strip()
    if texto == "":
        return padrao
    try:
        numero = float(texto.replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(numero) or numero < 0:
        return None
    return numero


def buscar_por_id(colecao, documento_id):
    """Busca um documento pelo id. Devolve None se o id for invalido ou nao existir."""
    if not documento_id:
        return None
    try:
        return colecao.find_one({"_id": ObjectId(documento_id)})
    except (InvalidId, TypeError):
        return None


def novo_doc_campanha(nome, data_inicio, data_fim, orcamento, status="ativa"):
    """Monta o documento de uma campanha nova, com totais e indicadores zerados."""
    return {
        "nome": nome,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "orcamento_planejado": orcamento,
        "status": status,
        "total_investido": 0.0,
        "total_impressoes": 0,
        "total_cliques": 0,
        "total_visitas": 0,
        "total_vendas": 0,
        "total_receita": 0.0,
        "ctr": 0.0,
        "cpc": 0.0,
        "taxa_conversao": 0.0,
        "custo_por_venda": 0.0,
        "roas": 0.0,
        "criado_em": datetime.utcnow(),
    }


def validar_periodo(data_inicio, data_fim):
    """A data de fim nao pode ser anterior a data de inicio (RNF04)."""
    if data_inicio and data_fim and data_fim < data_inicio:
        return "A data de fim não pode ser anterior à data de início."
    return None


def enriquecer_campanha(campanha):
    """Acrescenta os dados de uso do orcamento (RF01) usados nas telas."""
    orcamento = campanha.get("orcamento_planejado") or 0
    investido = campanha.get("total_investido") or 0
    percentual = round(investido / orcamento * 100) if orcamento else 0
    campanha["uso_pct"] = min(percentual, 100)
    campanha["uso_texto"] = percentual
    campanha["estourou"] = orcamento > 0 and investido > orcamento
    return campanha


STATUS_CAMPANHA = ["ativa", "pausada", "encerrada"]
STATUS_ANUNCIO = ["ativo", "pausado", "encerrado"]


def numero_para_campo(valor):
    """89.9 -> '89,90' (para preencher campos de formulario no padrao brasileiro)."""
    return f"{(valor or 0):.2f}".replace(".", ",")


ROTULOS_METRICA = {
    "impressoes": "impressões",
    "cliques": "cliques",
    "visitas": "visitas",
    "vendas": "vendas",
}


def montar_metrica(campanha_id, data, brutos):
    """
    Valida e monta o documento de uma metrica (RF05).
    'brutos' pode ser o formulario da tela ou o JSON da API.
    Devolve (documento, None) se estiver tudo certo ou (None, mensagem_de_erro).
    """
    doc = {"campanha_id": campanha_id, "data": data, "criado_em": datetime.utcnow()}

    for campo, rotulo in ROTULOS_METRICA.items():
        valor = para_numero(brutos.get(campo))
        if valor is None:
            return None, f"Valor inválido em {rotulo}. Use apenas números positivos."
        doc[campo] = int(valor)

    # O anuncio e opcional, mas se vier precisa existir e pertencer a mesma campanha.
    anuncio_id = brutos.get("anuncio_id") or ""
    if anuncio_id:
        anuncio = buscar_por_id(anuncios_collection, anuncio_id)
        if not anuncio:
            return None, "Anúncio inválido ou não encontrado."
        if anuncio.get("campanha_id") != campanha_id:
            return None, "O anúncio selecionado não pertence a esta campanha."
        doc["anuncio_id"] = anuncio_id
    else:
        doc["anuncio_id"] = None

    receita = para_numero(brutos.get("receita_atribuida"))
    if receita is None:
        return None, "Receita inválida. Use apenas números, com vírgula ou ponto para os centavos."
    doc["receita_atribuida"] = receita

    if doc["cliques"] > doc["impressoes"]:
        return None, "Os cliques não podem ser maiores que as impressões."

    return doc, None


def campanha_para_dict(campanha):
    """Converte um documento do Mongo em um dicionario simples (JSON-friendly)."""
    return {
        "id": str(campanha["_id"]),
        "nome": campanha.get("nome"),
        "data_inicio": campanha.get("data_inicio"),
        "data_fim": campanha.get("data_fim"),
        "orcamento_planejado": campanha.get("orcamento_planejado"),
        "status": campanha.get("status"),
        "total_investido": campanha.get("total_investido", 0),
        "total_impressoes": campanha.get("total_impressoes", 0),
        "total_cliques": campanha.get("total_cliques", 0),
        "total_visitas": campanha.get("total_visitas", 0),
        "total_vendas": campanha.get("total_vendas", 0),
        "total_receita": campanha.get("total_receita", 0),
        "ctr": campanha.get("ctr", 0),
        "cpc": campanha.get("cpc", 0),
        "taxa_conversao": campanha.get("taxa_conversao", 0),
        "custo_por_venda": campanha.get("custo_por_venda", 0),
        "roas": campanha.get("roas", 0),
    }


def produto_para_dict(produto):
    return {
        "id": str(produto["_id"]),
        "nome": produto.get("nome"),
        "categoria": produto.get("categoria"),
        "preco_unitario": produto.get("preco_unitario"),
    }


def anuncio_para_dict(anuncio):
    return {
        "id": str(anuncio["_id"]),
        "titulo": anuncio.get("titulo"),
        "codigo_marketplace": anuncio.get("codigo_marketplace"),
        "campanha_id": anuncio.get("campanha_id"),
        "produto_id": anuncio.get("produto_id"),
        "status": anuncio.get("status"),
    }


def totais_por_anuncio():
    """
    Soma as metricas de cada anuncio (RF03 - acompanhamento individual).
    Devolve {anuncio_id: {impressoes, cliques, visitas, vendas, receita, ctr}}.
    So considera metricas que foram registradas com um anuncio.
    """
    totais = {}
    for m in metricas_collection.find():
        aid = m.get("anuncio_id")
        if not aid:
            continue
        t = totais.setdefault(aid, {"impressoes": 0, "cliques": 0, "visitas": 0, "vendas": 0, "receita": 0.0})
        t["impressoes"] += m.get("impressoes", 0) or 0
        t["cliques"] += m.get("cliques", 0) or 0
        t["visitas"] += m.get("visitas", 0) or 0
        t["vendas"] += m.get("vendas", 0) or 0
        t["receita"] += m.get("receita_atribuida", 0) or 0
    for t in totais.values():
        t["ctr"] = round(t["cliques"] / t["impressoes"] * 100, 2) if t["impressoes"] else 0.0
    return totais


SEM_TOTAIS = {"impressoes": 0, "cliques": 0, "visitas": 0, "vendas": 0, "receita": 0.0, "ctr": 0.0}


def investimento_para_dict(investimento):
    return {
        "id": str(investimento["_id"]),
        "campanha_id": investimento.get("campanha_id"),
        "data": investimento.get("data"),
        "investimento": investimento.get("investimento"),
    }


def metrica_para_dict(metrica):
    return {
        "id": str(metrica["_id"]),
        "campanha_id": metrica.get("campanha_id"),
        "anuncio_id": metrica.get("anuncio_id"),
        "data": metrica.get("data"),
        "impressoes": metrica.get("impressoes"),
        "cliques": metrica.get("cliques"),
        "visitas": metrica.get("visitas"),
        "vendas": metrica.get("vendas"),
        "receita_atribuida": metrica.get("receita_atribuida"),
    }


def recalcular_indicadores(campanha_id):
    """
    RF06 - Recalcula os totais e os indicadores (CTR, CPC, taxa de conversao,
    custo por venda, ROAS) de uma campanha a partir dos registros existentes
    em Investimentos e Metricas, e grava o resultado na propria campanha.

    E chamada sempre que um investimento ou uma metrica e registrado
    (RF01 e RF05) - e o mesmo relacionamento "<<include>> Calcular
    indicadores" do diagrama de casos de uso e de atividades.
    """
    investimentos = list(investimentos_collection.find({"campanha_id": campanha_id}))
    metricas = list(metricas_collection.find({"campanha_id": campanha_id}))
    r = calcular_resumo(investimentos, metricas)   # RNF09: trata divisao por zero

    campanhas_collection.update_one(
        {"_id": ObjectId(campanha_id)},
        {"$set": {
            "total_investido": r["investido"],
            "total_impressoes": r["impressoes"],
            "total_cliques": r["cliques"],
            "total_visitas": r["visitas"],
            "total_vendas": r["vendas"],
            "total_receita": r["receita"],
            "ctr": r["ctr"],
            "cpc": r["cpc"],
            "taxa_conversao": r["taxa_conversao"],
            "custo_por_venda": r["custo_por_venda"],
            "roas": r["roas"],
        }},
    )


# ---------- FILTROS E CONSULTAS (RF08) ----------

def filtros_da_requisicao():
    """Le campanha, 'de' e 'ate' da URL. Devolve (campanha_id, data_ini, data_fim, erro)."""
    campanha_id = request.args.get("campanha_id", "")
    data_ini = request.args.get("de", "")
    data_fim = request.args.get("ate", "")

    erro = validar_periodo(data_ini, data_fim)
    if not erro and campanha_id and not buscar_por_id(campanhas_collection, campanha_id):
        erro = "Campanha do filtro não encontrada."
    return campanha_id, data_ini, data_fim, erro


def ler_filtros():
    """Para as telas: se o filtro for invalido, avisa e mostra tudo sem filtro."""
    campanha_id, data_ini, data_fim, erro = filtros_da_requisicao()
    if erro:
        flash(erro + " Mostrando tudo, sem filtro.", "erro")
        return "", "", ""
    return campanha_id, data_ini, data_fim


def registros_filtrados(campanha_id="", data_ini="", data_fim=""):
    """Investimentos e metricas que atendem ao filtro de campanha e periodo."""
    consulta = {"campanha_id": campanha_id} if campanha_id else {}
    investimentos = [i for i in investimentos_collection.find(consulta) if no_periodo(i, data_ini, data_fim)]
    metricas = [m for m in metricas_collection.find(consulta) if no_periodo(m, data_ini, data_fim)]
    return investimentos, metricas


def escalar_barras(itens, chaves):
    """Acrescenta a cada item a largura (%) de cada barra, proporcional ao maior valor."""
    maximo = max([i[c] for i in itens for c in chaves] + [0]) or 1
    for item in itens:
        for chave in chaves:
            item["w_" + chave] = round(item[chave] / maximo * 100, 1)
    return itens


# ---------- DASHBOARD (RF07) ----------

def montar_dashboard(campanha_id, data_ini, data_fim):
    """Reune os numeros e graficos do dashboard, respeitando os filtros."""
    investimentos, metricas = registros_filtrados(campanha_id, data_ini, data_fim)
    resumo = calcular_resumo(investimentos, metricas)
    serie = serie_diaria(investimentos, metricas)

    nomes_campanha = {str(c["_id"]): c.get("nome") for c in campanhas_collection.find()}
    anuncios = {str(a["_id"]): a for a in anuncios_collection.find()}
    nomes_produto = {str(p["_id"]): p.get("nome") for p in produtos_collection.find()}

    if campanha_id:
        # Com uma campanha escolhida, o que interessa e qual anuncio rendeu mais.
        receita = {}
        for m in metricas:
            chave = m.get("anuncio_id")
            receita[chave] = receita.get(chave, 0) + (m.get("receita_atribuida") or 0)
        itens = [
            {"nome": anuncios[k]["titulo"] if k in anuncios else "Sem anúncio específico", "receita": v}
            for k, v in receita.items()
        ]
        itens.sort(key=lambda i: i["receita"], reverse=True)
        barras = {"titulo": "Receita por anúncio", "duplo": False, "itens": escalar_barras(itens, ["receita"])}
    else:
        por = {}
        for i in investimentos:
            por.setdefault(i.get("campanha_id"), {"investido": 0.0, "receita": 0.0})["investido"] += i.get("investimento", 0) or 0
        for m in metricas:
            por.setdefault(m.get("campanha_id"), {"investido": 0.0, "receita": 0.0})["receita"] += m.get("receita_atribuida", 0) or 0
        itens = [
            {"nome": nomes_campanha.get(k, "(campanha removida)"), **v, "roas": round(dividir(v["receita"], v["investido"]), 2)}
            for k, v in por.items()
        ]
        itens.sort(key=lambda i: i["receita"], reverse=True)
        barras = {"titulo": "Investido x receita por campanha", "duplo": True,
                  "itens": escalar_barras(itens, ["investido", "receita"])}

    por_produto = {}
    for m in metricas:
        anuncio = anuncios.get(m.get("anuncio_id"))
        if anuncio:
            nome = nomes_produto.get(anuncio.get("produto_id"), "(produto removido)")
            por_produto[nome] = por_produto.get(nome, 0) + (m.get("receita_atribuida") or 0)
    produtos = [{"nome": k, "receita": v} for k, v in por_produto.items()]
    produtos.sort(key=lambda i: i["receita"], reverse=True)

    return {
        "resumo": resumo,
        "serie": serie,
        "grafico": geometria_linhas(serie),
        "funil": montar_funil(resumo),
        "barras": barras,
        "produtos": escalar_barras(produtos, ["receita"]),
        "tem_dados": bool(investimentos or metricas),
    }


# ---------- COMPARACOES (RF09) ----------

def ranking_campanhas():
    """Campanhas ordenadas por ROAS. Devolve (com_investimento, sem_investimento, posicao_do_ROAS_1)."""
    linhas = []
    for c in campanhas_collection.find():
        linhas.append({
            "nome": c.get("nome"),
            "status": c.get("status"),
            "investido": c.get("total_investido", 0) or 0,
            "receita": c.get("total_receita", 0) or 0,
            "vendas": c.get("total_vendas", 0) or 0,
            "roas": c.get("roas", 0) or 0,
            "ctr": c.get("ctr", 0) or 0,
            "cpc": c.get("cpc", 0) or 0,
            "taxa_conversao": c.get("taxa_conversao", 0) or 0,
            "custo_por_venda": c.get("custo_por_venda", 0) or 0,
        })

    com = sorted((l for l in linhas if l["investido"] > 0), key=lambda l: l["roas"], reverse=True)
    sem = [l for l in linhas if l["investido"] <= 0]

    escala = max([l["roas"] for l in com] + [1.0]) * 1.1
    for posicao, linha in enumerate(com, 1):
        linha["posicao"] = posicao
        linha["largura"] = round(linha["roas"] / escala * 100, 1)
        linha["abaixo_do_custo"] = linha["roas"] < 1      # receita menor que o investimento
        linha["tag"] = ""
    if len(com) >= 2:
        com[0]["tag"] = "melhor"
        if com[-1]["roas"] < com[0]["roas"]:
            com[-1]["tag"] = "pior"
    return com, sem, round(1 / escala * 100, 1)


def ranking_anuncios(campanha_id=""):
    """Anuncios ordenados por receita, com CTR, conversao e ticket medio."""
    totais = totais_por_anuncio()
    nomes_campanha = {str(c["_id"]): c.get("nome") for c in campanhas_collection.find()}
    nomes_produto = {str(p["_id"]): p.get("nome") for p in produtos_collection.find()}

    consulta = {"campanha_id": campanha_id} if campanha_id else {}
    linhas = []
    for a in anuncios_collection.find(consulta):
        t = totais.get(str(a["_id"]), SEM_TOTAIS)
        linhas.append({
            "titulo": a.get("titulo"),
            "campanha": nomes_campanha.get(a.get("campanha_id"), "(campanha removida)"),
            "produto": nomes_produto.get(a.get("produto_id"), "(produto removido)"),
            **t,
            "conversao": round(dividir(t["vendas"], t["visitas"]) * 100, 2),
            "ticket": round(dividir(t["receita"], t["vendas"]), 2),
            "tags": [],
        })
    linhas.sort(key=lambda l: l["receita"], reverse=True)

    com_dados = [l for l in linhas if l["impressoes"] > 0]
    if len(com_dados) >= 2:
        maior_receita = max(com_dados, key=lambda l: l["receita"])
        maior_ctr = max(com_dados, key=lambda l: l["ctr"])
        maior_receita["tags"].append("Maior receita")
        maior_ctr["tags"].append("Maior CTR")
    return linhas


# ---------- TELAS (paginas HTML) ----------

@app.route("/")
def home():
    """Visao geral: numeros consolidados e campanhas mais recentes."""
    campanhas = [enriquecer_campanha(c) for c in campanhas_collection.find()]

    total_investido = sum(c.get("total_investido", 0) or 0 for c in campanhas)
    total_receita = sum(c.get("total_receita", 0) or 0 for c in campanhas)
    resumo = {
        "total_investido": total_investido,
        "total_orcamento": sum(c.get("orcamento_planejado", 0) or 0 for c in campanhas),
        "total_receita": total_receita,
        "total_vendas": sum(c.get("total_vendas", 0) or 0 for c in campanhas),
        "roas_geral": (total_receita / total_investido) if total_investido else 0.0,
        "campanhas_ativas": sum(1 for c in campanhas if c.get("status") == "ativa"),
        "total_campanhas": len(campanhas),
    }

    recentes = sorted(
        campanhas, key=lambda c: c.get("criado_em") or datetime.min, reverse=True
    )[:5]
    return render_template("index.html", resumo=resumo, recentes=recentes)


@app.route("/campanhas")
def tela_campanhas():
    campanhas = [
        enriquecer_campanha(c)
        for c in campanhas_collection.find().sort("data_inicio", -1)
    ]
    return render_template("campanhas.html", campanhas=campanhas)


@app.route("/campanhas/nova", methods=["POST"])
def criar_campanha_tela():
    """RF02 - cadastra uma campanha a partir do formulario."""
    nome = request.form.get("nome", "").strip()
    data_inicio = request.form.get("data_inicio", "")
    data_fim = request.form.get("data_fim", "")
    orcamento = para_numero(request.form.get("orcamento_planejado"))

    if not nome:
        flash("Informe o nome da campanha.", "erro")
    elif orcamento is None:
        flash("Orçamento inválido. Use apenas números, com vírgula ou ponto para os centavos (ex: 1500,50).", "erro")
    elif validar_periodo(data_inicio, data_fim):
        flash(validar_periodo(data_inicio, data_fim), "erro")
    else:
        campanhas_collection.insert_one(novo_doc_campanha(nome, data_inicio, data_fim, orcamento))
        flash(f"Campanha “{nome}” cadastrada.", "sucesso")

    return redirect(url_for("tela_campanhas"))


@app.route("/produtos")
def tela_produtos():
    produtos = list(produtos_collection.find().sort("nome", 1))

    # Desempenho de cada produto = soma do desempenho dos anuncios que o divulgam.
    totais = totais_por_anuncio()
    for p in produtos:
        p["n_anuncios"] = 0
        p["vendas"] = 0
        p["receita"] = 0.0
        p["impressoes"] = 0
    por_id = {str(p["_id"]): p for p in produtos}
    for a in anuncios_collection.find():
        p = por_id.get(a.get("produto_id"))
        if not p:
            continue
        t = totais.get(str(a["_id"]), SEM_TOTAIS)
        p["n_anuncios"] += 1
        p["vendas"] += t["vendas"]
        p["receita"] += t["receita"]
        p["impressoes"] += t["impressoes"]
    return render_template("produtos.html", produtos=produtos)


@app.route("/produtos/novo", methods=["POST"])
def criar_produto_tela():
    """RF04 - cadastra um produto a partir do formulario."""
    nome = request.form.get("nome", "").strip()
    categoria = request.form.get("categoria", "").strip()
    preco = para_numero(request.form.get("preco_unitario"))

    if not nome:
        flash("Informe o nome do produto.", "erro")
    elif preco is None:
        flash("Preço inválido. Use apenas números, com vírgula ou ponto para os centavos (ex: 89,90).", "erro")
    else:
        produtos_collection.insert_one({
            "nome": nome,
            "categoria": categoria,
            "preco_unitario": preco,
            "criado_em": datetime.utcnow(),
        })
        flash(f"Produto “{nome}” cadastrado.", "sucesso")

    return redirect(url_for("tela_produtos"))


@app.route("/anuncios")
def tela_anuncios():
    campanhas = list(campanhas_collection.find().sort("nome", 1))
    produtos = list(produtos_collection.find().sort("nome", 1))
    nomes_campanha = {str(c["_id"]): c.get("nome") for c in campanhas}
    nomes_produto = {str(p["_id"]): p.get("nome") for p in produtos}

    totais = totais_por_anuncio()
    anuncios = list(anuncios_collection.find().sort("titulo", 1))
    for a in anuncios:
        a["campanha_nome"] = nomes_campanha.get(a.get("campanha_id"), "(campanha removida)")
        a["produto_nome"] = nomes_produto.get(a.get("produto_id"), "(produto removido)")
        a["totais"] = totais.get(str(a["_id"]), SEM_TOTAIS)

    return render_template("anuncios.html", campanhas=campanhas, produtos=produtos, anuncios=anuncios)


@app.route("/anuncios/novo", methods=["POST"])
def criar_anuncio_tela():
    """RF03 - cadastra um anuncio ligado a uma campanha e a um produto."""
    titulo = request.form.get("titulo", "").strip()
    codigo = request.form.get("codigo_marketplace", "").strip()
    campanha_id = request.form.get("campanha_id", "")
    produto_id = request.form.get("produto_id", "")

    if not titulo:
        flash("Informe o título do anúncio.", "erro")
    elif not buscar_por_id(campanhas_collection, campanha_id):
        flash("Selecione uma campanha válida.", "erro")
    elif not buscar_por_id(produtos_collection, produto_id):
        flash("Selecione um produto válido.", "erro")
    else:
        anuncios_collection.insert_one({
            "titulo": titulo,
            "codigo_marketplace": codigo,
            "campanha_id": campanha_id,
            "produto_id": produto_id,
            "status": "ativo",
            "criado_em": datetime.utcnow(),
        })
        flash(f"Anúncio “{titulo}” cadastrado.", "sucesso")

    return redirect(url_for("tela_anuncios"))


@app.route("/investimentos")
def tela_investimentos():
    campanhas = list(campanhas_collection.find().sort("nome", 1))
    nomes_campanha = {str(c["_id"]): c.get("nome") for c in campanhas}

    investimentos = list(investimentos_collection.find().sort("data", -1))
    for inv in investimentos:
        inv["campanha_nome"] = nomes_campanha.get(inv.get("campanha_id"), "(campanha removida)")

    orcamentos = [enriquecer_campanha(c) for c in campanhas]      # RF01: planejado x investido
    return render_template("investimentos.html", campanhas=campanhas, investimentos=investimentos, orcamentos=orcamentos)


@app.route("/investimentos/novo", methods=["POST"])
def criar_investimento_tela():
    """RF01 - registra um investimento e recalcula os indicadores da campanha."""
    campanha_id = request.form.get("campanha_id", "")
    data = request.form.get("data", "")
    valor = para_numero(request.form.get("investimento"))

    if not buscar_por_id(campanhas_collection, campanha_id):
        flash("Selecione uma campanha válida.", "erro")
    elif valor is None or valor == 0:
        flash("Informe um valor maior que zero (ex: 500,00).", "erro")
    else:
        investimentos_collection.insert_one({
            "campanha_id": campanha_id,
            "data": data,
            "investimento": valor,
            "criado_em": datetime.utcnow(),
        })
        recalcular_indicadores(campanha_id)
        flash("Investimento registrado. Indicadores atualizados.", "sucesso")

    return redirect(url_for("tela_investimentos"))


@app.route("/metricas")
def tela_metricas():
    campanhas = list(campanhas_collection.find().sort("nome", 1))
    nomes_campanha = {str(c["_id"]): c.get("nome") for c in campanhas}

    anuncios = list(anuncios_collection.find().sort("titulo", 1))
    titulos_anuncio = {str(a["_id"]): a.get("titulo") for a in anuncios}

    metricas = list(metricas_collection.find().sort("data", -1))
    for m in metricas:
        m["campanha_nome"] = nomes_campanha.get(m.get("campanha_id"), "(campanha removida)")
        m["anuncio_titulo"] = titulos_anuncio.get(m.get("anuncio_id"))

    return render_template("metricas.html", campanhas=campanhas, anuncios=anuncios, metricas=metricas)


@app.route("/metricas/novo", methods=["POST"])
def criar_metrica_tela():
    """RF05 - registra uma metrica e recalcula os indicadores da campanha."""
    campanha_id = request.form.get("campanha_id", "")
    data = request.form.get("data", "")

    if not buscar_por_id(campanhas_collection, campanha_id):
        flash("Selecione uma campanha válida.", "erro")
        return redirect(url_for("tela_metricas"))

    metrica, erro = montar_metrica(campanha_id, data, request.form)
    if erro:
        flash(erro, "erro")
    else:
        metricas_collection.insert_one(metrica)
        recalcular_indicadores(campanha_id)
        flash("Métrica registrada. Indicadores atualizados.", "sucesso")

    return redirect(url_for("tela_metricas"))


@app.route("/dashboard")
def tela_dashboard():
    """RF07 - painel gerencial com graficos, filtravel por campanha e periodo (RF08)."""
    campanha_id, data_ini, data_fim = ler_filtros()
    contexto = montar_dashboard(campanha_id, data_ini, data_fim)
    return render_template(
        "dashboard.html",
        campanhas=list(campanhas_collection.find().sort("nome", 1)),
        filtros={"campanha_id": campanha_id, "de": data_ini, "ate": data_fim},
        **contexto,
    )


@app.route("/comparar")
def tela_comparar():
    """RF09 - compara campanhas, anuncios ou dois periodos."""
    visao = request.args.get("visao", "campanhas")
    if visao not in ("campanhas", "anuncios", "periodos"):
        visao = "campanhas"

    campanhas = list(campanhas_collection.find().sort("nome", 1))
    contexto = {"visao": visao, "campanhas": campanhas}

    if visao == "campanhas":
        com, sem, marca_um = ranking_campanhas()
        contexto.update(ranking=com, sem_investimento=sem, marca_um=marca_um)

    elif visao == "anuncios":
        campanha_id = request.args.get("campanha_id", "")
        if campanha_id and not buscar_por_id(campanhas_collection, campanha_id):
            flash("Campanha do filtro não encontrada. Mostrando todas.", "erro")
            campanha_id = ""
        contexto.update(anuncios=ranking_anuncios(campanha_id), campanha_id=campanha_id)

    else:
        campanha_id = request.args.get("campanha_id", "")
        a_de, a_ate = request.args.get("a_de", ""), request.args.get("a_ate", "")
        b_de, b_ate = request.args.get("b_de", ""), request.args.get("b_ate", "")
        contexto.update(campanha_id=campanha_id, a_de=a_de, a_ate=a_ate, b_de=b_de, b_ate=b_ate, linhas=None)

        if all([a_de, a_ate, b_de, b_ate]):
            erro = validar_periodo(a_de, a_ate) or validar_periodo(b_de, b_ate)
            if campanha_id and not buscar_por_id(campanhas_collection, campanha_id):
                erro = "Campanha do filtro não encontrada."
            if erro:
                flash(erro, "erro")
            else:
                resumo_a = calcular_resumo(*registros_filtrados(campanha_id, a_de, a_ate))
                resumo_b = calcular_resumo(*registros_filtrados(campanha_id, b_de, b_ate))
                contexto["linhas"] = comparar_periodos(resumo_a, resumo_b)
        elif any([a_de, a_ate, b_de, b_ate]):
            flash("Preencha as quatro datas (início e fim dos dois períodos) para comparar.", "erro")

    return render_template("comparar.html", **contexto)


@app.route("/historico")
def tela_historico():
    """Resultados dia a dia, do mais recente para o mais antigo."""
    campanha_id, data_ini, data_fim = ler_filtros()
    investimentos, metricas = registros_filtrados(campanha_id, data_ini, data_fim)
    return render_template(
        "historico.html",
        campanhas=list(campanhas_collection.find().sort("nome", 1)),
        filtros={"campanha_id": campanha_id, "de": data_ini, "ate": data_fim},
        dias=list(reversed(serie_diaria(investimentos, metricas))),
        total=calcular_resumo(investimentos, metricas),
    )


@app.route("/indicadores")
def tela_indicadores():
    """RF06 - os cinco indicadores de cada campanha, mais o consolidado de todas."""
    campanhas = [enriquecer_campanha(c) for c in campanhas_collection.find().sort("nome", 1)]
    total = calcular_resumo(list(investimentos_collection.find()), list(metricas_collection.find()))
    return render_template("indicadores.html", campanhas=campanhas, total=total)


# ----- edicao (campanhas, produtos, anuncios) -----

def pagina_edicao(titulo, voltar, campos):
    return render_template("editar.html", titulo=titulo, voltar=voltar, campos=campos)


@app.route("/campanhas/<campanha_id>/editar", methods=["GET", "POST"])
def editar_campanha(campanha_id):
    """Corrige nome, periodo, orcamento e status de uma campanha (RF02: editar e acompanhar)."""
    campanha = buscar_por_id(campanhas_collection, campanha_id)
    if not campanha:
        flash("Campanha não encontrada.", "erro")
        return redirect(url_for("tela_campanhas"))

    valores = {
        "nome": campanha.get("nome", ""), "data_inicio": campanha.get("data_inicio", ""),
        "data_fim": campanha.get("data_fim", ""), "status": campanha.get("status", "ativa"),
        "orcamento_planejado": numero_para_campo(campanha.get("orcamento_planejado")),
    }
    if request.method == "POST":
        valores = {k: request.form.get(k, "").strip() for k in valores}
        orcamento = para_numero(valores["orcamento_planejado"])
        erro = None
        if not valores["nome"]:
            erro = "Informe o nome da campanha."
        elif orcamento is None:
            erro = "Orçamento inválido. Use apenas números, com vírgula ou ponto para os centavos (ex: 1500,50)."
        elif validar_periodo(valores["data_inicio"], valores["data_fim"]):
            erro = validar_periodo(valores["data_inicio"], valores["data_fim"])
        elif valores["status"] not in STATUS_CAMPANHA:
            erro = "Status inválido."
        if erro:
            flash(erro, "erro")
        else:
            campanhas_collection.update_one({"_id": campanha["_id"]}, {"$set": {
                "nome": valores["nome"], "data_inicio": valores["data_inicio"], "data_fim": valores["data_fim"],
                "orcamento_planejado": orcamento, "status": valores["status"],
            }})
            flash(f"Campanha “{valores['nome']}” atualizada.", "sucesso")
            return redirect(url_for("tela_campanhas"))

    campos = [
        {"nome": "nome", "rotulo": "Nome da campanha", "tipo": "text", "valor": valores["nome"], "largo": True},
        {"nome": "data_inicio", "rotulo": "Início", "tipo": "date", "valor": valores["data_inicio"]},
        {"nome": "data_fim", "rotulo": "Fim", "tipo": "date", "valor": valores["data_fim"]},
        {"nome": "orcamento_planejado", "rotulo": "Orçamento planejado (R$)", "tipo": "text", "valor": valores["orcamento_planejado"]},
        {"nome": "status", "rotulo": "Status", "tipo": "select", "valor": valores["status"], "opcoes": [(s, s.capitalize()) for s in STATUS_CAMPANHA]},
    ]
    return pagina_edicao("Editar campanha", url_for("tela_campanhas"), campos)


@app.route("/produtos/<produto_id>/editar", methods=["GET", "POST"])
def editar_produto(produto_id):
    produto = buscar_por_id(produtos_collection, produto_id)
    if not produto:
        flash("Produto não encontrado.", "erro")
        return redirect(url_for("tela_produtos"))

    valores = {"nome": produto.get("nome", ""), "categoria": produto.get("categoria", ""),
               "preco_unitario": numero_para_campo(produto.get("preco_unitario"))}
    if request.method == "POST":
        valores = {k: request.form.get(k, "").strip() for k in valores}
        preco = para_numero(valores["preco_unitario"])
        if not valores["nome"]:
            flash("Informe o nome do produto.", "erro")
        elif preco is None:
            flash("Preço inválido. Use apenas números, com vírgula ou ponto para os centavos (ex: 89,90).", "erro")
        else:
            produtos_collection.update_one({"_id": produto["_id"]}, {"$set": {
                "nome": valores["nome"], "categoria": valores["categoria"], "preco_unitario": preco}})
            flash(f"Produto “{valores['nome']}” atualizado.", "sucesso")
            return redirect(url_for("tela_produtos"))

    campos = [
        {"nome": "nome", "rotulo": "Nome do produto", "tipo": "text", "valor": valores["nome"], "largo": True},
        {"nome": "categoria", "rotulo": "Categoria", "tipo": "text", "valor": valores["categoria"]},
        {"nome": "preco_unitario", "rotulo": "Preço unitário (R$)", "tipo": "text", "valor": valores["preco_unitario"]},
    ]
    return pagina_edicao("Editar produto", url_for("tela_produtos"), campos)


@app.route("/anuncios/<anuncio_id>/editar", methods=["GET", "POST"])
def editar_anuncio(anuncio_id):
    """A campanha do anuncio nao muda (as metricas ja registradas dependem dela); o resto pode ser corrigido."""
    anuncio = buscar_por_id(anuncios_collection, anuncio_id)
    if not anuncio:
        flash("Anúncio não encontrado.", "erro")
        return redirect(url_for("tela_anuncios"))

    valores = {"titulo": anuncio.get("titulo", ""), "codigo_marketplace": anuncio.get("codigo_marketplace", ""),
               "produto_id": anuncio.get("produto_id", ""), "status": anuncio.get("status", "ativo")}
    if request.method == "POST":
        valores = {k: request.form.get(k, "").strip() for k in valores}
        if not valores["titulo"]:
            flash("Informe o título do anúncio.", "erro")
        elif not buscar_por_id(produtos_collection, valores["produto_id"]):
            flash("Selecione um produto válido.", "erro")
        elif valores["status"] not in STATUS_ANUNCIO:
            flash("Status inválido.", "erro")
        else:
            anuncios_collection.update_one({"_id": anuncio["_id"]}, {"$set": valores})
            flash(f"Anúncio “{valores['titulo']}” atualizado.", "sucesso")
            return redirect(url_for("tela_anuncios"))

    campos = [
        {"nome": "titulo", "rotulo": "Título do anúncio", "tipo": "text", "valor": valores["titulo"], "largo": True},
        {"nome": "produto_id", "rotulo": "Produto divulgado", "tipo": "select", "valor": valores["produto_id"],
         "opcoes": [(str(p["_id"]), p.get("nome")) for p in produtos_collection.find().sort("nome", 1)]},
        {"nome": "status", "rotulo": "Status", "tipo": "select", "valor": valores["status"], "opcoes": [(s, s.capitalize()) for s in STATUS_ANUNCIO]},
        {"nome": "codigo_marketplace", "rotulo": "Código no Mercado Livre (opcional)", "tipo": "text", "valor": valores["codigo_marketplace"], "largo": True},
    ]
    return pagina_edicao("Editar anúncio", url_for("tela_anuncios"), campos)


# ----- exclusao de registros lancados por engano -----

@app.route("/investimentos/<registro_id>/excluir", methods=["POST"])
def excluir_investimento(registro_id):
    registro = buscar_por_id(investimentos_collection, registro_id)
    if registro:
        investimentos_collection.delete_one({"_id": registro["_id"]})
        if buscar_por_id(campanhas_collection, registro.get("campanha_id")):
            recalcular_indicadores(registro["campanha_id"])
        flash("Investimento excluído. Indicadores recalculados.", "sucesso")
    else:
        flash("Investimento não encontrado.", "erro")
    return redirect(url_for("tela_investimentos"))


@app.route("/metricas/<registro_id>/excluir", methods=["POST"])
def excluir_metrica(registro_id):
    registro = buscar_por_id(metricas_collection, registro_id)
    if registro:
        metricas_collection.delete_one({"_id": registro["_id"]})
        if buscar_por_id(campanhas_collection, registro.get("campanha_id")):
            recalcular_indicadores(registro["campanha_id"])
        flash("Métrica excluída. Indicadores recalculados.", "sucesso")
    else:
        flash("Métrica não encontrada.", "erro")
    return redirect(url_for("tela_metricas"))


# ----- relatorios gerenciais e exportacao -----

def montar_relatorios(campanha_id, data_ini, data_fim):
    """Dados dos quatro relatorios, respeitando o filtro de campanha e periodo."""
    investimentos, metricas = registros_filtrados(campanha_id, data_ini, data_fim)

    todas = list(campanhas_collection.find().sort("nome", 1))
    campanhas = [c for c in todas if not campanha_id or str(c["_id"]) == campanha_id]
    anuncios = [a for a in anuncios_collection.find().sort("titulo", 1) if not campanha_id or a.get("campanha_id") == campanha_id]
    todos_anuncios = list(anuncios_collection.find())
    nomes_campanha = {str(c["_id"]): c.get("nome") for c in todas}
    nomes_produto = {str(p["_id"]): p.get("nome") for p in produtos_collection.find()}

    return {
        "investimentos": investimentos, "metricas": metricas,
        "campanhas_rel": relatorios.por_campanha(investimentos, metricas, campanhas),
        "dias": relatorios.por_dia(investimentos, metricas),
        "anuncios_rel": relatorios.por_anuncio(metricas, anuncios, nomes_campanha, nomes_produto),
        "produtos_rel": relatorios.por_produto(metricas, todos_anuncios, nomes_produto),
        "total": calcular_resumo(investimentos, metricas),
        "nomes_campanha": nomes_campanha, "nomes_produto": nomes_produto, "todos_anuncios": todos_anuncios,
    }


@app.route("/relatorios")
def tela_relatorios():
    """Relatorios gerenciais: resumo por campanha, por dia, por anuncio e por produto."""
    campanha_id, data_ini, data_fim = ler_filtros()
    dados = montar_relatorios(campanha_id, data_ini, data_fim)
    nome_filtro = dados["nomes_campanha"].get(campanha_id, "Todas as campanhas")
    return render_template(
        "relatorios.html", campanhas=list(campanhas_collection.find().sort("nome", 1)),
        filtros={"campanha_id": campanha_id, "de": data_ini, "ate": data_fim},
        nome_filtro=nome_filtro, **dados,
    )


@app.route("/relatorios/exportar/<tipo>.csv")
def exportar_csv(tipo):
    """CSV para Excel e Power BI. Aceita os mesmos filtros da tela (?campanha_id=&de=&ate=)."""
    if tipo not in relatorios.CABECALHOS:
        return jsonify({"erro": "Tipo de relatório inexistente"}), 404
    campanha_id, data_ini, data_fim, erro = filtros_da_requisicao()
    if erro:
        return jsonify({"erro": erro}), 400

    dados = montar_relatorios(campanha_id, data_ini, data_fim)
    if tipo == "metricas":
        anuncio_por_id = {str(a["_id"]): a for a in dados["todos_anuncios"]}
        linhas = []
        for m in sorted(dados["metricas"], key=lambda m: m.get("data") or ""):
            anuncio = anuncio_por_id.get(m.get("anuncio_id"))
            produto = dados["nomes_produto"].get(anuncio.get("produto_id")) if anuncio else ""
            linhas.append([m.get("data"), dados["nomes_campanha"].get(m.get("campanha_id"), ""),
                           anuncio.get("titulo") if anuncio else "", produto, int(m.get("impressoes") or 0),
                           int(m.get("cliques") or 0), int(m.get("visitas") or 0), int(m.get("vendas") or 0),
                           float(m.get("receita_atribuida") or 0)])
    elif tipo == "investimentos":
        linhas = [[i.get("data"), dados["nomes_campanha"].get(i.get("campanha_id"), ""), float(i.get("investimento") or 0)]
                  for i in sorted(dados["investimentos"], key=lambda i: i.get("data") or "")]
    else:
        fonte = {"campanhas": "campanhas_rel", "dias": "dias", "anuncios": "anuncios_rel", "produtos": "produtos_rel"}[tipo]
        linhas = relatorios.linhas_csv(tipo, dados[fonte])

    conteudo = relatorios.para_csv(relatorios.CABECALHOS[tipo], linhas)
    return Response(conteudo, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=adcontrol_{tipo}.csv"})


# ---------- API (JSON) ----------

@app.route("/api/campanhas", methods=["GET"])
def listar_campanhas_api():
    """RF02 - retorna todas as campanhas, ja com totais e indicadores."""
    return jsonify([campanha_para_dict(c) for c in campanhas_collection.find()])


@app.route("/api/campanhas/<campanha_id>", methods=["GET"])
def obter_campanha_api(campanha_id):
    campanha = buscar_por_id(campanhas_collection, campanha_id)
    if not campanha:
        return jsonify({"erro": "Campanha não encontrada"}), 404
    return jsonify(campanha_para_dict(campanha))


@app.route("/api/campanhas", methods=["POST"])
def criar_campanha_api():
    """RF02 - cadastra uma campanha recebendo dados em JSON."""
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    orcamento = para_numero(dados.get("orcamento_planejado"))
    data_inicio = dados.get("data_inicio", "")
    data_fim = dados.get("data_fim", "")

    if not nome:
        return jsonify({"erro": "O campo 'nome' é obrigatório"}), 400
    if orcamento is None:
        return jsonify({"erro": "orcamento_planejado deve ser um número maior ou igual a zero"}), 400
    if validar_periodo(data_inicio, data_fim):
        return jsonify({"erro": validar_periodo(data_inicio, data_fim)}), 400

    nova_campanha = novo_doc_campanha(
        nome, data_inicio, data_fim, orcamento, dados.get("status", "ativa")
    )
    resultado = campanhas_collection.insert_one(nova_campanha)
    nova_campanha["_id"] = resultado.inserted_id
    return jsonify(campanha_para_dict(nova_campanha)), 201


@app.route("/api/produtos", methods=["GET"])
def listar_produtos_api():
    """RF04 - retorna todos os produtos cadastrados."""
    return jsonify([produto_para_dict(p) for p in produtos_collection.find()])


@app.route("/api/produtos/<produto_id>", methods=["GET"])
def obter_produto_api(produto_id):
    produto = buscar_por_id(produtos_collection, produto_id)
    if not produto:
        return jsonify({"erro": "Produto não encontrado"}), 404
    return jsonify(produto_para_dict(produto))


@app.route("/api/produtos", methods=["POST"])
def criar_produto_api():
    """RF04 - cadastra um produto recebendo dados em JSON."""
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    preco = para_numero(dados.get("preco_unitario"))

    if not nome:
        return jsonify({"erro": "O campo 'nome' é obrigatório"}), 400
    if preco is None:
        return jsonify({"erro": "preco_unitario deve ser um número maior ou igual a zero"}), 400

    novo_produto = {
        "nome": nome,
        "categoria": dados.get("categoria", ""),
        "preco_unitario": preco,
        "criado_em": datetime.utcnow(),
    }
    resultado = produtos_collection.insert_one(novo_produto)
    novo_produto["_id"] = resultado.inserted_id
    return jsonify(produto_para_dict(novo_produto)), 201


@app.route("/api/anuncios", methods=["GET"])
def listar_anuncios_api():
    """RF03 - retorna todos os anuncios, ja com o desempenho acumulado de cada um."""
    totais = totais_por_anuncio()
    resposta = []
    for a in anuncios_collection.find():
        item = anuncio_para_dict(a)
        item["desempenho"] = totais.get(item["id"], SEM_TOTAIS)
        resposta.append(item)
    return jsonify(resposta)


@app.route("/api/anuncios/<anuncio_id>", methods=["GET"])
def obter_anuncio_api(anuncio_id):
    anuncio = buscar_por_id(anuncios_collection, anuncio_id)
    if not anuncio:
        return jsonify({"erro": "Anúncio não encontrado"}), 404
    item = anuncio_para_dict(anuncio)
    item["desempenho"] = totais_por_anuncio().get(item["id"], SEM_TOTAIS)
    return jsonify(item)


@app.route("/api/anuncios", methods=["POST"])
def criar_anuncio_api():
    """RF03 - cadastra um anuncio recebendo dados em JSON."""
    dados = request.get_json(silent=True) or {}
    titulo = (dados.get("titulo") or "").strip()
    campanha_id = dados.get("campanha_id", "")
    produto_id = dados.get("produto_id", "")

    if not titulo:
        return jsonify({"erro": "O campo 'titulo' é obrigatório"}), 400
    if not buscar_por_id(campanhas_collection, campanha_id):
        return jsonify({"erro": "campanha_id inválido ou não encontrado"}), 400
    if not buscar_por_id(produtos_collection, produto_id):
        return jsonify({"erro": "produto_id inválido ou não encontrado"}), 400

    novo_anuncio = {
        "titulo": titulo,
        "codigo_marketplace": dados.get("codigo_marketplace", ""),
        "campanha_id": campanha_id,
        "produto_id": produto_id,
        "status": dados.get("status", "ativo"),
        "criado_em": datetime.utcnow(),
    }
    resultado = anuncios_collection.insert_one(novo_anuncio)
    novo_anuncio["_id"] = resultado.inserted_id
    return jsonify(anuncio_para_dict(novo_anuncio)), 201


@app.route("/api/investimentos", methods=["GET"])
def listar_investimentos_api():
    """RF01 - retorna todos os investimentos registrados."""
    return jsonify([investimento_para_dict(i) for i in investimentos_collection.find()])


@app.route("/api/investimentos", methods=["POST"])
def criar_investimento_api():
    """RF01 - registra um investimento e recalcula os indicadores da campanha."""
    dados = request.get_json(silent=True) or {}
    campanha_id = dados.get("campanha_id", "")
    valor = para_numero(dados.get("investimento"))

    if not buscar_por_id(campanhas_collection, campanha_id):
        return jsonify({"erro": "campanha_id inválido ou não encontrado"}), 400
    if valor is None or valor == 0:
        return jsonify({"erro": "investimento deve ser um número maior que zero"}), 400

    novo_investimento = {
        "campanha_id": campanha_id,
        "data": dados.get("data", ""),
        "investimento": valor,
        "criado_em": datetime.utcnow(),
    }
    resultado = investimentos_collection.insert_one(novo_investimento)
    novo_investimento["_id"] = resultado.inserted_id
    recalcular_indicadores(campanha_id)
    return jsonify(investimento_para_dict(novo_investimento)), 201


@app.route("/api/metricas", methods=["GET"])
def listar_metricas_api():
    """RF05 - retorna todas as metricas registradas."""
    return jsonify([metrica_para_dict(m) for m in metricas_collection.find()])


@app.route("/api/metricas", methods=["POST"])
def criar_metrica_api():
    """RF05 - registra uma metrica e recalcula os indicadores da campanha."""
    dados = request.get_json(silent=True) or {}
    campanha_id = dados.get("campanha_id", "")

    if not buscar_por_id(campanhas_collection, campanha_id):
        return jsonify({"erro": "campanha_id inválido ou não encontrado"}), 400

    nova_metrica, erro = montar_metrica(campanha_id, dados.get("data", ""), dados)
    if erro:
        return jsonify({"erro": erro}), 400

    resultado = metricas_collection.insert_one(nova_metrica)
    nova_metrica["_id"] = resultado.inserted_id
    recalcular_indicadores(campanha_id)
    return jsonify(metrica_para_dict(nova_metrica)), 201


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    """RF07/RF08 - resumo e serie diaria, filtraveis por ?campanha_id=&de=&ate= (uso: Excel, Power BI)."""
    campanha_id, data_ini, data_fim, erro = filtros_da_requisicao()
    if erro:
        return jsonify({"erro": erro}), 400
    investimentos, metricas = registros_filtrados(campanha_id, data_ini, data_fim)
    return jsonify({
        "filtros": {"campanha_id": campanha_id, "de": data_ini, "ate": data_fim},
        "resumo": calcular_resumo(investimentos, metricas),
        "serie_diaria": serie_diaria(investimentos, metricas),
    })


@app.route("/api/historico", methods=["GET"])
def api_historico():
    """Resultados dia a dia (mesmos filtros do dashboard)."""
    campanha_id, data_ini, data_fim, erro = filtros_da_requisicao()
    if erro:
        return jsonify({"erro": erro}), 400
    investimentos, metricas = registros_filtrados(campanha_id, data_ini, data_fim)
    return jsonify(serie_diaria(investimentos, metricas))


if __name__ == "__main__":
    if app.secret_key == "dev-adcontrol-troque-esta-chave":
        print("AVISO: defina a variavel de ambiente SECRET_KEY com um texto proprio antes de usar de verdade.")
    # O modo debug abre o depurador do Flask no navegador; so ligue em desenvolvimento (FLASK_DEBUG=1).
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
