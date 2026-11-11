# Notícias do Brasil

Site em Python que reúne as principais notícias do Brasil das últimas 48 horas, a partir dos feeds RSS dos maiores veículos do país, com filtros por editoria (Política, Economia, Brasil, Mundo, Esportes, Saúde e Tecnologia), por veículo e busca.

A seção **Em destaque** mostra os assuntos que mais de um veículo noticiou nas últimas 24 horas (ex.: "em 4 veículos"), com links para a versão de cada um.

## Como rodar

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Depois abra http://localhost:5000. Os feeds são consultados no máximo a cada 10 minutos, e a página se recarrega sozinha no mesmo intervalo. Para ver no terminal o que foi coletado e os destaques, rode `python coletor.py`.

## Fontes

- **G1** e **ge** (Globo)
- **Folha de S.Paulo**
- **Estadão**
- **Agência Brasil** (EBC)
- **CNN Brasil**, **Poder360** e **BBC News Brasil** (feeds gerais; a editoria é deduzida do endereço da notícia)

A lista de feeds fica em `FEEDS`, no começo de `coletor.py`. Títulos, resumos e imagens são dos próprios veículos, e cada notícia leva para a matéria no site original.

## Publicação no Firebase

O site publicado é uma versão estática gerada por `python gerar_site.py` na pasta `public/` (HTML, `static/` e `noticias.json`). O workflow `.github/workflows/deploy.yml` faz isso de 30 em 30 minutos, a cada push na `main` ou manualmente, e publica no Firebase Hosting. Se mais da metade dos feeds falhar, nada é publicado e a versão anterior continua no ar.

Configuração (uma vez só):

1. Crie um projeto em https://console.firebase.google.com e ative o Hosting.
2. O ID do projeto (`feed-de-atualizacoes---pedro`) fica em `.firebaserc` e em `.github/workflows/deploy.yml`. O site publicado fica em https://feed-de-atualizacoes---pedro.web.app.
3. Em Configurações do projeto → Contas de serviço, gere uma nova chave privada e salve o conteúdo do JSON como secret `FIREBASE_SERVICE_ACCOUNT` no GitHub (Settings → Secrets and variables → Actions).
4. Faça push e, se quiser, rode o workflow manualmente pela aba Actions ("Run workflow").
5. Recomendado: em Hosting → Histórico de versões, limite a retenção (ex.: 10 versões), já que são ~48 publicações por dia.
