"""
Testes automaticos do AdControl Web.

Rodam SEM MongoDB: usam um banco de mentira em memoria (tests/stub_mongo).
Como rodar, dentro da pasta do projeto:   python tests/rodar_testes.py

Se algum teste falhar, o programa para e mostra qual foi.
Isso nao substitui testar com o MongoDB de verdade antes de apresentar.
"""
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "tests", "stub_mongo"))
sys.path.insert(0, RAIZ)

import app as A                      # noqa: E402
from analise import (                # noqa: E402
    calcular_resumo, comparar_periodos, geometria_linhas, montar_funil,
    no_periodo, serie_diaria, teto_agradavel, abreviar_brl,
)

c = A.app.test_client()

# Os blocos abaixo testam as regras de negocio; o login e o CSRF tem bloco proprio no final.
A.app.config["AUTENTICACAO_ATIVA"] = False
A.app.config["CSRF_ATIVO"] = False


def html(resposta):
    return resposta.get_data(as_text=True)


def secao(titulo):
    print(f"  ok  {titulo}")


print("\n== Calculos (analise.py) ==")
r = calcular_resumo([{"investimento": 500.0}], [{"impressoes": 1000, "cliques": 50, "visitas": 40, "vendas": 5, "receita_atribuida": 750.0}])
assert (r["ctr"], r["cpc"], r["taxa_conversao"], r["custo_por_venda"], r["roas"]) == (5.0, 10.0, 12.5, 100.0, 1.5)
z = calcular_resumo([], [])
assert z["roas"] == 0 and z["ctr"] == 0 and z["cpc"] == 0 and z["custo_por_venda"] == 0
secao("5 indicadores conferidos a mao e divisao por zero (RNF09)")
assert no_periodo({"data": "2026-11-20"}, "2026-11-01", "2026-11-30")
assert not no_periodo({"data": "2026-12-01"}, "2026-11-01", "2026-11-30")
assert not no_periodo({"data": ""}, "2026-11-01", "")
secao("filtro de periodo")
s = serie_diaria([{"data": "2026-11-20", "investimento": 100}, {"data": "lixo", "investimento": 9}],
                 [{"data": "2026-11-20", "receita_atribuida": 300}, {"data": "2026-11-21", "receita_atribuida": 40}])
assert [d["data"] for d in s] == ["2026-11-20", "2026-11-21"] and s[0]["roas"] == 3.0
secao("serie diaria ordenada e ignorando data invalida")
assert teto_agradavel(8700) == 10000 and abreviar_brl(1500) == "R$ 1,5 mil" and abreviar_brl(800) == "R$ 800"
g = geometria_linhas(s)
assert g["pontos"][0]["x"] == g["esq"] and geometria_linhas([]) is None
secao("geometria do grafico")
assert [e["taxa"] for e in montar_funil({"impressoes": 1000, "cliques": 50, "visitas": 40, "vendas": 5})[1:]] == [5.0, 80.0, 12.5]
secao("funil")
a = calcular_resumo([{"investimento": 100}], [{"impressoes": 1000, "cliques": 10, "visitas": 10, "vendas": 1, "receita_atribuida": 100}])
b = calcular_resumo([{"investimento": 100}], [{"impressoes": 1000, "cliques": 20, "visitas": 20, "vendas": 4, "receita_atribuida": 400}])
linhas = {l["nome"]: l for l in comparar_periodos(a, b)}
assert linhas["ROAS"]["variacao"] == 300.0 and linhas["CPC"]["sentido"] == "bom" and linhas["Investido"]["sentido"] == "neutro"
secao("comparacao de periodos (custo menor e bom)")

print("\n== Formatacao e conversao ==")
assert A.filtro_brl(1234.5) == "R$ 1.234,50" and A.filtro_numero(12345) == "12.345" and A.filtro_data_br("2026-11-20") == "20/11/2026"
assert A.para_numero("1500,50") == 1500.5 and A.para_numero("1.500,00") is None and A.para_numero("-5") is None
assert A.para_numero("nan") is None and A.para_numero("") == 0.0
secao("padrao brasileiro e numeros invalidos")

