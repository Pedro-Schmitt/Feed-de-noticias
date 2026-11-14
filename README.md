# Revista do Promotor

Site em Python que mostra as **cinco principais notícias de Política, Economia, Tecnologia e Cibersegurança e Mundo** (cibersegurança vem também de uma busca no Google Notícias, com no máximo dois assuntos só dela entre os cinco), a partir dos feeds RSS dos maiores veículos do país, e logo abaixo os **gráficos de cotação em R$** do dólar, euro, bitcoin, ethereum, Tron e Tether (filtros de 5 anos a 1 dia).

Há também um bloco de **notícias jurídicas** com as cinco principais sobre o STF, o STJ, o TJGO, os demais Ministérios Públicos do país (quadro "Outros MPs do País", cada notícia com a etiqueta do MP de que trata: estadual, como MPSP, ou ramo do MPU, como MPF e MPT), o Ministério Público de Goiás (MPGO) e o Conselho Superior do MPGO (CSMP). Como esses órgãos não têm feed RSS acessível, as notícias vêm de buscas no Google Notícias (lista em `JURIDICO`, em `coletor.py`), que juntam os sites oficiais e a imprensa.

As agendas (`agendas.py`) vêm direto das fontes oficiais. O que está em julgamento no STF e no CSMP aparece dentro dos painéis de notícias desses órgãos; o bloco **Agendas** traz as do Presidente, do Senado e da Câmara, cada uma com as três principais notícias do órgão acima (busca no Google Notícias, `ORGAOS` em `coletor.py`):

- **Em julgamento no STF**: sessões virtuais em andamento (quantidade de processos no Plenário e nas Turmas) e a próxima sessão presencial com a lista de processos, relator e resumo do tema (serviços do calendário de julgamentos do portal do STF)
- **Em julgamento no CSMP do MPGO**: sessões em andamento e próximas, com o número de processos, os itens e os relatores, lidos do PDF da pauta publicado no portal do MPGO
- **Presidente da República**: compromissos do dia no site do Planalto (até a agenda do dia sair, mostra a última publicada)
- **Senado Federal**: sessões do Plenário (com as matérias em pauta) e reuniões das comissões, pelos dados abertos do Senado
- **Câmara dos Deputados**: eventos do dia (Plenário primeiro), pela API de dados abertos da Câmara

Senado e Câmara mostram o próximo dia com agenda quando não há nada hoje (ex.: fim de semana). Se uma fonte falhar, só aquele painel mostra um aviso.

No quadro do **MPGO** aparecem também os **editais de promoção e remoção com inscrições abertas** (`editais.py`): o site lê a página de editais do ano no portal do MPGO, abre o PDF dos editais recentes e tira a promotoria, a entrância, a forma e o critério de provimento, a data de publicação no Diário Oficial e o prazo (10 dias corridos a partir do 1º dia útil seguinte). O fim do prazo é calculado pelo site considerando fins de semana e feriados nacionais fixos.

A área **Jurisprudência** mostra os últimos informativos do STF (cinco) e do STJ (três) lidos direto nos sites dos tribunais (`informativos.py`): no STF, a página de informativos dá o número mais recente e cada edição (`informativoNNNN.htm`) traz ramo, título com o processo e o resumo; no STJ, a página do Informativo de Jurisprudência dá a última edição, e cada nota tem endereço próprio. Cada julgado abre no site do tribunal (no STF, já rolado até o trecho, por fragmento de texto). Como o Dizer o Direito comenta os informativos semanas depois, cada informativo traz também o link da versão comentada quando ela já existe (procurada pelo número no feed do Blogger). Os informativos novos (últimos 7 dias) são marcados, e a indicação dos julgados que interessam ao MP estadual é automática, por regras de tema: o julgado cita o MP ou é de área típica de atuação do MP.

No início da página, o bloco **Sua Promotoria de Justiça** pede ao promotor que escolha a sua Promotoria de Justiça (lista oficial do MPGO, "Encontre uma promotoria"); a escolha fica salva no navegador. A escolha define as **matérias** da promotoria, lidas do texto da atribuição na lista oficial ("plena" vale como todas), e a área **Jurisprudência** passa a mostrar só os julgados pertinentes a essas matérias (com a opção de ver todos os de interesse do MP); a mesma lista de matérias (`MATERIAS`, em `informativos.py`) classifica os julgados e as atribuições. A área **Notícias específicas da sua região** mostra as notícias da comarca (a sede e os demais municípios atendidos, conforme a lista oficial do MPGO — ex.: Ceres e Carmo do Rio Verde) e da região geográfica imediata do IBGE em que ela fica (`regional.py`). Abaixo vêm o **Radar de acontecimentos na comarca** — as notícias da comarca classificadas por palavras de cada matéria (`RADAR`, em `regional.py`) e filtradas pelas matérias da promotoria escolhida; com o secret `ANTHROPIC_API_KEY` configurado no GitHub, o Claude (`radar.py`) resume cada fato, explica por que ele pode exigir a atuação do MP e descarta o que não pede atuação, e cada notícia é analisada uma vez só — e as **Câmaras Municipais** dos municípios da comarca: três principais notícias e, para as câmaras que publicam as sessões no SAPL do Interlegis (lista em `dados/camaras_sapl.json`), a agenda das sessões. As notícias mostradas no quadro das câmaras não se repetem nos quadros da comarca e da região. O botão **"Respondendo por mais de uma promotoria? Selecione outro órgão"** acrescenta outras promotorias (também salvas no navegador): as matérias se somam na jurisprudência, e cada comarca escolhida ganha seus quadros. Abaixo do radar fica **Instituições que merecem seu acompanhamento** — escolas (Censo Escolar do INEP), hospitais, UBS e CAPS (CNES), unidades prisionais (SISDEPEN) e unidades de acolhimento de crianças e adolescentes, idosos e mulheres (Censo SUAS) dos municípios da comarca, mostradas conforme as matérias da promotoria. Essas bases ficam numa cópia em `dados/instituicoes.json`; para atualizar, rode `python instituicoes.py --atualizar` (se o Python recusar o certificado do INEP, baixe o .zip do Censo Escolar e passe `--censo arquivo.zip`). Se o portal do MPGO estiver fora do ar, a lista de promotorias vem da cópia em `dados/promotorias.json`. Os municípios e regiões do IBGE ficam numa cópia em `dados/ibge_municipios.json`, porque a API do IBGE não responde aos servidores do GitHub; para atualizar, rode `python regional.py --atualizar-ibge`. Como o site publicado é estático, as notícias das comarcas, regiões e câmaras (cerca de 400 buscas) são geradas antes, 90 buscas por execução (o estado inteiro se renova a cada ~2h15); cada execução lê o `regional/estado.json` publicado e atualiza os locais mais antigos. Cidades com nome repetido em outros estados ou que são palavras comuns só entram em notícias que citam "Goiás".

