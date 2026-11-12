// --- Notícias ---

const CORES_FONTES = {
  "G1": "#e0352b",
  "Folha": "#2f6fdb",
  "Estadão": "#8b5cf6",
  "Agência Brasil": "#0c9fb5",
  "CNN Brasil": "#e2408f",
  "Poder360": "#64748b",
  "BBC Brasil": "#e38b00",
};

const CORES_SECOES = {
  politica: "#c9a227",
  economia: "#0f9d58",
  tecnologia: "#0fb5d4",
  mundo: "#e0352b",
  stf: "#c9a227",
  stj: "#0c9fb5",
  tjgo: "#0f9d58",
  mp: "#e2408f",
  mpgo: "#8b5cf6",
  csmp: "#d6336c",
  ceres: "#0f9d58",
  vale: "#c9a227",
};

const RECARREGAR_MS = 10 * 60 * 1000;

let noticias = null;

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

function etiquetaFonte(fonte) {
  const el = elemento("span", "fonte", fonte);
  el.style.setProperty("--cor", CORES_FONTES[fonte] || "#6b7280");
  return el;
}

function linhaMeta(noticia) {
  const meta = elemento("div", "meta");
  const hora = elemento("time", "", tempoRelativo(noticia.data));
  hora.dateTime = noticia.data;
  hora.title = new Date(noticia.data).toLocaleString("pt-BR", { dateStyle: "full", timeStyle: "short" });
  meta.append(etiquetaFonte(noticia.fonte), hora);
  if (noticia.veiculos > 1) {
    const selo = elemento("span", "selo", `em ${noticia.veiculos} veículos`);
    selo.title = `Assunto noticiado por ${noticia.veiculos} veículos diferentes`;
    meta.append(selo);
  }
  return meta;
}