print("\n== Telas abrem (vazias) ==")
rotas = ["/", "/dashboard", "/comparar", "/comparar?visao=anuncios", "/comparar?visao=periodos", "/historico",
         "/campanhas", "/anuncios", "/produtos", "/investimentos", "/metricas", "/api/dashboard", "/api/historico"]
for rota in rotas:
    assert c.get(rota).status_code == 200, rota
secao(f"{len(rotas)} rotas respondem 200")
assert "Falta cadastrar uma campanha" in html(c.get("/anuncios"))

print("\n== Campanhas e Produtos ==")
r = c.post("/campanhas/nova", data={"nome": "X", "orcamento_planejado": "1.500,00"}, follow_redirects=True)
assert "Orçamento inválido" in html(r) and not c.get("/api/campanhas").get_json()
r = c.post("/campanhas/nova", data={"nome": "X", "data_inicio": "2026-12-10", "data_fim": "2026-12-01"}, follow_redirects=True)
assert "data de fim não pode ser anterior" in html(r)
assert "Informe o nome" in html(c.post("/campanhas/nova", data={"nome": "  "}, follow_redirects=True))
secao("campanha: orcamento invalido, periodo invertido, nome vazio")
for nome, ini, fim, orc in [("Black Friday 2026", "2026-11-20", "2026-11-30", "3000,00"),
                            ("Dia das Mães 2026", "2026-05-01", "2026-05-10", "1500,00"),
                            ("Sem Verba", "", "", "500")]:
    c.post("/campanhas/nova", data={"nome": nome, "data_inicio": ini, "data_fim": fim, "orcamento_planejado": orc})
camps = {x["nome"]: x["id"] for x in c.get("/api/campanhas").get_json()}
bf, dm = camps["Black Friday 2026"], camps["Dia das Mães 2026"]
assert all(x["roas"] == 0 and x["ctr"] == 0 for x in c.get("/api/campanhas").get_json())
secao("campanhas nascem com indicadores zerados")
assert "Preço inválido" in html(c.post("/produtos/novo", data={"nome": "Y", "preco_unitario": "1.500,00"}, follow_redirects=True))
c.post("/produtos/novo", data={"nome": "Fone XY200", "categoria": "Eletrônicos", "preco_unitario": "89,90"})
c.post("/produtos/novo", data={"nome": "Capa S23", "preco_unitario": "39,90"})
pr = {x["nome"]: x["id"] for x in c.get("/api/produtos").get_json()}
secao("produtos")

print("\n== Anuncios ==")
assert "Informe o título" in html(c.post("/anuncios/novo", data={"titulo": "", "campanha_id": bf, "produto_id": pr["Fone XY200"]}, follow_redirects=True))
assert "campanha válida" in html(c.post("/anuncios/novo", data={"titulo": "A", "campanha_id": "naoexiste", "produto_id": pr["Fone XY200"]}, follow_redirects=True))
assert "produto válido" in html(c.post("/anuncios/novo", data={"titulo": "A", "campanha_id": bf, "produto_id": "naoexiste"}, follow_redirects=True))
assert not c.get("/api/anuncios").get_json()
secao("anuncio exige titulo, campanha e produto validos")
c.post("/anuncios/novo", data={"titulo": "Fone frete grátis", "campanha_id": bf, "produto_id": pr["Fone XY200"]})
c.post("/anuncios/novo", data={"titulo": "Capa reforçada", "campanha_id": bf, "produto_id": pr["Capa S23"]})
c.post("/anuncios/novo", data={"titulo": "Fone presente", "campanha_id": dm, "produto_id": pr["Fone XY200"]})
an = {x["titulo"]: x["id"] for x in c.get("/api/anuncios").get_json()}
secao("anuncios cadastrados")

print("\n== Investimentos e Metricas ==")
assert "Selecione uma campanha válida" in html(c.post("/investimentos/novo", data={"campanha_id": "naoexiste", "data": "2026-11-20", "investimento": "500"}, follow_redirects=True))
assert "maior que zero" in html(c.post("/investimentos/novo", data={"campanha_id": bf, "data": "2026-11-20", "investimento": "0"}, follow_redirects=True))
secao("investimento: campanha invalida (sem erro 500) e valor zero")


def inv(cid, d, v):
    c.post("/investimentos/novo", data={"campanha_id": cid, "data": d, "investimento": v})


