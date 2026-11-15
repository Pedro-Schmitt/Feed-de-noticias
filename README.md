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

A aba **Jurisprudência relativa à sua atuação** mostra os últimos informativos do STF (cinco) e do STJ (três) comentados no Dizer o Direito (`informativos.py`): o feed do Blogger traz o índice de cada informativo (ramo, assunto e cada julgado com as marcas ⭐ 🏛️ 🔄), e o PDF completo é lido para levar cada julgado à sua página. Como os tribunais publicam o informativo semanas antes do comentário, no início de cada quadro há um aviso com os informativos já publicados pelo STF ou pelo STJ e ainda não comentados, com o link de cada um no site do tribunal (a página de informativos do STF e a do Informativo de Jurisprudência do STJ dão o número mais recente). Os informativos novos (últimos 7 dias) são marcados, e a indicação dos julgados que interessam ao MP estadual é automática, por regras de tema: o julgado cita o MP ou é de área típica de atuação do MP.

Abaixo dos informativos, **Entendimentos do CNMP e do CNJ** traz os atos normativos mais recentes de cada conselho (`normas.py`): do CNMP, as resoluções, recomendações, enunciados, súmulas, assentos e emendas regimentais da página "Atos e Normas" (sem as portarias e os acordos); do CNJ, as resoluções, recomendações, enunciados administrativos e provimentos da pesquisa de atos. **Novidades legislativas** traz as leis, leis complementares e emendas constitucionais dos últimos 60 dias: as federais pelos dados abertos do Senado (com o link do texto no Planalto) e as de Goiás pela API do Legisla, da Casa Civil, sem as de homenagens, datas comemorativas e créditos orçamentários. Atos e leis recebem as matérias pela ementa e seguem o mesmo filtro da jurisprudência (os atos do CNMP sem matéria específica, sobre a carreira e o funcionamento do MP, aparecem sempre). Na aba MPGO, abaixo das três colunas do quadro do MPGO, ficam os **próximos cursos e eventos da ESUMP** (`esump.py`), lidos da página de cursos e eventos da Escola Superior no portal do MPGO, com a data do evento tirada do título ou do texto.

