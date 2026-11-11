# Revista do Promotor

Site em Python que mostra as **cinco principais notícias de Política, Economia, Tecnologia e Mundo**, a partir dos feeds RSS dos maiores veículos do país, e logo abaixo os **gráficos de cotação em R$** do dólar, euro, bitcoin, ethereum, Tron e Tether (filtros de 5 anos a 1 dia).

Há também um bloco de **notícias jurídicas** com as cinco principais sobre o STF, o STJ, o TJGO, o Ministério Público brasileiro, o Ministério Público de Goiás (MPGO) e o Conselho Superior do MPGO (CSMP). Como esses órgãos não têm feed RSS acessível, as notícias vêm de buscas no Google Notícias (lista em `JURIDICO`, em `coletor.py`), que juntam os sites oficiais e a imprensa.

As agendas (`agendas.py`) vêm direto das fontes oficiais. O que está em julgamento no STF e no CSMP aparece dentro dos painéis de notícias desses órgãos; o bloco **Agendas** traz as do Presidente, do Senado e da Câmara:

- **Em julgamento no STF**: sessões virtuais em andamento (quantidade de processos no Plenário e nas Turmas) e a próxima sessão presencial com a lista de processos, relator e resumo do tema (serviços do calendário de julgamentos do portal do STF)
- **Em julgamento no CSMP do MPGO**: sessões em andamento e próximas, com o número de processos, os itens e os relatores, lidos do PDF da pauta publicado no portal do MPGO
- **Presidente da República**: compromissos do dia no site do Planalto (até a agenda do dia sair, mostra a última publicada)
- **Senado Federal**: sessões do Plenário (com as matérias em pauta) e reuniões das comissões, pelos dados abertos do Senado
- **Câmara dos Deputados**: eventos do dia (Plenário primeiro), pela API de dados abertos da Câmara

Senado e Câmara mostram o próximo dia com agenda quando não há nada hoje (ex.: fim de semana). Se uma fonte falhar, só aquele painel mostra um aviso.

A área de notícias locais tem dois quadros, **Ceres** e **Vale do São Patrício**, cada um com as cinco principais notícias dos últimos 10 dias; o do Vale cobre as demais cidades (Rialma, Rubiataba, Goianésia, Itapaci, Itapuranga, Uruana e outras; lista em `CIDADES_VALE`, em `coletor.py`), também por buscas no Google Notícias.

A página é dividida em quatro áreas: 1) Notícias Gerais, 2) Notícias Locais de Ceres e Vale do São Patrício, 3) Notícias do Mundo Jurídico e Agenda dos Órgãos e 4) Cotações das Principais Moedas.

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
2. O ID do projeto (`feed-de-atualizacoes---pedro`) fica em `.firebaserc` e em `.github/workflows/deploy.yml`. O site publicado fica em https://feed-de-atualizacoes---pedro.web.app.
3. Em Configurações do projeto → Contas de serviço, gere uma nova chave privada e salve o conteúdo do JSON como secret `FIREBASE_SERVICE_ACCOUNT` no GitHub (Settings → Secrets and variables → Actions).
4. No Google Cloud (IAM e administrador → IAM), edite a conta `firebase-adminsdk-...` e adicione os papéis **Administrador do Firebase Hosting**, **Consumidor do Service Usage** e **Leitor de chaves de API**. Sem isso, o deploy falha com `PERMISSION_DENIED`.
5. Faça push e, se quiser, rode o workflow manualmente pela aba Actions ("Run workflow").
6. Recomendado: em Hosting → Histórico de versões, limite a retenção (ex.: 10 versões), já que são ~48 publicações por dia.