def met(cid, aid, d, i, cl, vi, ve, rc):
    return c.post("/metricas/novo", data={"campanha_id": cid, "anuncio_id": aid, "data": d, "impressoes": i,
                                          "cliques": cl, "visitas": vi, "vendas": ve, "receita_atribuida": rc}, follow_redirects=True)


assert "cliques não podem ser maiores" in html(met(bf, "", "2026-11-21", 100, 200, 10, 1, "10"))
assert "Valor inválido em vendas" in html(met(bf, "", "2026-11-21", 100, 20, 10, "abc", "10"))
assert "não pertence a esta campanha" in html(met(bf, an["Fone presente"], "2026-11-21", 100, 20, 10, 1, "10"))
assert "Anúncio inválido" in html(met(bf, "naoexiste", "2026-11-21", 100, 20, 10, 1, "10"))
assert not c.get("/api/metricas").get_json()
secao("metrica: cliques>impressoes, texto invalido, anuncio de outra campanha, anuncio inexistente")

inv(bf, "2026-11-20", "1000"); inv(bf, "2026-11-22", "500"); inv(dm, "2026-05-02", "400")
met(bf, an["Fone frete grátis"], "2026-11-21", 10000, 400, 300, 30, "3000,00")
met(bf, an["Capa reforçada"], "2026-11-23", 20000, 200, 150, 10, "400,00")
met(dm, an["Fone presente"], "2026-05-03", 5000, 100, 80, 4, "360,00")
camp = c.get(f"/api/campanhas/{bf}").get_json()
assert (camp["total_investido"], camp["total_receita"], camp["roas"], camp["ctr"], camp["cpc"]) == (1500, 3400, 2.27, 2.0, 2.5)
secao("indicadores gravados na campanha (ROAS 2,27 / CTR 2,0% / CPC R$ 2,50)")
lista = {x["titulo"]: x for x in c.get("/api/anuncios").get_json()}
assert lista["Fone frete grátis"]["desempenho"]["ctr"] == 4.0 and lista["Capa reforçada"]["desempenho"]["receita"] == 400
h = html(c.get("/produtos"))
assert "R$ 3.360,00" in h and "R$ 400,00" in h        # Fone: 3000 + 360 ; Capa: 400
secao("desempenho por anuncio e por produto (soma dos anuncios)")
c.post("/investimentos/novo", data={"campanha_id": bf, "data": "2026-11-25", "investimento": "3000"})
assert "Acima do orçamento" in html(c.get("/campanhas"))
secao("alerta de orcamento estourado")
c.post("/investimentos/novo", data={"campanha_id": bf, "data": "2026-11-25", "investimento": "1"})   # nao deve quebrar nada
# remove o excesso para manter os valores dos proximos testes
for d in list(A.investimentos_collection._docs):
    if d["data"] == "2026-11-25":
        A.investimentos_collection._docs.remove(d)
A.recalcular_indicadores(bf)

print("\n== Dashboard e filtros (RF07, RF08) ==")
h = html(c.get("/dashboard"))
assert "R$ 1.900,00" in h and "R$ 3.760,00" in h and 'class="grafico"' in h and "Funil de conversão" in h
secao("KPIs, grafico, barras, funil")
api = c.get("/api/dashboard").get_json()
assert api["resumo"]["investido"] == 1900 and api["resumo"]["receita"] == 3760 and len(api["serie_diaria"]) == 6
f = c.get(f"/api/dashboard?campanha_id={bf}").get_json()
assert f["resumo"]["investido"] == 1500 and f["resumo"]["receita"] == 3400
f = c.get("/api/dashboard?de=2026-11-21&ate=2026-11-30").get_json()
assert f["resumo"]["investido"] == 500 and f["resumo"]["receita"] == 3400
secao("filtros por campanha e por periodo somam certo")
assert c.get("/api/dashboard?de=2026-12-10&ate=2026-12-01").status_code == 400
assert c.get("/api/dashboard?campanha_id=naoexiste").status_code == 400
h = html(c.get("/dashboard?de=2026-12-10&ate=2026-12-01"))
assert "data de fim não pode ser anterior" in h and "R$ 1.900,00" in h
assert "Nenhum dado para este filtro" in html(c.get("/dashboard?de=2030-01-01&ate=2030-12-31"))
secao("filtro invalido: API 400, tela avisa; filtro sem dados avisa")
h = html(c.get(f"/dashboard?campanha_id={bf}"))
assert "Receita por anúncio" in h and "Fone frete grátis" in h and "Fone presente" not in h
secao("campanha filtrada mostra receita por anuncio")

