/* Consulta de produção: filtros, tabela ordenável, pesquisa, paginação e CSV. */
(function () {
  "use strict";

  const { escapar, obterJson, numero, SIMBOLOS } = window.LSPA;
  const opcoes = window.LSPA.lerOpcoes();

  const form = document.getElementById("form-producao");
  const selRegiao = document.getElementById("f-regiao");
  const selEstado = document.getElementById("f-estado");
  const selAno = document.getElementById("f-ano");
  const selMes = document.getElementById("f-mes");
  const campoBusca = document.getElementById("f-busca");
  const selPorPagina = document.getElementById("f-por-pagina");
  const tabela = document.getElementById("tabela-producao");
  const corpo = document.getElementById("tabela-corpo");

  const estado = { ordenar: "produto", direcao: "asc", pagina: 1 };
  let controlador = null;
  let temporizadorBusca = null;

  // ------------------------------------------------------------------ Filtros dependentes
  function preencherEstados() {
    const regiao = selRegiao.value;
    const selecionado = selEstado.value || selEstado.dataset.selecionado || "";
    const estados = (opcoes.estados || []).filter((uf) => !regiao || uf.regiao_codigo === regiao);
    selEstado.innerHTML = '<option value="">Todos os estados</option>' +
      estados.map((uf) => `<option value="${escapar(uf.codigo)}">${escapar(uf.nome)}</option>`).join("");
    if (estados.some((uf) => uf.codigo === selecionado)) selEstado.value = selecionado;
    selEstado.dataset.selecionado = "";
  }

  function preencherMeses() {
    window.LSPA.preencherMeses(selAno, selMes, opcoes.meses_por_ano || {}, true);
  }

  // ------------------------------------------------------------------ Parâmetros
  function parametros(extra = {}) {
    const p = new URLSearchParams();
    new FormData(form).forEach((valor, chave) => { if (valor) p.set(chave, valor); });
    if (campoBusca.value.trim()) p.set("busca", campoBusca.value.trim());
    p.set("ordenar", estado.ordenar);
    p.set("direcao", estado.direcao);
    p.set("pagina", estado.pagina);
    p.set("por_pagina", selPorPagina.value);
    Object.entries(extra).forEach(([k, v]) => p.set(k, v));
    return p;
  }

  function lerUrl() {
    const url = new URLSearchParams(location.search);
    if (url.get("ordenar")) estado.ordenar = url.get("ordenar");
    if (url.get("direcao")) estado.direcao = url.get("direcao");
    if (url.get("pagina")) estado.pagina = parseInt(url.get("pagina"), 10) || 1;
    if (url.get("por_pagina") && [...selPorPagina.options].some((o) => o.value === url.get("por_pagina"))) {
      selPorPagina.value = url.get("por_pagina");
    }
  }

  // ------------------------------------------------------------------ Renderização
  function renderizarLinhas(linhas) {
    if (!linhas.length) {
      corpo.innerHTML = '<tr><td colspan="7" class="text-center text-secondary py-5">Nenhum registro encontrado para os filtros informados.</td></tr>';
      return;
    }
    corpo.innerHTML = linhas.map((l) => {
      const semValor = l.valor === null;
      const valor = semValor
        ? `<span title="${escapar(SIMBOLOS[l.simbolo] || "Sem dado")}">${escapar(l.simbolo || "...")}</span>`
        : escapar(numero(l.valor));
      return `<tr>
        <td>${escapar(l.produto)}</td>
        <td>${escapar(l.localidade)}<span class="badge-nivel" title="Nível territorial">${l.nivel === "N1" ? "BR" : l.nivel === "N2" ? "Região" : "UF"}</span></td>
        <td>${escapar(l.indicador)}</td>
        <td class="valor ${semValor ? "simbolo" : ""}">${valor}</td>
        <td>${escapar(l.unidade)}</td>
        <td>${l.ano}</td>
        <td>${escapar(l.mes_nome)}</td>
      </tr>`;
    }).join("");
  }

  function itemPagina(rotulo, pagina, { ativo = false, desabilitado = false, aria = "" } = {}) {
    return `<li class="page-item ${ativo ? "active" : ""} ${desabilitado ? "disabled" : ""}">
      <button type="button" class="page-link" data-pagina="${pagina}" ${desabilitado ? "disabled" : ""}
              ${ativo ? 'aria-current="page"' : ""} ${aria ? `aria-label="${aria}"` : ""}>${rotulo}</button></li>`;
  }

  function renderizarPaginacao(r) {
    const nav = document.getElementById("paginacao");
    const inicio = r.total ? (r.pagina - 1) * r.por_pagina + 1 : 0;
    const fim = Math.min(r.pagina * r.por_pagina, r.total);
    document.getElementById("info-paginacao").textContent =
      `Mostrando ${numero(inicio)}–${numero(fim)} de ${numero(r.total)} registros`;

    if (r.total_paginas <= 1) { nav.innerHTML = ""; return; }
    const paginas = new Set([1, r.total_paginas]);
    for (let i = r.pagina - 2; i <= r.pagina + 2; i++) if (i >= 1 && i <= r.total_paginas) paginas.add(i);
    const ordenadas = [...paginas].sort((a, b) => a - b);

    let html = itemPagina('<i class="bi bi-chevron-left"></i>', r.pagina - 1, { desabilitado: r.pagina === 1, aria: "Página anterior" });
    ordenadas.forEach((p, i) => {
      if (i > 0 && p - ordenadas[i - 1] > 1) html += '<li class="page-item disabled"><span class="page-link">…</span></li>';
      html += itemPagina(p, p, { ativo: p === r.pagina });
    });
    html += itemPagina('<i class="bi bi-chevron-right"></i>', r.pagina + 1, { desabilitado: r.pagina === r.total_paginas, aria: "Próxima página" });
    nav.innerHTML = html;
  }

  function renderizarResumo(r) {
    const periodos = r.periodos.map((p) => p.nome);
    const textoPeriodo = periodos.length > 2 ? `${periodos[0]} a ${periodos[periodos.length - 1]}` : periodos.join(", ");
    document.getElementById("resumo-resultados").textContent =
      `${numero(r.total)} registros · estimativa de ${textoPeriodo}`;
  }

  function atualizarCabecalhos() {
    tabela.querySelectorAll(".ordenar").forEach((botao) => {
      const ativo = botao.dataset.coluna === estado.ordenar;
      botao.classList.toggle("asc", ativo && estado.direcao === "asc");
      botao.classList.toggle("desc", ativo && estado.direcao === "desc");
      botao.closest("th").setAttribute("aria-sort", ativo ? (estado.direcao === "asc" ? "ascending" : "descending") : "none");
    });
  }

  // ------------------------------------------------------------------ Carga
  async function carregar() {
    if (controlador) controlador.abort();
    controlador = new AbortController();
    const params = parametros();
    history.replaceState(null, "", `${location.pathname}?${params}`);
    tabela.classList.add("tabela-carregando");
    window.LSPA.limparAlertas();
    atualizarCabecalhos();
    try {
      const r = await obterJson(`/api/producao?${params}`, { signal: controlador.signal });
      estado.pagina = r.pagina;
      renderizarLinhas(r.linhas);
      renderizarPaginacao(r);
      renderizarResumo(r);
      window.LSPA.atualizarSeloFonte(r.meta);
      window.LSPA.notaFonte(r.meta);
    } catch (erro) {
      if (erro.name === "AbortError") return;
      window.LSPA.mostrarAlerta(erro.message, erro.status === 503 ? "warning" : "danger");
      corpo.innerHTML = '<tr><td colspan="7" class="text-center text-secondary py-5">Não foi possível carregar os dados.</td></tr>';
      document.getElementById("paginacao").innerHTML = "";
      document.getElementById("info-paginacao").textContent = "";
      document.getElementById("resumo-resultados").textContent = "—";
    } finally {
      tabela.classList.remove("tabela-carregando");
    }
  }

  async function exportarCsv() {
    const botao = document.getElementById("btn-csv");
    botao.disabled = true;
    try {
      const resposta = await fetch(`/api/producao?${parametros({ formato: "csv" })}`);
      if (!resposta.ok) {
        let mensagem = `Erro ${resposta.status} ao exportar.`;
        try { mensagem = (await resposta.json()).mensagem || mensagem; } catch (_) { /* sem JSON */ }
        throw new Error(mensagem);
      }
      const disposicao = resposta.headers.get("Content-Disposition") || "";
      const nome = (disposicao.match(/filename="([^"]+)"/) || [])[1] || "lspa_producao.csv";
      const url = URL.createObjectURL(await resposta.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = nome;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (erro) {
      window.LSPA.mostrarAlerta(erro.message);
    } finally {
      botao.disabled = false;
    }
  }

  // ------------------------------------------------------------------ Eventos
  selRegiao.addEventListener("change", preencherEstados);
  selAno.addEventListener("change", preencherMeses);
  form.addEventListener("submit", (e) => { e.preventDefault(); estado.pagina = 1; carregar(); });
  document.getElementById("btn-limpar").addEventListener("click", () => {
    form.reset();
    [...form.querySelectorAll("select")].forEach((s) => { s.value = ""; });
    campoBusca.value = "";
    preencherEstados();
    preencherMeses();
    estado.pagina = 1;
    carregar();
  });
  document.getElementById("btn-csv").addEventListener("click", exportarCsv);
  campoBusca.addEventListener("input", () => {
    clearTimeout(temporizadorBusca);
    temporizadorBusca = setTimeout(() => { estado.pagina = 1; carregar(); }, 400);
  });
  selPorPagina.addEventListener("change", () => { estado.pagina = 1; carregar(); });
  tabela.querySelector("thead").addEventListener("click", (e) => {
    const botao = e.target.closest(".ordenar");
    if (!botao) return;
    const coluna = botao.dataset.coluna;
    if (estado.ordenar === coluna) {
      estado.direcao = estado.direcao === "asc" ? "desc" : "asc";
    } else {
      estado.direcao = coluna === "valor" ? "desc" : "asc"; // valores: maiores primeiro
    }
    estado.ordenar = coluna;
    estado.pagina = 1;
    carregar();
  });
  document.getElementById("paginacao").addEventListener("click", (e) => {
    const botao = e.target.closest("[data-pagina]");
    if (!botao || botao.disabled) return;
    estado.pagina = parseInt(botao.dataset.pagina, 10);
    carregar();
    tabela.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  lerUrl();
  preencherEstados();
  preencherMeses();
  carregar();
})();
