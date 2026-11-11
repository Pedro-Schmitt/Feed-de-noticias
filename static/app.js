const CORES = {
  "G1": "#e0352b",
  "ge": "#0fa14c",
  "Folha": "#2f6fdb",
  "Estadão": "#8b5cf6",
  "Agência Brasil": "#0c9fb5",
  "CNN Brasil": "#e2408f",
  "Poder360": "#64748b",
  "BBC Brasil": "#e38b00",
};

const POR_PAGINA = 30;
const RECARREGAR_MS = 10 * 60 * 1000;

let dados = null;
let categoriaAtual = "todas";
let busca = "";
let exibidas = POR_PAGINA;

// Veículos exibidos na lista e modo da lista (a escolha fica salva no navegador)
const CHAVE_OCULTOS = "fontes-ocultas";
const CHAVE_MODO = "modo-lista";
let ocultos = new Set();
let modoLista = "cartoes";
try {
  const salvo = JSON.parse(localStorage.getItem(CHAVE_OCULTOS));
  if (Array.isArray(salvo)) ocultos = new Set(salvo);
  if (localStorage.getItem(CHAVE_MODO) === "lista") modoLista = "lista";
} catch { /* sem localStorage: mostra tudo */ }

function salvar(chave, valor) {
  try {
    localStorage.setItem(chave, valor);
  } catch { /* ignora */ }
}

function elemento(tag, classe, texto) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