print("\n== Comparar (RF09) e Historico ==")
h = html(c.get("/comparar"))
assert "2,27x" in h and "0,90x" in h and "Melhor retorno" in h and "Menor retorno" in h and "Abaixo do custo" in h
assert "fora do ranking: Sem Verba" in h and h.index("Black Friday 2026") < h.index("Dia das Mães 2026")
secao("campanhas: ranking por ROAS, melhor/menor retorno, abaixo do custo")
h = html(c.get("/comparar?visao=anuncios"))
assert "Maior receita" in h and "Maior CTR" in h and h.index("Fone frete grátis") < h.index("Capa reforçada")
assert "Fone frete grátis" not in html(c.get(f"/comparar?visao=anuncios&campanha_id={dm}"))
secao("anuncios: ranking, tags e filtro")
h = html(c.get("/comparar?visao=periodos&a_de=2026-11-20&a_ate=2026-11-21&b_de=2026-11-22&b_ate=2026-11-23"))
assert "-73,3%" in h and "variacao-ruim" in h and "variacao-neutro" in h
assert "Preencha as quatro datas" in html(c.get("/comparar?visao=periodos&a_de=2026-11-20"))
assert "Escolha os dois períodos" in html(c.get("/comparar?visao=periodos"))
secao("periodos: variacao, cor por sentido, validacoes")
h = html(c.get("/historico"))
assert h.index("23/11/2026") < h.index("20/11/2026") < h.index("03/05/2026") and "Total do filtro" in h
assert "23/11/2026" not in html(c.get(f"/historico?campanha_id={dm}"))
assert c.get("/api/historico").get_json()[0]["data"] == "2026-05-02"
secao("historico: ordem, total, filtro, API")

print("\n== API ==")
assert c.get("/api/campanhas/naoexiste").status_code == 404 and c.get("/api/anuncios/naoexiste").status_code == 404
assert c.post("/api/campanhas", json={"nome": "A", "orcamento_planejado": "abc"}).status_code == 400
assert c.post("/api/produtos", json={"nome": "P", "preco_unitario": -1}).status_code == 400
assert c.post("/api/anuncios", json={"titulo": "Via API", "campanha_id": bf, "produto_id": pr["Fone XY200"]}).status_code == 201
assert c.post("/api/investimentos", json={"campanha_id": "x", "investimento": 5}).status_code == 400
assert c.post("/api/metricas", json={"campanha_id": bf, "anuncio_id": an["Fone presente"], "impressoes": 10, "cliques": 1}).status_code == 400
secao("404 em id invalido e 400 em dados invalidos")


print("\n== Relatorios e exportacao CSV ==")
h = html(c.get("/relatorios"))
assert "Resumo por campanha" in h and "Desempenho por anúncio" in h and "Desempenho por produto" in h and "Exportar CSV" in h
assert "R$ 1.900,00" in h and "Imprimir ou salvar em PDF" in h
h = html(c.get(f"/relatorios?campanha_id={dm}"))
assert "Campanha: Dia das Mães 2026" in h and "Black Friday 2026" not in h.split("Resumo por campanha")[1].split("Resultados por dia")[0]
secao("tela de relatorios, com filtro por campanha")
r = c.get("/relatorios/exportar/campanhas.csv")
assert r.status_code == 200 and r.mimetype == "text/csv"
txt = r.get_data(as_text=True)
assert txt.startswith("\ufeff"), "falta o BOM (Excel nao leria os acentos)"
assert txt.splitlines()[0].lstrip("\ufeff") == ";".join(["Campanha", "Status", "Orçamento planejado", "Investido", "Impressões", "Cliques", "CTR (%)", "CPC",
                                                         "Visitas", "Vendas", "Taxa de conversão (%)", "Custo por venda", "Receita atribuída", "ROAS"])
