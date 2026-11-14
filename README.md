# AdControl Web — versão inicial (API + tela)

Sistema web de gestão de publicidade da Presente na Web. Módulos prontos:
**Campanhas (RF02)**, **Anúncios (RF03)**, **Produtos (RF04)**, **Investimentos (RF01)**,
**Métricas (RF05)**, **Indicadores calculados automaticamente (RF06)** e **Margem Pós-Anúncios (RF10)**,
mais **Dashboard com gráficos (RF07)**, **filtros por campanha e período (RF08)**,
**comparação de campanhas, anúncios e períodos (RF09)** e **Histórico** dia a dia.
Os requisitos RF01 a RF09 e a regra RF10 estão implementados. Também há a tela de **Indicadores**,
**Relatórios gerenciais** com exportação CSV (Excel e Power BI), edição de cadastros e **acesso restrito por login** (RNF03).

## O que já tem
- Telas: Visão geral, Dashboard, Indicadores, Comparar, Histórico, Relatórios, Campanhas, Anúncios, Produtos, Investimentos e Métricas, mais Login
- API REST em Flask: `/api/campanhas`, `/api/anuncios`, `/api/produtos`, `/api/investimentos`, `/api/metricas`, `/api/dashboard`, `/api/historico` (os dois últimos aceitam `?campanha_id=&de=&ate=`, bons para Excel e Power BI)
- Persistência em MongoDB (banco NoSQL orientado a documentos)
- Valores no padrão brasileiro (R$ 1.234,50 e datas dd/mm/aaaa); os campos aceitam vírgula ou ponto
- Validações: campos numéricos, período da campanha, cliques não podem passar das impressões, anúncio precisa pertencer à campanha da métrica
- Desempenho individual de cada anúncio e total por produto (soma dos anúncios do produto)
- MPA estimada por produto: receita atribuída menos custo do produto e frete por unidade vendida, percentuais de taxas/impostos e parcela do investimento da campanha

## Regra de negócio RF10 — Margem Pós-Anúncios (MPA)

Para cada produto, a MPA é calculada em reais: `receita atribuída − custo do produto vendido − frete do vendedor − taxas − impostos − investimento em anúncios rateado`. O investimento de uma campanha é distribuído entre seus produtos proporcionalmente à receita atribuída de cada produto sobre a receita total da campanha; receitas sem anúncio associado não são transferidas para outros produtos. O sistema alerta quando a MPA é negativa ou é igual ou inferior a 12% da receita atribuída. É uma estimativa gerencial com os custos cadastrados atualmente no produto, não uma apuração contábil histórica.

## Estrutura de pastas
```
adcontrol_api/
├── app.py              # rotas da API e das telas
├── analise.py          # cálculos: indicadores, séries, funil, gráficos (sem Flask/Mongo)
├── banco.py            # conexão MongoDB e coleções
├── especialista.py     # cálculo estimado da MPA e alertas por regras
├── relatorios.py       # montagem e exportação dos relatórios
├── render.yaml         # configuração de hospedagem no Render
├── requirements.txt    # dependências
├── tests/
│   ├── rodar_testes.py  # testes automáticos (rodam sem MongoDB)
│   └── stub_mongo/      # banco de mentira em memória, usado só pelos testes
├── templates/
│   ├── base.html        # menu lateral e estrutura comum a todas as telas
│   ├── index.html       # visão geral
│   ├── campanhas.html, anuncios.html, produtos.html, investimentos.html, metricas.html
└── static/
    └── style.css        # identidade visual
```

## Como rodar

1. Instale o Python 3.10+ (se ainda não tiver).
2. Tenha um MongoDB disponível. Duas opções:
   - Instalar localmente: https://www.mongodb.com/try/download/community
   - Usar o MongoDB Atlas (gratuito, na nuvem): https://www.mongodb.com/cloud/atlas/register
3. No terminal, dentro da pasta do projeto:
   ```
   pip install -r requirements.txt
   ```
4. Se for usar o Atlas, defina a variável de ambiente com a sua string de conexão
   (troque usuário/senha/cluster pelos seus dados reais):
   ```
   # Windows (PowerShell)
   $env:MONGO_URI = "mongodb+srv://usuario:senha@seucluster.mongodb.net/adcontrol_web"

   # Mac/Linux
   export MONGO_URI="mongodb+srv://usuario:senha@seucluster.mongodb.net/adcontrol_web"
   ```
   Se você não definir nada, o sistema tenta se conectar em
   `mongodb://localhost:27017/adcontrol_web`.
5. Rode o servidor:
   ```
   python app.py
   ```
6. Abra o navegador em http://127.0.0.1:5000. No **primeiro acesso** o sistema pede para criar o usuário
   administrador (nome, usuário e senha de 8 caracteres ou mais). Depois disso, só entra quem tiver usuário e senha.