A página é dividida, de cima para baixo, em: **Sua Promotoria de Justiça** (seletor); **Notícias** (Política, Economia, Tecnologia e Cibersegurança e Mundo, com 20 notícias cada: cinco à mostra e o botão "Carregar mais notícias" para o resto, com rolagem); **Notícias específicas da sua região** (comarca e região da promotoria escolhida, também até 20; radar de acontecimentos na comarca; câmaras municipais com notícias e agenda); **Jurisprudência** (informativos do STF e do STJ); **Notícias jurídicas e agendas** (MPGO na linha inteira em três colunas — notícias, editais abertos e o CSMP —, depois Outros MPs do País, STF, STJ e TJGO; Presidente, Senado e Câmara com notícias e agenda) e **Cotações**.

As principais de cada editoria são os assuntos noticiados por mais veículos (ex.: "em 4 veículos"); no empate, vale o mais recente, e os assuntos das últimas 24 horas vêm antes. A primeira notícia de cada editoria traz links para a versão dos outros veículos. Notícias de esportes ficam de fora.

## Como rodar

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Depois abra http://localhost:5000. Os feeds são consultados no máximo a cada 10 minutos, e a página recarrega as notícias sozinha no mesmo intervalo. Para ver no terminal as principais de cada editoria, rode `python coletor.py`.

Na primeira execução o histórico de cotações desde 01/01/2021 é baixado para `cotacoes.db`; depois, só os dias novos, uma vez por dia.

## Fontes

Notícias (lista em `FEEDS`, no começo de `coletor.py`):

- **G1** (Globo)
- **Folha de S.Paulo**
- **Estadão**
- **Agência Brasil** (EBC)
- **CNN Brasil**, **Poder360** e **BBC News Brasil** (feeds gerais; a editoria é deduzida do endereço da notícia)

Títulos, resumos e imagens são dos próprios veículos, e cada notícia leva para a matéria no site original.

Cotações (`cotacoes.py`, o mesmo coletor do Projeto Site Cotações):

- **Dólar e euro**: Banco Central do Brasil (PTAX de venda, só dias úteis)
- **Bitcoin, Ethereum e Tether**: Binance (pares BTCBRL, ETHBRL e USDTBRL, fechamento diário em UTC)
- **Tron**: Binance (TRXUSDT × USDTBRL, porque não existe par TRX/BRL)
- **Filtro "1 dia"**: cotações de hora em hora das últimas 24h. Criptos pela Binance; dólar e euro pelo Yahoo Finance (cotação de mercado, não a PTAX)

## Publicação no Firebase

O site publicado é uma versão estática gerada por `python gerar_site.py` na pasta `public/` (HTML, `static/`, `noticias.json`, `agendas.json`, `cotacoes.json` e `intradia.json`). O workflow `.github/workflows/deploy.yml` faz isso de 30 em 30 minutos, a cada push na `main` ou manualmente, e publica no Firebase Hosting. Se mais da metade dos feeds falhar, nada é publicado e a versão anterior continua no ar; se só uma cotação falhar, o site é publicado sem aquele gráfico.

Configuração (uma vez só):

1. Crie um projeto em https://console.firebase.google.com e ative o Hosting.
2. O ID do projeto (`feed-de-atualizacoes---pedro`) fica em `.firebaserc` e em `.github/workflows/deploy.yml`. O site publicado fica em https://revista-do-promotor.web.app (um segundo site do mesmo projeto, configurado em `firebase.json`); o endereço antigo, https://feed-de-atualizacoes---pedro.web.app, redireciona para ele.
3. Em Configurações do projeto → Contas de serviço, gere uma nova chave privada e salve o conteúdo do JSON como secret `FIREBASE_SERVICE_ACCOUNT` no GitHub (Settings → Secrets and variables → Actions).
4. No Google Cloud (IAM e administrador → IAM), edite a conta `firebase-adminsdk-...` e adicione os papéis **Administrador do Firebase Hosting**, **Consumidor do Service Usage** e **Leitor de chaves de API**. Sem isso, o deploy falha com `PERMISSION_DENIED`.
5. Faça push e, se quiser, rode o workflow manualmente pela aba Actions ("Run workflow").
6. Recomendado: em Hosting → Histórico de versões, limite a retenção (ex.: 10 versões), já que são ~48 publicações por dia.