assert "Black Friday 2026;ativa;3000,00;1500,00;30000;600;2,00;2,50;450;40;8,89;37,50;3400,00;2,27" in txt.splitlines()
secao("CSV de campanhas: BOM, separador ';', decimais com virgula, valores conferidos a mao")
txt = c.get(f"/relatorios/exportar/campanhas.csv?campanha_id={dm}").get_data(as_text=True)
assert "Dia das Mães 2026" in txt and "Black Friday 2026" not in txt
txt = c.get("/relatorios/exportar/metricas.csv").get_data(as_text=True)
linhas = txt.lstrip("\ufeff").splitlines()
assert linhas[0] == "Data;Campanha;Anúncio;Produto;Impressões;Cliques;Visitas;Vendas;Receita atribuída"
assert len(linhas) >= 4
assert any(l.startswith("2026-11-21;Black Friday 2026;Fone frete grátis;Fone XY200;10000;400;300;30;3000,00") for l in linhas)
txt = c.get("/relatorios/exportar/investimentos.csv").get_data(as_text=True)
assert "2026-11-20;Black Friday 2026;1000,00" in txt
assert "Fone XY200" in c.get("/relatorios/exportar/produtos.csv").get_data(as_text=True)
assert "Fone frete grátis" in c.get("/relatorios/exportar/anuncios.csv").get_data(as_text=True)
assert "2026-11-23" in c.get("/relatorios/exportar/dias.csv").get_data(as_text=True)
secao("CSV de metricas, investimentos, produtos, anuncios e dias")
assert c.get("/relatorios/exportar/lixo.csv").status_code == 404
assert c.get("/relatorios/exportar/campanhas.csv?de=2026-12-10&ate=2026-12-01").status_code == 400
secao("exportacao: tipo inexistente (404) e filtro invalido (400)")

print("\n== Indicadores e controle de orcamento ==")
h = html(c.get("/indicadores"))
assert "Indicadores por campanha" in h and "2,27x" in h and "Todas as campanhas" in h
assert "(Cliques ÷ Impressões) × 100" in h and "Receita atribuída ÷ Investimento" in h and "Custo por venda" in h
secao("tela de Indicadores: 5 indicadores por campanha, total geral e formulas do documento")
h = html(c.get("/investimentos"))
assert "Controle de orçamento" in h and "do orçamento" in h
secao("painel de controle de orcamento na tela de Investimentos (RF01)")

print("\n== Edicao ==")
assert c.get(f"/campanhas/{bf}/editar").status_code == 200 and "Black Friday 2026" in html(c.get(f"/campanhas/{bf}/editar"))
r = c.post(f"/campanhas/{bf}/editar", data={"nome": "BF Editada", "data_inicio": "2026-11-20", "data_fim": "2026-11-30", "orcamento_planejado": "1.500,00", "status": "ativa"})
assert r.status_code == 200 and "Orçamento inválido" in html(r) and 'value="BF Editada"' in html(r)
secao("edicao com erro nao perde o que foi digitado")
assert "Status inválido" in html(c.post(f"/campanhas/{bf}/editar", data={"nome": "X", "orcamento_planejado": "1", "status": "inventado"}))
assert "data de fim não pode ser anterior" in html(c.post(f"/campanhas/{bf}/editar", data={"nome": "X", "data_inicio": "2026-12-10", "data_fim": "2026-12-01", "orcamento_planejado": "1", "status": "ativa"}))
r = c.post(f"/campanhas/{bf}/editar", data={"nome": "Black Friday 2026 (revisada)", "data_inicio": "2026-11-20", "data_fim": "2026-11-30", "orcamento_planejado": "3500,00", "status": "pausada"}, follow_redirects=True)
assert "atualizada" in html(r) and "Black Friday 2026 (revisada)" in html(r)
camp = c.get(f"/api/campanhas/{bf}").get_json()
assert camp["status"] == "pausada" and camp["orcamento_planejado"] == 3500 and camp["nome"] == "Black Friday 2026 (revisada)"
assert camp["total_investido"] == 1500 and camp["roas"] == 2.27, "editar nao pode mexer nos totais"
assert "Black Friday 2026 (revisada)" in html(c.get("/anuncios"))
secao("campanha editada: nome, orcamento e status mudam; totais e anuncios continuam ligados")
r = c.get("/campanhas/naoexiste/editar", follow_redirects=True)
assert "Campanha não encontrada" in html(r)
r = c.post(f"/produtos/{pr['Fone XY200']}/editar", data={"nome": "Fone XY200 Pro", "categoria": "Áudio", "preco_unitario": "99,90"}, follow_redirects=True)
assert "atualizado" in html(r) and "R$ 99,90" in html(r)
assert "Preço inválido" in html(c.post(f"/produtos/{pr['Fone XY200']}/editar", data={"nome": "X", "preco_unitario": "1.500,00"}))
secao("produto editado")
r = c.post(f"/anuncios/{an['Fone frete grátis']}/editar", data={"titulo": "Fone frete grátis v2", "produto_id": pr["Capa S23"], "status": "pausado", "codigo_marketplace": "MLB1"}, follow_redirects=True)
assert "atualizado" in html(r) and "Fone frete grátis v2" in html(r)
assert "produto válido" in html(c.post(f"/anuncios/{an['Fone frete grátis']}/editar", data={"titulo": "X", "produto_id": "naoexiste", "status": "ativo"}))
assert "Status inválido" in html(c.post(f"/anuncios/{an['Fone frete grátis']}/editar", data={"titulo": "X", "produto_id": pr["Capa S23"], "status": "zzz"}))
anuncio = c.get(f"/api/anuncios/{an['Fone frete grátis']}").get_json()
assert anuncio["campanha_id"] == bf and anuncio["status"] == "pausado" and anuncio["produto_id"] == pr["Capa S23"]
secao("anuncio editado (a campanha nao muda) e validacoes")