As fontes (Space Grotesk e IBM Plex Sans) vêm do Google Fonts: precisam de internet
para aparecer; sem internet o sistema usa uma fonte padrão e continua funcionando.
Opcional: defina `SECRET_KEY` (mesmo método do `MONGO_URI`) com um texto próprio.

## Publicar na nuvem (Render + MongoDB Atlas)

Uma configuração simples para este projeto é hospedar o Flask no Render e manter os dados no MongoDB Atlas. O repositório já inclui `render.yaml` para configurar o serviço.

1. Envie o projeto para um repositório GitHub.
2. No Atlas, crie um cluster e um **usuário de banco de dados** para a aplicação. Use uma senha exclusiva e guarde a URI de conexão; não a coloque no código nem no Git.
3. No Render, crie um Web Service conectado ao repositório e configure pelo Blueprint `render.yaml`.
4. No serviço, defina `MONGO_URI` com a URI do Atlas. O Render gera `SECRET_KEY`; `COOKIES_SEGUROS=1` já está configurado para HTTPS.
5. Na lista de acesso de rede do Atlas, permita a conexão de saída do serviço Render. Para demonstrações, `0.0.0.0/0` é simples, mas permite tentativas de conexão de qualquer endereço; use senha forte e um usuário com acesso somente ao banco `adcontrol_web`. Em plano pago, prefira restringir a lista às faixas estáticas de saída da hospedagem.
6. Após o deploy, abra a URL pública. Na primeira visita, crie o usuário do sistema. A rota `/health` permite ao Render verificar se a aplicação está respondendo.

O plano gratuito do Render pode suspender o site após 15 minutos sem acessos, e a próxima visita pode demorar para reativá-lo. O cluster gratuito do Atlas também tem limites e pode pausar após 30 dias sem conexões. São opções para aprendizado e demonstrações, não para um serviço que precise de disponibilidade contínua.

## Testando a API diretamente (Postman, Insomnia ou navegador)
- Listar campanhas: `GET http://127.0.0.1:5000/api/campanhas`
- Buscar uma campanha: `GET http://127.0.0.1:5000/api/campanhas/<id>`
- Cadastrar campanha: `POST http://127.0.0.1:5000/api/campanhas` com corpo JSON, exemplo:
  ```json
  {
    "nome": "Black Friday 2026",
    "data_inicio": "2026-11-20",
    "data_fim": "2026-11-30",
    "orcamento_planejado": 1500.00
  }
  ```

## Como rodar os testes
```
python tests/rodar_testes.py
```
Roda sem MongoDB (usa um banco de mentira em memória). Se algo falhar, mostra qual teste caiu.

## Como foi testado
Antes de entregar, todas as rotas foram testadas automaticamente (tela e API):
cadastro pelo formulário, listagem, cadastro via JSON e validação de campo
obrigatório (nome). Isso não substitui testar com o
MongoDB real rodando — faça isso antes de apresentar para a turma.

## Próximos passos (a combinar com o grupo)
- Módulo de Produtos e Anúncios
- Registro de Investimentos e Métricas
- Cálculo automático dos indicadores (CTR, CPC, conversão, custo por venda, ROAS)
- Dashboard consolidado
- Autenticação de usuário (ainda não é um requisito oficial do projeto)


## Acesso e segurança (RNF03)
- Todas as telas e a API exigem login. A senha é guardada só como hash (nunca em texto).
- Formulários têm token CSRF. Após 5 erros de senha seguidos o login bloqueia por alguns minutos.
- **Excel e Power BI na API:** defina a variável `API_KEY` e envie o cabeçalho `X-API-Key` nas chamadas a `/api/...`. A chave vale só para a API, não para as telas.
- Variáveis de ambiente: `MONGO_URI` (banco), `SECRET_KEY` (texto próprio, obrigatório em uso real), `API_KEY` (opcional),
  `COOKIES_SEGUROS=1` (quando o site estiver em https) e `FLASK_DEBUG=1` (só em desenvolvimento; por padrão fica desligado).
- Limitações: sem recuperação de senha e sem vários perfis de usuário. Para redefinir, apague o documento do usuário na coleção `usuarios`.

## Relatórios e exportação
- A tela **Relatórios** traz o resumo por campanha, os resultados por dia e o desempenho por anúncio e por produto, com filtro de campanha e período.
- **Exportar CSV:** cada relatório tem seu botão, e há dois arquivos de dados brutos (métricas e investimentos) para análises estatísticas.
  O arquivo usa ponto e vírgula, decimais com vírgula e UTF-8 com BOM, que o Excel em português abre direto.
- **Imprimir ou salvar em PDF** usa a impressão do navegador, com layout próprio para papel.

oimatheus