No início da página, o bloco **Sua Promotoria de Justiça** pede ao promotor que escolha a sua Promotoria de Justiça (lista oficial do MPGO, "Encontre uma promotoria"); a escolha fica salva no navegador. A escolha define as **matérias** da promotoria, lidas do texto da atribuição na lista oficial ("plena" vale como todas), e a área **Jurisprudência** passa a mostrar só os julgados pertinentes a essas matérias (com a opção de ver todos os de interesse do MP); a mesma lista de matérias (`MATERIAS`, em `informativos.py`) classifica os julgados e as atribuições. A área **Notícias específicas da sua região** mostra as notícias da comarca (a sede e os demais municípios atendidos, conforme a lista oficial do MPGO — ex.: Ceres e Carmo do Rio Verde) e da região geográfica imediata do IBGE em que ela fica (`regional.py`). Abaixo vêm o **Radar de acontecimentos na comarca** — as notícias da comarca classificadas por palavras de cada matéria (`RADAR`, em `regional.py`) e filtradas pelas matérias da promotoria escolhida; com o secret `ANTHROPIC_API_KEY` configurado no GitHub, o Claude (`radar.py`) resume cada fato, explica por que ele pode exigir a atuação do MP e descarta o que não pede atuação, e cada notícia é analisada uma vez só — e as **Câmaras Municipais** dos municípios da comarca: três principais notícias e, para as câmaras que publicam as sessões no SAPL do Interlegis (lista em `dados/camaras_sapl.json`), a agenda das sessões. As notícias mostradas no quadro das câmaras não se repetem nos quadros da comarca e da região. O botão **"Respondendo por mais de uma promotoria? Selecione outro órgão"** acrescenta outras promotorias (também salvas no navegador): as matérias se somam na jurisprudência, e cada comarca escolhida ganha seus quadros. Abaixo do radar fica **Instituições que merecem seu acompanhamento** — escolas (Censo Escolar do INEP, agrupadas pela natureza: federais, estaduais, municipais e privadas), unidades de saúde num grupo só — hospitais e pronto atendimento, UBS e CAPS (CNES) —, CRAS, CREAS, Centros POP, centros-dia e unidades de acolhimento de crianças e adolescentes (inclusive família acolhedora), idosos e mulheres (Censo SUAS, com endereço e telefone) e unidades prisionais (SISDEPEN) dos municípios da comarca. As instituições vêm separadas por cidade e, em cada uma, primeiro os tipos ligados às matérias da promotoria (as unidades prisionais também para a promotoria criminal, e saúde, educação, idosos e assistência social também para a do cidadão); os demais ficam numa parte recolhida logo abaixo. Clicar no nome de uma instituição mostra o endereço completo, o telefone e o link do mapa. Essas bases ficam numa cópia em `dados/instituicoes.json`; para atualizar, rode `python instituicoes.py --atualizar` (se o Python recusar o certificado do INEP, baixe o .zip do Censo Escolar e passe `--censo arquivo.zip`, ou use `--manter-escolas` para atualizar o resto e manter as escolas da cópia; os .zip do IDEB por escola podem ir numa pasta, com `--ideb pasta`). Por fim, o **Retrato da comarca em números** traz: a **violência e segurança pública** (SINESP VDE, do Ministério da Justiça, mês a mês nos últimos cinco anos) com as mortes violentas intencionais (CVLI) dos últimos 12 meses, a tendência frente aos 12 anteriores, a taxa por 100 mil habitantes comparada com Goiás, o mapa dos municípios da comarca pela taxa, as mortes violentas ano a ano por tipo e a tabela de cada evento (o SINESP publica por município só os crimes contra a vida, as mortes no trânsito, os suicídios e os mandados de prisão; estupro, roubo e furto de veículo e tráfico vêm com o total de Goiás); a **lotação** das unidades prisionais (presos sobre vagas, SISDEPEN) e do acolhimento de crianças e adolescentes e de idosos (acolhidos sobre a capacidade, Censo SUAS); a **qualidade das escolas** pelo IDEB de cada escola (INEP), por etapa, com a mediana das escolas públicas de Goiás; e a **saúde** de cada município — mortalidade infantil e internações por diarreia (IBGE Cidades) e leitos SUS e de UTI (CNES), comparados com Goiás, e os leitos de cada hospital. Esses indicadores ficam numa cópia em `dados/indicadores.json`; para atualizar, rode `python indicadores.py --atualizar` (as planilhas do SINESP já baixadas podem ir numa pasta, com `--vde pasta`). As planilhas do INEP e do SINESP são lidas por `xlsx_simples.py`, sem dependências. Se o portal do MPGO estiver fora do ar, a lista de promotorias vem da cópia em `dados/promotorias.json`. Os municípios e regiões do IBGE ficam numa cópia em `dados/ibge_municipios.json`, porque a API do IBGE não responde aos servidores do GitHub; para atualizar, rode `python regional.py --atualizar-ibge`. Como o site publicado é estático, as notícias das comarcas, regiões e câmaras (cerca de 400 buscas) são geradas antes, 90 buscas por execução (o estado inteiro se renova a cada ~2h15); cada execução lê o `regional/estado.json` publicado e atualiza os locais mais antigos. Cidades com nome repetido em outros estados ou que são palavras comuns só entram em notícias que citam "Goiás".

No alto da página fica **Sua Promotoria de Justiça** (seletor); abaixo, quatro abas (a escolhida fica salva no navegador e no endereço, ex.: `#mpgo`): **Brasil e Mundo** (Política, Economia, Tecnologia e Cibersegurança e Mundo, com 20 notícias cada: cinco à mostra e o botão "Carregar mais notícias" para o resto; notícias jurídicas de Outros MPs do País, STF, STJ e TJGO; Presidente, Senado e Câmara com notícias e agenda; e Cotações); **Sua região** (comarca e região da promotoria escolhida, radar de acontecimentos, câmaras municipais, instituições que merecem acompanhamento e o retrato da comarca em números); **MPGO** (notícias, editais abertos, o CSMP com notícias e pauta, e os eventos da ESUMP); e **Jurisprudência relativa à sua atuação** (informativos do STF e do STJ, atos do CNMP e do CNJ, leis federais e de Goiás).

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

Jurisprudência e normas: **Dizer o Direito** (informativos comentados), sites do **STF** e do **STJ** (aviso dos ainda não comentados), **CNMP** e **CNJ** (atos normativos), dados abertos do **Senado Federal** (leis federais) e **Legisla** da Casa Civil de Goiás (leis estaduais). Eventos: página da **ESUMP** no portal do MPGO.

Instituições e retrato da comarca: **INEP** (Censo Escolar e IDEB por escola), **CNES** (unidades de saúde e leitos), **SISDEPEN** (unidades prisionais), **Censo SUAS** (assistência social e acolhimento), **SINESP VDE** do Ministério da Justiça (segurança pública) e **IBGE** (municípios, população, mortalidade infantil, internações por diarreia e malha municipal).

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