print("\n== Exclusao de registros lancados por engano ==")
inv_bf = [i for i in c.get("/api/investimentos").get_json() if i["campanha_id"] == bf and i["investimento"] == 500][0]
r = c.post(f"/investimentos/{inv_bf['id']}/excluir", follow_redirects=True)
assert "Investimento excluído" in html(r)
camp = c.get(f"/api/campanhas/{bf}").get_json()
assert camp["total_investido"] == 1000 and camp["roas"] == 3.4 and camp["cpc"] == 1.67
secao("investimento excluido: total, CPC e ROAS recalculados (R$ 1.000 / 1,67 / 3,4)")
met_bf = [m for m in c.get("/api/metricas").get_json() if m["campanha_id"] == bf and m["receita_atribuida"] == 400][0]
r = c.post(f"/metricas/{met_bf['id']}/excluir", follow_redirects=True)
assert "Métrica excluída" in html(r)
camp = c.get(f"/api/campanhas/{bf}").get_json()
assert camp["total_receita"] == 3000 and camp["total_impressoes"] == 10000 and camp["roas"] == 3.0 and camp["ctr"] == 4.0
secao("metrica excluida: totais, CTR e ROAS recalculados")
assert "não encontrado" in html(c.post("/investimentos/naoexiste/excluir", follow_redirects=True))
assert "não encontrada" in html(c.post("/metricas/naoexiste/excluir", follow_redirects=True))
assert c.get("/investimentos/naoexiste/excluir").status_code == 405
secao("exclusao de id inexistente avisa; exclusao so por POST")


print("\n== Login, sessao e CSRF (RNF03) ==")
A.app.config["AUTENTICACAO_ATIVA"] = True
A.app.config["CSRF_ATIVO"] = True
A.usuarios_collection._docs.clear()
A.TENTATIVAS_LOGIN.clear()
v = A.app.test_client()          # visitante


def token(cli, rota):
    return re.search(r'name="_csrf" value="([^"]+)"', cli.get(rota).get_data(as_text=True)).group(1)