function imagem(noticia) {
  const vazia = () => {
    const el = elemento("div", "imagem imagem-vazia", noticia.fonte);
    el.style.setProperty("--cor", CORES_FONTES[noticia.fonte] || "#6b7280");
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

function link(noticia, ...conteudo) {
  const a = elemento("a");
  a.href = noticia.link;
  a.target = "_blank";
  a.rel = "noopener";
  a.append(...conteudo);
  return a;
}

/** Primeira notícia da editoria: foto grande, resumo e links dos outros veículos. */
function noticiaLider(noticia, comImagens = true) {
  const lider = elemento("article", comImagens ? "lider" : "lider sem-imagem");
  const corpo = elemento("div", "corpo");
  const titulo = elemento("h3");
  titulo.append(link(noticia, noticia.titulo));
  corpo.append(linhaMeta(noticia), titulo);
  if (noticia.resumo) corpo.append(elemento("p", "resumo", noticia.resumo));

  if (noticia.relacionadas.length) {
    const tambem = elemento("ul", "tambem");
    for (const r of noticia.relacionadas) {
      const item = elemento("li");
      const a = link(r, r.titulo);
      a.title = r.titulo;
      item.append(etiquetaFonte(r.fonte), a);
      tambem.append(item);
    }
    corpo.append(tambem);
  }
  if (comImagens) lider.append(link(noticia, imagem(noticia)));
  lider.append(corpo);
  return lider;
}

function montarSecoes() {
  const container = document.getElementById("secoes");
  container.replaceChildren();
  for (const secao of noticias.secoes) {
    const painel = elemento("section", "painel secao");
    painel.style.setProperty("--cor", CORES_SECOES[secao.id] || "#6b7280");
    painel.append(elemento("h2", "", secao.nome));

    painel.append(...destaqueELista(secao.noticias, "Nenhuma notícia desta editoria agora."));
    container.append(painel);
  }
}

/**
 * A primeira notícia em destaque e as outras em lista (editorias e Ceres).
 * Sem imagens (Ceres: a busca não traz fotos), o quadro fica só com os textos.
 */
function destaqueELista(lista, textoVazio, comImagens = true) {
  const [primeira, ...demais] = lista;
  if (!primeira) return [elemento("p", "vazio", textoVazio)];
  const outras = elemento("ul", "outras");
  for (const n of demais) {
    const corpo = elemento("div", "corpo");
    corpo.append(linhaMeta(n), elemento("h3", "", n.titulo));
    const item = elemento("li");
    item.append(comImagens ? link(n, imagem(n), corpo) : link(n, corpo));
    outras.append(item);
  }
  return [noticiaLider(primeira, comImagens), outras];
}

function itemJuridico(n) {
  const item = elemento("li");
  const titulo = elemento("h3");
  // Quadro "Ministério Público Brasileiro": de qual MP (estado ou ramo federal) é a notícia
  if ("mp" in n) {
    const etiqueta = n.mp
      ? elemento("span", "etiqueta", n.mp.sigla === n.mp.nome ? n.mp.sigla : `${n.mp.sigla} · ${n.mp.nome}`)
      : elemento("span", "etiqueta indefinido", "MP não identificado");
    titulo.append(etiqueta, " ");
  }
  titulo.append(n.titulo);
  item.append(link(n, linhaMeta(n), titulo));
  return item;
}

/** Um painel por órgão (STF, STJ, TJGO, CSMP), com cinco notícias só em texto. */
const ORDEM_ENTRANCIAS = ["Procuradoria de Justiça", "Entrância final", "Entrância intermediária", "Entrância inicial"];

/** Editais de promoção e remoção com inscrições abertas (quadro MPGO), agrupados por entrância. */
function blocoEditais(dados) {
  const bloco = elemento("div", "editais");
  bloco.append(elemento("h3", "titulo-agenda", "Editais de promoção e remoção abertos"));
  if (!dados) {
    bloco.append(elemento("p", "vazio", "Não foi possível consultar os editais agora."));
    return bloco;
  }
  const { abertos } = dados;
  if (!abertos.length) {
    bloco.append(elemento("p", "vazio", "Nenhum edital com inscrições abertas no momento."));
  } else {
    const fins = [...new Set(abertos.map((e) => e.fim))].sort();
    const prazo = fins.length === 1
      ? `inscrições até ${dataCurta(fins[0])}`
      : `inscrições até ${dataCurta(fins[0])} a ${dataCurta(fins[fins.length - 1])}`;
    bloco.append(elemento("p", "editais-resumo", `${abertos.length} ${abertos.length === 1 ? "edital aberto" : "editais abertos"} · ${prazo}`));

    const lista = elemento("div", "editais-lista");
    for (const entrancia of ORDEM_ENTRANCIAS.concat(abertos.map((e) => e.entrancia))) {
      const doGrupo = abertos.filter((e) => e.entrancia === entrancia);
      if (!doGrupo.length || lista.querySelector(`[data-entrancia="${entrancia}"]`)) continue;
      const grupo = elemento("div", "editais-grupo");
      grupo.dataset.entrancia = entrancia;
      grupo.append(elemento("h4", "", `${entrancia || "Outros"} (${doGrupo.length})`));
      const ul = elemento("ul");
      for (const e of doGrupo) {
        const li = elemento("li");
        const vaga = linkExterno(e.link, e.vaga || `Edital ${e.numero}`);
        vaga.title = `Edital n. ${e.numero} · publicado em ${dataCurta(e.publicado)} · inscrições até ${dataCurta(e.fim)}`;
        const detalhe = elemento("span", "edital-criterio", e.criterio + (e.subsidiario ? ` (subsidiário: ${e.subsidiario.toLowerCase()})` : ""));
        li.append(vaga, detalhe);
        if (e.dificil_provimento) li.append(elemento("span", "etiqueta", "Difícil provimento"));
        if (fins.length > 1) li.append(elemento("span", "edital-criterio", `até ${dataCurta(e.fim)}`));
        ul.append(li);
      }
      grupo.append(ul);
      lista.append(grupo);
    }
    bloco.append(lista);
    bloco.append(elemento("p", "nota", "Prazo calculado pelo site (10 dias corridos a partir do 1º dia útil após a publicação); confira no edital."));
  }
  const todos = elemento("p", "editais-resumo");
  todos.append(linkExterno(dados.pagina, "Todos os editais do ano no portal do MPGO"));
  bloco.append(todos);
  return bloco;
}

// Links fixos no fim de alguns quadros jurídicos
const LINKS_JURIDICO = {
  mpgo: [
    ["Acessar todas as notícias do Portal do MPGO", "https://www.mpgo.mp.br/portal/noticias"],
    ["Acessar todas as notícias na Intranet do MPGO", "https://intranet.mpgo.mp.br/olimpo/news?category=ascom"],
  ],
};

function montarJuridico() {
  const container = document.getElementById("juridico");
  container.replaceChildren();
  for (const orgao of noticias.juridico || []) {
    const painel = elemento("section", "painel secao");
    painel.style.setProperty("--cor", CORES_SECOES[orgao.id] || "#6b7280");
    painel.append(elemento("h2", "", orgao.nome));

    if (!orgao.noticias.length) {
      painel.append(elemento("p", "vazio", "Nenhuma notícia recente."));
    } else {
      const lista = elemento("ul", "juridicas");
      orgao.noticias.forEach((n) => lista.append(itemJuridico(n)));
      painel.append(lista);
    }
    // STF e CSMP mostram, abaixo das notícias, o que está em julgamento
    if (orgao.id in MONTAR_AGENDA) {
      const agenda = elemento("div", "agenda-juridica");
      agenda.dataset.agenda = orgao.id;
      agenda.append(elemento("h3", "titulo-agenda", "Em julgamento"), elemento("div", "agenda-corpo"));
      painel.append(agenda);
    }
    if (orgao.id === "mpgo") painel.append(blocoEditais(noticias.editais));
    if (LINKS_JURIDICO[orgao.id]) {
      const links = elemento("div", "links-quadro");
      for (const [texto, href] of LINKS_JURIDICO[orgao.id]) links.append(linkExterno(href, texto));
      painel.append(links);
    }
    container.append(painel);
  }
  preencherAgendas();
}

const NOMES_MARCAS = {
  importante: "⭐ Julgado importante",
  repetitivo: "🏛️ Repetitivo / repercussão geral",
  mudanca: "🔄 Mudança de entendimento",
};

/** Link do julgado: o PDF completo já na página dele (ou o post, se não houver PDF). */
function linkJulgado(info, julgado, ...conteudo) {
  const href = info.pdf ? `${info.pdf}${julgado.pagina ? `#page=${julgado.pagina}` : ""}` : info.link;
  return link({ link: href }, ...conteudo);
}

/** Só a data: o horário que o feed traz é sempre 00:30, então não diz nada. */
function dataPublicacao(iso) {
  const dia = (d) => d.toLocaleDateString("pt-BR");
  const data = new Date(iso);
  const ontem = new Date(Date.now() - 86400000);
  if (dia(data) === dia(new Date())) return "hoje";
  if (dia(data) === dia(ontem)) return "ontem";
  return `em ${dia(data)}`;
}

function blocoInformativo(info) {
  const bloco = elemento("div", "informativo-bloco");
  const titulo = elemento("p", "informativo-titulo");
  if (info.novo) titulo.append(elemento("span", "etiqueta andamento", "Novo"));
  titulo.append(`Informativo ${info.numero} · publicado ${dataPublicacao(info.data)}`);
  const resumo = info.julgados_mp.length
    ? `${info.julgados_mp.length} de ${info.total} julgados de interesse do MP estadual`
    : `Nenhum dos ${info.total} julgados tem relação direta com a atuação do MP estadual`;
  const ler = elemento("p", "informativo-resumo", `${resumo} · `);
  ler.append(link(info, "Ler no Dizer o Direito"));
  if (info.pdf) ler.append(" · ", link({ link: info.pdf }, "PDF completo"));
  bloco.append(titulo, ler);

  if (info.julgados_mp.length) {
    const lista = elemento("ul", "julgados");
    for (const j of info.julgados_mp) {
      const item = elemento("li", j.marcas.includes("importante") ? "destacado" : "");
      const tese = linkJulgado(info, j, j.tese);
      tese.className = "julgado-tese";
      tese.title = j.pagina ? `Abrir o PDF completo na página ${j.pagina}` : "Abrir o PDF completo";
      item.append(elemento("p", "julgado-tema", [j.ramo, j.assunto].filter(Boolean).join(" · ")), tese);
      const etiquetas = elemento("div", "julgado-etiquetas");
      for (const motivo of j.interesse_mp) etiquetas.append(elemento("span", "etiqueta", motivo));
      for (const marca of j.marcas) etiquetas.append(elemento("span", "marca", NOMES_MARCAS[marca]));
      if (j.pagina) etiquetas.append(linkJulgado(info, j, `Ver no PDF (p. ${j.pagina})`));
      item.append(etiquetas);
      lista.append(item);
    }
    bloco.append(lista);
  }
  return bloco;
}

function montarInformativos() {
  const container = document.getElementById("informativos");
  container.replaceChildren();
  for (const [id, nome] of [["stf", "STF"], ["stj", "STJ"]]) {
    const lista = noticias.informativos?.[id];
    const painel = elemento("section", "painel secao informativo");
    painel.style.setProperty("--cor", CORES_SECOES[id]);
    painel.append(elemento("h2", "", `Informativos do ${nome}`));
    if (!lista?.length) {
      painel.append(elemento("p", "vazio", "Não foi possível consultar o Dizer o Direito agora."));
    } else {
      // Os três informativos rolam dentro do quadro, para a página não ficar comprida
      const corpo = elemento("div", "informativo-corpo");
      lista.forEach((info) => corpo.append(blocoInformativo(info)));
      painel.append(corpo);
    }
    container.append(painel);
  }
}

function montarRegional() {
  const container = document.getElementById("regional");
  container.replaceChildren();
  for (const quadro of noticias.regional || []) {
    const painel = elemento("section", "painel secao");
    painel.style.setProperty("--cor", CORES_SECOES[quadro.id] || "#6b7280");
    painel.append(elemento("h2", "", quadro.nome));
    // A busca não traz fotos: o quadro fica só com os textos
    painel.append(...destaqueELista(quadro.noticias, "Nenhuma notícia recente.", false));
    container.append(painel);
  }
}

function atualizarSubtitulo() {
  const falhas = noticias.falhas.length ? ` · ${noticias.falhas.length} feed(s) indisponível(is) agora` : "";
  document.getElementById("subtitulo").textContent =
    `As cinco principais de cada editoria, entre ${noticias.total} notícias de ${noticias.fontes.length} veículos · atualizado ${tempoRelativo(noticias.atualizado)}${falhas}`;
}

async function carregarNoticias() {
  try {
    const resp = await fetch("/api/noticias", { cache: "no-cache" });
    if (!resp.ok) throw new Error(resp.status);
    noticias = await resp.json();
  } catch {
    if (!noticias) document.getElementById("subtitulo").textContent = "Não foi possível carregar as notícias. Tente recarregar a página.";
    return;
  }
  montarSecoes();
  montarJuridico();
  montarRegional();
  montarInformativos();
  atualizarSubtitulo();
}

// --- Agendas (STF, CSMP, Presidente, Senado e Câmara) ---

function dataCurta(iso) {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

/** "Hoje, quarta-feira, 11/11", "Amanhã, ...", "Ontem, ..." ou só o dia da semana e a data. */
function descricaoDia(iso, hoje) {
  const [ano, mes, dia] = iso.split("-").map(Number);
  const semana = new Date(Date.UTC(ano, mes - 1, dia, 12)).toLocaleDateString("pt-BR", { weekday: "long", timeZone: "UTC" });
  const texto = `${semana}, ${dataCurta(iso)}`;
  const diferenca = Math.round((Date.parse(iso) - Date.parse(hoje)) / 86400000);
  const relativo = { 0: "Hoje", 1: "Amanhã", [-1]: "Ontem" }[diferenca];
  return relativo ? `${relativo}, ${texto}` : texto[0].toUpperCase() + texto.slice(1);
}

function periodo(inicio, fim) {
  return inicio === fim ? `Em ${dataCurta(inicio)}` : `De ${dataCurta(inicio)} a ${dataCurta(fim)}`;
}

function linkExterno(href, ...conteudo) {
  const a = elemento("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener";
  a.append(...conteudo);
  return a;
}

function bloco(titulo, ...conteudo) {
  const div = elemento("div", "agenda-bloco");
  if (titulo) div.append(elemento("h3", "", titulo));
  div.append(...conteudo);
  return div;
}

/** Item de agenda: horário à esquerda, título (com link) e detalhes embaixo. */
function compromisso({ hora = "", titulo, link: href, detalhes = [], etiqueta, cancelado = false, extra }) {
  const li = elemento("li", cancelado ? "cancelado" : "");
  const corpo = elemento("div");
  const tituloEl = href ? linkExterno(href, titulo) : elemento("span", "", titulo);
  tituloEl.classList.add("titulo");
  const linhaTitulo = elemento("p", "titulo");
  if (etiqueta) linhaTitulo.append(elemento("span", "etiqueta", etiqueta));
  linhaTitulo.append(tituloEl);
  corpo.append(linhaTitulo);
  for (const d of detalhes.filter(Boolean)) corpo.append(elemento("p", "detalhe", d));
  if (extra) corpo.append(extra);
  li.append(elemento("span", "hora", hora), corpo);
  return li;
}

function listaCompromissos(itens) {
  const ul = elemento("ul", "compromissos");
  itens.forEach((item) => ul.append(compromisso(item)));
  return ul;
}

function rodapeLink(href, texto) {
  const p = elemento("p", "agenda-data");
  p.append(linkExterno(href, texto));
  return p;
}

function agendaStf(stf, hoje) {
  const partes = [];
  // As sessões virtuais em andamento vêm primeiro: são o que está sendo julgado agora
  if (stf.virtuais.length) {
    const sessoes = stf.virtuais.map((v) => {
      const div = elemento("div", "sessao");
      const contagens = elemento("div", "contagens");
      for (const [rotulo, total] of [["Plenário", v.plenario], ["1ª Turma", v.primeira_turma], ["2ª Turma", v.segunda_turma]]) {
        const span = elemento("span", "", `${rotulo}: `);
        span.append(elemento("strong", "", total));
        contagens.append(span);
      }
      div.append(elemento("h4", "", `${periodo(v.inicio, v.fim)} · ${v.plenario + v.primeira_turma + v.segunda_turma} processos`), contagens);
      const p = elemento("p");
      p.append(linkExterno(v.link, "Ver os processos no portal do STF"));
      div.append(p);
      return div;
    });
    partes.push(bloco("Sessões virtuais em andamento", ...sessoes));
  }
  if (stf.presencial) {
    const { data, sessoes } = stf.presencial;
    for (const sessao of sessoes) {
      const hora = sessao.inicio.split(" ")[1]?.replace(":", "h") || "";
      partes.push(bloco(
        `${sessao.colegiado} · ${sessao.descricao} · ${descricaoDia(data, hoje)}${hora ? `, ${hora}` : ""}`,
        listaCompromissos(sessao.processos.map((p, i) => ({
          hora: `${i + 1}.`,
          titulo: p.processo,
          link: p.link,
          detalhes: [p.relator && `Relator: ${p.relator}`, p.tema],
        }))),
      ));
    }
    if (!sessoes.length) partes.push(bloco("Sessão presencial", elemento("p", "vazio", `Sem processos na pauta de ${dataCurta(data)}.`)));
  }

  if (!partes.length) partes.push(elemento("p", "vazio", "Nenhuma sessão de julgamento marcada."));
  partes.push(rodapeLink(stf.presencial?.link || "https://portal.stf.jus.br/pauta/pesquisarCalendario.asp", "Calendário completo de julgamentos do STF"));
  return partes;
}

const SITUACOES_CSMP = { andamento: "Em andamento", proxima: "Próxima", realizada: "Realizada" };

function agendaCsmp(pautas) {
  if (!pautas.length) return [elemento("p", "vazio", "Nenhuma pauta publicada.")];
  return pautas.map((pauta) => {
    const div = elemento("div", "sessao");
    const titulo = elemento("h4");
    titulo.append(
      elemento("span", `etiqueta ${pauta.situacao === "andamento" ? "andamento" : ""}`, SITUACOES_CSMP[pauta.situacao]),
      pauta.titulo,
    );
    div.append(titulo, elemento("p", "", periodo(pauta.inicio, pauta.fim)));
    if (pauta.processos) {
      const contagens = elemento("div", "contagens");
      const span = elemento("span");
      span.append(elemento("strong", "", pauta.processos), pauta.processos === 1 ? " processo na pauta" : " processos na pauta");
      contagens.append(span);
      div.append(contagens);
    }
    if (pauta.itens?.length) {
      const ol = elemento("ol");
      pauta.itens.forEach((item) => ol.append(elemento("li", "", item)));
      div.append(ol);
    }
    if (pauta.relatores?.length) div.append(elemento("p", "", `Relatores: ${pauta.relatores.join(", ")}`));
    const links = elemento("p");
    if (pauta.pdf) links.append(linkExterno(pauta.pdf, "Ver a pauta completa (PDF)"), " · ");
    links.append(linkExterno(pauta.link, "Publicação no portal do MPGO"));
    div.append(links);
    return div;
  });
}

function agendaPresidente(agenda, hoje) {
  if (!agenda.data) return [elemento("p", "vazio", "Nenhuma agenda publicada nos últimos dias."), rodapeLink(agenda.link, "Agenda no site do Planalto")];
  let texto = descricaoDia(agenda.data, hoje);
  if (agenda.data !== hoje) texto += " · a agenda de hoje ainda não foi publicada";
  const partes = [elemento("p", "agenda-data", texto)];
  if (agenda.aviso) partes.push(elemento("p", "agenda-data", agenda.aviso));
  partes.push(agenda.compromissos.length
    ? listaCompromissos(agenda.compromissos.map((c) => ({ hora: c.hora, titulo: c.titulo, detalhes: [c.local] })))
    : elemento("p", "vazio", "Sem compromissos na agenda."));
  partes.push(rodapeLink(agenda.link, "Agenda no site do Planalto"));
  return partes;
}

function agendaSenado(agenda, hoje) {
  if (!agenda.data) return [elemento("p", "vazio", "Nenhuma sessão ou reunião nos próximos dias."), rodapeLink(agenda.link, "Agenda no site do Senado")];
  const partes = [elemento("p", "agenda-data", descricaoDia(agenda.data, hoje))];
  if (agenda.plenario.length) {
    partes.push(bloco("Plenário", listaCompromissos(agenda.plenario.map((s) => {
      let extra;
      if (s.materias.length) {
        extra = elemento("ul", "materias");
        for (const m of s.materias) {
          const li = elemento("li");
          li.append(linkExterno(m.link, m.identificacao), ` – ${m.ementa}`);
          extra.append(li);
        }
        if (s.total_materias > s.materias.length) extra.append(elemento("li", "", `e mais ${s.total_materias - s.materias.length} matérias`));
      }
      return {
        hora: s.hora,
        titulo: s.tipo,
        etiqueta: s.casa === "Congresso Nacional" ? "Congresso" : undefined,
        detalhes: [s.situacao !== "Agendada" && s.situacao, s.descricao],
        cancelado: /cancel/i.test(s.situacao),
        extra,
      };
    }))));
  }
  if (agenda.comissoes.length) {
    partes.push(bloco("Comissões", listaCompromissos(agenda.comissoes.map((r) => ({
      hora: r.hora,
      titulo: `${r.sigla} · ${r.titulo}`,
      link: r.link,
      detalhes: [r.nome, r.situacao !== "Agendada" && r.situacao],
      cancelado: /cancel/i.test(r.situacao),
    })))));
  }
  partes.push(rodapeLink(agenda.link, "Agenda completa no site do Senado"));
  return partes;
}

function agendaCamara(agenda, hoje) {
  if (!agenda.data) return [elemento("p", "vazio", "Nenhum evento nos próximos dias."), rodapeLink(agenda.link, "Agenda no site da Câmara")];
  return [
    elemento("p", "agenda-data", `${descricaoDia(agenda.data, hoje)} · ${agenda.eventos.length} eventos`),
    listaCompromissos(agenda.eventos.map((e) => ({
      hora: e.hora,
      titulo: e.titulo || e.tipo,
      link: e.link,
      etiqueta: e.orgao === "PLEN" ? "Plenário" : e.orgao,
      detalhes: [`${e.tipo}${e.orgao !== "PLEN" && e.nome_orgao ? ` · ${e.nome_orgao}` : ""}`, /cancel/i.test(e.situacao) && e.situacao],
      cancelado: /cancel/i.test(e.situacao),
    }))),
    rodapeLink(agenda.link, "Agenda completa no site da Câmara"),
  ];
}

const MONTAR_AGENDA = {
  stf: agendaStf,
  csmp: agendaCsmp,
  presidente: agendaPresidente,
  senado: agendaSenado,
  camara: agendaCamara,
};

// Guardadas para redesenhar o STF e o CSMP quando os painéis jurídicos são recriados
let agendas = null;

/** Preenche cada elemento com data-agenda (os do bloco Agendas e os do STF e CSMP). */
function preencherAgendas() {
  if (!agendas) return;
  for (const painel of document.querySelectorAll("[data-agenda]")) {
    const nome = painel.dataset.agenda;
    const corpo = painel.querySelector(".agenda-corpo");
    corpo.replaceChildren();
    if (agendas[nome] == null) {
      corpo.append(elemento("p", "vazio", "Não foi possível carregar esta agenda agora."));
      continue;
    }
    corpo.append(...MONTAR_AGENDA[nome](agendas[nome], agendas.hoje));
  }
}

async function carregarAgendas() {
  const nota = document.getElementById("nota-agendas");
  try {
    const resp = await fetch("/api/agendas", { cache: "no-cache" });
    if (!resp.ok) throw new Error(resp.status);
    agendas = await resp.json();
  } catch {
    if (!agendas) nota.textContent = "Não foi possível carregar as agendas. Tente recarregar a página.";
    return;
  }
  preencherAgendas();
  nota.textContent = `Compromissos do dia, direto das fontes oficiais · atualizado ${tempoRelativo(agendas.atualizado)}`;
}

// --- Cotações (mesmos gráficos do Projeto Site Cotações) ---

const CORES = {
  USD: "#2a7de1",
  EUR: "#7b5cd6",
  BTC: "#f2a900",
  ETH: "#627eea",
  TRX: "#e5342f",
  USDT: "#26a17b",
};

const MOEDAS = ["USD", "EUR"];
const CRIPTOS = ["BTC", "ETH", "TRX", "USDT"];

const PERIODOS = {
  anos5: { rotulo: "em 5 anos", recuar: (d) => d.setUTCFullYear(d.getUTCFullYear() - 5) },
  ano: { rotulo: "em 1 ano", recuar: (d) => d.setUTCFullYear(d.getUTCFullYear() - 1) },
  mes: { rotulo: "em 1 mês", recuar: (d) => d.setUTCMonth(d.getUTCMonth() - 1) },
  semana: { rotulo: "em 1 semana", recuar: (d) => d.setUTCDate(d.getUTCDate() - 7) },
  dia: { rotulo: "nas últimas 24h", recuar: (d) => d.setUTCDate(d.getUTCDate() - 1) },
};

const escuro = window.matchMedia("(prefers-color-scheme: dark)").matches;
const corTexto = escuro ? "#e8eaf0" : "#1d2230";
const corGrade = escuro ? "#1a2230" : "#e3e6eb";
const corSuave = escuro ? "#9aa2b1" : "#4b5563";

let cotacoes = null;
let periodoAtual = "anos5";

const NOTA_COTACOES = "Histórico diário dos últimos 5 anos, atualizado automaticamente.";

// Cotações de hora em hora (filtro "1 dia"), recarregadas a cada 5 minutos
const VALIDADE_INTRADIA_MS = 5 * 60 * 1000;
let intradia = null;
let momentoIntradia = 0;

/** Série a exibir: de hora em hora no filtro "1 dia" (se disponível), senão diária. */
function serie(ativo) {
  if (periodoAtual === "dia" && intradia && intradia[ativo]?.valores.length) {
    return intradia[ativo];
  }
  return recortar(cotacoes[ativo], periodoAtual);
}

async function carregarIntradia() {
  if (intradia && Date.now() - momentoIntradia < VALIDADE_INTRADIA_MS) return;
  const resposta = await fetch("/api/intradia");
  if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
  intradia = await resposta.json();
  momentoIntradia = Date.now();
}

/**
 * Recorta a série para o período escolhido, contado a partir da última cotação.
 * Inclui a última cotação anterior ao corte como ponto de partida, para que o
 * gráfico faça sentido mesmo em fins de semana (dólar e euro).
 */
function recortar(info, periodo) {
  const { datas, valores } = info;
  const recuar = PERIODOS[periodo].recuar;
  if (!recuar || !datas.length) return { datas, valores };

  const corte = new Date(datas[datas.length - 1] + "T00:00:00Z");
  recuar(corte);
  const corteIso = corte.toISOString().slice(0, 10);

  let inicio = datas.findIndex((d) => d >= corteIso);
  if (inicio === -1) inicio = datas.length - 1;
  if (datas[inicio] > corteIso && inicio > 0) inicio -= 1;
  return { datas: datas.slice(inicio), valores: valores.slice(inicio) };
}

function eixoX(serieCurta) {
  const eixo = { gridcolor: corGrade, tickformat: "%d/%m/%y", hoverformat: "%d/%m/%Y" };
  if (periodoAtual === "dia" && intradia) {
    eixo.tickformat = "%H:%M";
    eixo.hoverformat = "%d/%m %H:%M";
  } else if (serieCurta) {
    eixo.tickformat = "%d/%m";
    eixo.dtick = 24 * 60 * 60 * 1000; // um rótulo por dia
  }
  return eixo;
}

function layoutBase(extra = {}) {
  return {
    margin: { l: 70, r: 16, t: 36, b: 40 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: corTexto, family: "system-ui, sans-serif" },
    separators: ",.",
    hovermode: "x unified",
    // Fundo sólido na janela do mouse (o fundo do gráfico é transparente)
    hoverlabel: {
      bgcolor: escuro ? "#0a0e15" : "#ffffff",
      bordercolor: escuro ? "#3a4252" : "#c9ced6",
      font: { color: corTexto, size: 13, family: "system-ui, sans-serif" },
    },
    ...extra,
  };
}

const configPlotly = { responsive: true, displaylogo: false };

function formatarReal(valor) {
  // Ativos baratos (ex.: Tron) precisam de mais casas decimais
  const casas = valor < 10 ? 4 : 2;
  return valor.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
}

function formatarData(texto) {
  // Aceita "2026-09-29" ou "2026-09-29 14:00"
  const [dia, hora] = texto.split(" ");
  const [a, m, d] = dia.split("-");
  return hora ? `${d}/${m}/${a} ${hora}` : `${d}/${m}/${a}`;
}

const VARIACOES = [["anos5", "5 anos"], ["ano", "1 ano"], ["mes", "1 mês"], ["semana", "1 semana"], ["dia", "1 dia"]];

/**
 * Variação nos últimos 5 anos, ano, mês, semana e dia, qualquer que seja o filtro escolhido.
 * O "1 dia" usa as cotações de hora em hora quando já carregadas; senão, as diárias.
 */
function preencherVariacoes(ativo) {
  const caixa = document.getElementById(`variacoes-${ativo}`);
  if (!caixa) return;
  caixa.replaceChildren();
  for (const [periodo, rotulo] of VARIACOES) {
    const horaria = periodo === "dia" && intradia?.[ativo]?.valores.length >= 2;
    const { datas, valores } = horaria ? intradia[ativo] : recortar(cotacoes[ativo], periodo);
    const item = elemento("div");
    const valor = elemento("span", "valor", "–");
    if (valores.length >= 2) {
      const variacao = (valores[valores.length - 1] / valores[0] - 1) * 100;
      valor.textContent = `${variacao >= 0 ? "+" : ""}${variacao.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
      valor.classList.add(variacao >= 0 ? "alta" : "baixa");
      item.title = `De ${formatarReal(valores[0])} (${formatarData(datas[0])}) ` +
        `para ${formatarReal(valores[valores.length - 1])} (${formatarData(datas[datas.length - 1])})`;
    }
    item.append(elemento("span", "rotulo", rotulo), valor);
    caixa.append(item);
  }
}

function montarGraficosIndividuais(idContainer, ativos) {
  const container = document.getElementById(idContainer);
  for (const ativo of ativos) {
    const info = cotacoes[ativo];
    if (!info || !info.valores.length) continue;

    let grafico = document.getElementById(`grafico-${ativo}`);
    if (!grafico) {
      const painel = document.createElement("div");
      painel.className = "painel";
      grafico = document.createElement("div");
      grafico.id = `grafico-${ativo}`;
      grafico.className = "grafico";
      const variacoes = document.createElement("div");
      variacoes.id = `variacoes-${ativo}`;
      variacoes.className = "variacoes";
      variacoes.setAttribute("aria-label", `Variação do ${info.nome}`);
      painel.append(grafico, variacoes);
      container.appendChild(painel);
    }
    preencherVariacoes(ativo);

    const { datas, valores } = serie(ativo);
    const casas = valores[valores.length - 1] < 10 ? 4 : 2;
    Plotly.react(grafico, [{
      x: datas,
      y: valores,
      type: "scatter",
      mode: datas.length > 40 ? "lines" : "lines+markers",
      line: { color: CORES[ativo], width: 2 },
      hovertemplate: `R$ %{y:,.${casas}f}<extra></extra>`,
    }], layoutBase({
      // Nome em destaque, com uma bolinha na cor do ativo
      title: {
        text: `<span style="color:${CORES[ativo]}">●</span> <b>${info.nome}</b> <span style="color:${corSuave}">(${ativo})</span>`,
        font: { size: 20 },
        x: 0.02,
        y: 0.96,
      },
      // Valores na casa das centenas de milhares (bitcoin) precisam de mais espaço no eixo
      margin: { l: Math.max(...valores) >= 100000 ? 96 : 76, r: 16, t: 48, b: 40 },
      xaxis: eixoX(datas.length <= 10),
      yaxis: { gridcolor: corGrade, tickprefix: "R$ ", tickformat: `,.${casas}f` },
    }), configPlotly);
  }
}

function montarGraficos() {
  montarGraficosIndividuais("graficos-moedas", MOEDAS);
  montarGraficosIndividuais("graficos-cripto", CRIPTOS);
}

document.getElementById("filtros").addEventListener("click", async (evento) => {
  const botao = evento.target.closest("button[data-periodo]");
  if (!botao || !cotacoes) return;
  periodoAtual = botao.dataset.periodo;
  document.querySelectorAll("#filtros button").forEach((b) => b.classList.toggle("ativo", b === botao));

  const nota = document.getElementById("nota-cotacoes");
  if (periodoAtual === "dia") {
    nota.textContent = "Carregando cotações de hora em hora…";
    try {
      await carregarIntradia();
      nota.textContent = "Últimas 24 horas, de hora em hora.";
    } catch (erro) {
      nota.textContent = `Não foi possível carregar as cotações de hora em hora (${erro.message}). Mostrando dados diários.`;
    }
    if (periodoAtual !== "dia") return; // o usuário trocou de filtro enquanto carregava
  } else {
    nota.textContent = NOTA_COTACOES;
  }
  montarGraficos();
});

async function carregarCotacoes() {
  const nota = document.getElementById("nota-cotacoes");
  try {
    const resposta = await fetch("/api/cotacoes");
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    cotacoes = await resposta.json();
    montarGraficos();
    nota.textContent = NOTA_COTACOES;
  } catch (erro) {
    nota.textContent = `Não foi possível carregar as cotações (${erro.message}).`;
    return;
  }
  // As cotações de hora em hora deixam a variação de "1 dia" mais precisa
  try {
    await carregarIntradia();
    [...MOEDAS, ...CRIPTOS].forEach(preencherVariacoes);
  } catch { /* fica com a variação diária */ }
}

carregarNoticias();
carregarAgendas();
carregarCotacoes();
setInterval(carregarNoticias, RECARREGAR_MS);
setInterval(carregarAgendas, RECARREGAR_MS);
// Mantém o "há X min" em dia entre uma recarga e outra
setInterval(() => noticias && atualizarSubtitulo(), 60 * 1000);