function tempoRelativo(iso) {
  const minutos = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (minutos < 1) return "agora";
  if (minutos < 60) return `há ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `há ${horas} h`;
  return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function dataCompleta(iso) {
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "full", timeStyle: "short" });
}

function semAcento(texto) {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function etiquetaFonte(fonte) {
  const el = elemento("span", "fonte", fonte);
  el.style.setProperty("--cor", CORES[fonte] || "#6b7280");
  return el;
}

function linhaMeta(noticia, comFonte = true) {
  const meta = elemento("div", "meta");
  if (comFonte) meta.append(etiquetaFonte(noticia.fonte));
  meta.append(elemento("span", "", dados.categorias[noticia.categoria]));
  const hora = elemento("time", "", tempoRelativo(noticia.data));
  hora.dateTime = noticia.data;
  hora.title = dataCompleta(noticia.data);
  meta.append(hora);
  return meta;
}

function imagem(noticia) {
  const vazia = () => {
    const el = elemento("div", "imagem imagem-vazia", noticia.fonte);
    el.style.setProperty("--cor", CORES[noticia.fonte] || "#6b7280");
    el.setAttribute("aria-hidden", "true");
    return el;
  };
  if (!noticia.imagem || !noticia.imagem.startsWith("https://")) return vazia();
  const img = elemento("img", "imagem");
  img.src = noticia.imagem;
  img.alt = "";
  img.loading = "lazy";
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", () => img.replaceWith(vazia()), { once: true });
  return img;
}

function link(noticia, conteudo) {
  const a = elemento("a");
  a.href = noticia.link;
  a.target = "_blank";
  a.rel = "noopener";
  a.append(conteudo);
  return a;
}

function passaNosFiltros(noticia) {
  if (categoriaAtual !== "todas" && noticia.categoria !== categoriaAtual) return false;
  if (busca && !semAcento(`${noticia.titulo} ${noticia.resumo}`).includes(busca)) return false;
  return true;
}

// --- Filtros ---

function montarFiltros() {
  const nav = document.getElementById("filtros");
  nav.replaceChildren();
  const contagem = {};
  for (const n of dados.noticias) contagem[n.categoria] = (contagem[n.categoria] || 0) + 1;

  const opcoes = [["todas", "Todas", dados.noticias.length], ...Object.entries(dados.categorias).map(([id, nome]) => [id, nome, contagem[id] || 0])];
  for (const [id, nome, total] of opcoes) {
    const botao = elemento("button", id === categoriaAtual ? "ativo" : "", nome);
    botao.type = "button";
    botao.append(elemento("span", "contagem", total));
    botao.addEventListener("click", () => {
      categoriaAtual = id;
      exibidas = POR_PAGINA;
      for (const b of nav.children) b.classList.toggle("ativo", b === botao);
      renderizar();
    });
    nav.append(botao);
  }
}

function montarSeletorFontes() {
  const seletor = document.getElementById("seletor-fontes");
  seletor.replaceChildren();

  const atalho = (texto, acao) => {
    const botao = elemento("button", "atalho", texto);
    botao.type = "button";
    botao.addEventListener("click", () => {
      acao();
      salvar(CHAVE_OCULTOS, JSON.stringify([...ocultos]));
      montarSeletorFontes();
      renderizarLista();
    });
    return botao;
  };
  seletor.append(
    atalho("Todos", () => ocultos.clear()),
    atalho("Nenhum", () => { ocultos = new Set(dados.fontes); }),
    elemento("span", "divisor"),
  );

  for (const fonte of dados.fontes) {
    const chip = elemento("label", "chip");
    chip.style.setProperty("--cor", CORES[fonte] || "#6b7280");
    const caixa = elemento("input");
    caixa.type = "checkbox";
    caixa.checked = !ocultos.has(fonte);
    caixa.addEventListener("change", () => {
      if (caixa.checked) ocultos.delete(fonte);
      else ocultos.add(fonte);
      salvar(CHAVE_OCULTOS, JSON.stringify([...ocultos]));
      exibidas = POR_PAGINA;
      renderizarLista();
    });
    chip.append(caixa, fonte);
    seletor.append(chip);
  }
}

function montarAlternador() {
  const grupo = document.getElementById("modo-lista");
  for (const botao of grupo.querySelectorAll("button")) {
    botao.classList.toggle("ativo", botao.dataset.modo === modoLista);
    botao.addEventListener("click", () => {
      modoLista = botao.dataset.modo;
      salvar(CHAVE_MODO, modoLista);
      for (const b of grupo.children) b.classList.toggle("ativo", b === botao);
      renderizarLista();
    });
  }
}

// --- Destaques ---

function renderizarDestaques() {
  const caixa = document.getElementById("destaques");
  caixa.replaceChildren();
  const destaques = dados.destaques.filter((d) => passaNosFiltros(dados.noticias[d.principal]));

  if (!destaques.length) {
    caixa.append(elemento("p", "vazio", "Nenhum assunto em destaque com esses filtros."));
    return;
  }

  for (const d of destaques) {
    const principal = dados.noticias[d.principal];
    const card = elemento("article", "destaque");

    const balao = elemento("span", "balao", `🔥 em ${d.veiculos} veículos`);
    if (d.veiculos >= 4) balao.classList.add("balao-quente");
    else if (d.veiculos === 3) balao.classList.add("balao-morno");
    balao.title = `Assunto noticiado por ${d.veiculos} veículos diferentes nas últimas 24 horas`;

    const corpo = elemento("div", "corpo");
    const titulo = elemento("h3");
    titulo.append(link(principal, principal.titulo));
    corpo.append(linhaMeta(principal), titulo);
    if (principal.resumo) corpo.append(elemento("p", "resumo", principal.resumo));

    const tambem = elemento("ul", "tambem");
    for (const id of d.relacionadas) {
      const n = dados.noticias[id];
      const item = elemento("li");
      item.append(etiquetaFonte(n.fonte), link(n, n.titulo));
      tambem.append(item);
    }
    corpo.append(tambem);

    card.append(balao, link(principal, imagem(principal)), corpo);
    caixa.append(card);
  }
}

// --- Últimas notícias ---

function cartaoNoticia(noticia) {
  const corpo = elemento("div", "corpo");
  const meta = linhaMeta(noticia);
  if (noticia.veiculos_assunto) {
    const selo = elemento("span", "selo", `em ${noticia.veiculos_assunto} veículos`);
    selo.title = "Assunto noticiado por vários veículos nas últimas 24 horas";
    meta.append(selo);
  }
  corpo.append(meta, elemento("h3", "", noticia.titulo));
  if (noticia.resumo) corpo.append(elemento("p", "resumo", noticia.resumo));

  const frag = document.createDocumentFragment();
  frag.append(imagem(noticia), corpo);
  const a = link(noticia, frag);
  a.className = "noticia";
  return a;
}

function renderizarLista() {
  const lista = document.getElementById("lista");
  lista.classList.toggle("compacta", modoLista === "lista");
  lista.replaceChildren();

  const filtradas = dados.noticias.filter((n) => !ocultos.has(n.fonte) && passaNosFiltros(n));
  for (const noticia of filtradas.slice(0, exibidas)) lista.append(cartaoNoticia(noticia));
  if (!filtradas.length) lista.append(elemento("p", "vazio", "Nenhuma notícia encontrada com esses filtros."));

  const mais = document.getElementById("mais");
  mais.hidden = filtradas.length <= exibidas;
  mais.textContent = `Mostrar mais notícias (${filtradas.length - exibidas} restantes)`;

  const nota = document.getElementById("nota-lista");
  const ocultas = dados.fontes.filter((f) => ocultos.has(f)).length;
  nota.textContent = `${filtradas.length} notícias das últimas 48 horas` + (ocultas ? `, sem ${ocultas} veículo(s) desmarcado(s).` : ".");
}

function renderizar() {
  renderizarDestaques();
  renderizarLista();
}

function atualizarSubtitulo() {
  const falhas = dados.falhas.length ? ` · ${dados.falhas.length} feed(s) indisponível(is) agora` : "";
  document.getElementById("subtitulo").textContent =
    `${dados.noticias.length} notícias de ${dados.fontes.length} veículos · atualizado ${tempoRelativo(dados.atualizado)}${falhas}`;
}

async function carregar() {
  try {
    const resp = await fetch("/api/noticias", { cache: "no-cache" });
    if (!resp.ok) throw new Error(resp.status);
    dados = await resp.json();
  } catch (erro) {
    if (!dados) document.getElementById("subtitulo").textContent = "Não foi possível carregar as notícias. Tente recarregar a página.";
    return;
  }
  // Veículos que saíram da lista não ficam "presos" como ocultos
  ocultos = new Set([...ocultos].filter((f) => dados.fontes.includes(f)));
  montarFiltros();
  montarSeletorFontes();
  atualizarSubtitulo();
  renderizar();
}

document.getElementById("busca").addEventListener("input", (evento) => {
  busca = semAcento(evento.target.value.trim());
  exibidas = POR_PAGINA;
  if (dados) renderizar();
});

document.getElementById("mais").addEventListener("click", () => {
  exibidas += POR_PAGINA;
  renderizarLista();
});

montarAlternador();
carregar();
setInterval(carregar, RECARREGAR_MS);
// Mantém o "há X min" em dia entre uma recarga e outra
setInterval(() => dados && atualizarSubtitulo(), 60 * 1000);