r = v.get("/")
assert r.status_code == 302 and r.headers["Location"].endswith("/primeiro-acesso")
assert v.get("/api/campanhas").status_code == 401
assert v.get("/relatorios/exportar/campanhas.csv").status_code == 302
secao("visitante e levado ao primeiro acesso; API responde 401; CSV protegido")
r = v.post("/primeiro-acesso", data={"nome": "Ana", "usuario": "ana", "senha": "senha-forte-1", "confirmacao": "senha-forte-1"}, follow_redirects=True)
assert "sessão expirou" in html(r) and not A.usuarios_collection._docs
secao("formulario sem token CSRF e recusado")
base = {"nome": "Ana", "usuario": "Ana", "senha": "curta", "confirmacao": "curta"}
assert "pelo menos 8 caracteres" in html(v.post("/primeiro-acesso", data={**base, "_csrf": token(v, "/primeiro-acesso")}, follow_redirects=True))
assert "não confere" in html(v.post("/primeiro-acesso", data={**base, "senha": "senha-forte-1", "confirmacao": "outra-coisa-1", "_csrf": token(v, "/primeiro-acesso")}, follow_redirects=True))
r = v.post("/primeiro-acesso", data={**base, "senha": "senha-forte-1", "confirmacao": "senha-forte-1", "_csrf": token(v, "/primeiro-acesso")}, follow_redirects=True)
assert "Seu acesso foi criado" in html(r) and "Sair" in html(r)
doc = A.usuarios_collection._docs[0]
assert doc["usuario"] == "ana" and doc["senha_hash"] != "senha-forte-1" and doc["senha_hash"].startswith("pbkdf2:")
secao("primeiro acesso: senha curta e confirmacao errada recusadas; senha guardada so como hash")
assert v.get("/primeiro-acesso").status_code == 302 and v.get("/dashboard").status_code == 200
secao("primeiro acesso fecha depois do 1o usuario; usuario logado ve o sistema")
tk = token(v, "/campanhas")
antes = len(A.campanhas_collection._docs)
v.post("/campanhas/nova", data={"nome": "Sem token", "orcamento_planejado": "1"})
assert len(A.campanhas_collection._docs) == antes
v.post("/campanhas/nova", data={"nome": "Com token", "orcamento_planejado": "1", "_csrf": tk})
assert len(A.campanhas_collection._docs) == antes + 1
secao("POST sem token nao grava; com token grava")
assert v.post("/sair", data={"_csrf": token(v, "/campanhas")}).status_code == 302
r = v.get("/dashboard?campanha_id=x")
assert r.status_code == 302 and r.headers["Location"].startswith("/login?proximo=")
secao("sair encerra a sessao; o login lembra a tela que o usuario queria")
assert "Usuário ou senha incorretos" in html(v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "ana", "senha": "errada"}, follow_redirects=True))
assert "Usuário ou senha incorretos" in html(v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "naoexiste", "senha": "x"}, follow_redirects=True))
secao("senha errada e usuario inexistente recebem a mesma mensagem")
r = v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "ana", "senha": "senha-forte-1", "proximo": "//evil.com"})
assert r.status_code == 302 and "evil.com" not in r.headers["Location"]
v.post("/sair", data={"_csrf": token(v, "/campanhas")})
r = v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "ana", "senha": "senha-forte-1", "proximo": "/historico"})
assert r.status_code == 302 and r.headers["Location"].endswith("/historico")
v.post("/sair", data={"_csrf": token(v, "/campanhas")})
secao("login seguro: nao redireciona para outro site e volta para a tela pedida")
A.TENTATIVAS_LOGIN.clear()
for _ in range(5):
    v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "ana", "senha": "errada"})
r = v.post("/login", data={"_csrf": token(v, "/login"), "usuario": "ana", "senha": "senha-forte-1"})
assert r.status_code == 429 and "Muitas tentativas" in html(r)
A.TENTATIVAS_LOGIN.clear()
secao("apos 5 erros seguidos o login bloqueia, mesmo com a senha certa")
os.environ["API_KEY"] = "chave-de-teste"
anon = A.app.test_client()
assert anon.get("/api/campanhas", headers={"X-API-Key": "chave-de-teste"}).status_code == 200
assert anon.get("/api/dashboard", headers={"X-API-Key": "chave-de-teste"}).status_code == 200
assert anon.get("/api/campanhas", headers={"X-API-Key": "errada"}).status_code == 401
assert anon.get("/api/campanhas").status_code == 401
assert anon.get("/campanhas", headers={"X-API-Key": "chave-de-teste"}).status_code == 302
del os.environ["API_KEY"]
assert anon.get("/api/campanhas", headers={"X-API-Key": ""}).status_code == 401
secao("chave de API (Excel/Power BI): vale so para /api/; cabecalho vazio nunca passa")
assert A.app.config["AUTENTICACAO_ATIVA"] and A.app.config["CSRF_ATIVO"]

print("\nTODOS OS TESTES PASSARAM\n")
