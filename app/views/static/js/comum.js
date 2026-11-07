/* Utilitários compartilhados pelas páginas (formatação, requisições, alertas). */
(function (global) {
  "use strict";

  const fmtInteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
  const fmtDecimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const fmtData = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

  const SIMBOLOS = {
    "-": "Zero absoluto",
    "..": "Não se aplica",
    "...": "Não disponível",
    "X": "Valor inibido (sigilo)",
  };

  function numero(valor) {
    return valor === null || valor === undefined ? "—" : fmtInteiro.format(valor);
  }

  /** Número compacto para eixos e cards: 354,5 mi, 12,3 mil… */
  function compacto(valor) {
    if (valor === null || valor === undefined) return "—";
    const abs = Math.abs(valor);
    if (abs >= 1e9) return fmtDecimal.format(valor / 1e9) + " bi";
    if (abs >= 1e6) return fmtDecimal.format(valor / 1e6) + " mi";
    if (abs >= 1e4) return fmtDecimal.format(valor / 1e3) + " mil";
    return fmtInteiro.format(valor);
  }

  function percentual(valor) {
    if (valor === null || valor === undefined) return "—";
    const sinal = valor > 0 ? "+" : "";
    return sinal + fmtDecimal.format(valor) + "%";
  }

  function dataHora(iso) {
    if (!iso) return "—";
    const data = new Date(iso);
    return isNaN(data) ? iso : fmtData.format(data);
  }

  function escapar(texto) {
    return String(texto ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[c]);
  }

  /** GET JSON com tratamento das respostas de erro da API interna. */
  async function obterJson(url, opcoes = {}) {
    let resposta;
    try {
      resposta = await fetch(url, { headers: { Accept: "application/json" }, ...opcoes });
    } catch (erro) {
      if (erro.name === "AbortError") throw erro;
      throw new Error("Não foi possível conectar ao servidor da aplicação.");
    }
    let corpo = null;
    try { corpo = await resposta.json(); } catch (_) { /* resposta sem JSON */ }
    if (!resposta.ok) {
      const erro = new Error((corpo && corpo.mensagem) || `Erro ${resposta.status} ao carregar os dados.`);
      erro.status = resposta.status;
      throw erro;
    }
    return corpo;
  }

  function mostrarAlerta(mensagem, tipo = "danger") {
    const area = document.getElementById("area-alertas");
    if (!area) return;
    const icone = tipo === "warning" ? "bi-exclamation-triangle" : tipo === "info" ? "bi-info-circle" : "bi-x-octagon";
    area.innerHTML =
      `<div class="alert alert-${tipo} alert-dismissible d-flex gap-2" role="alert">` +
      `<i class="bi ${icone}" aria-hidden="true"></i><div>${escapar(mensagem)}</div>` +
      `<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Fechar"></button></div>`;
  }

  function limparAlertas() {
    const area = document.getElementById("area-alertas");
    if (area) area.innerHTML = "";
  }

  /** Atualiza o selo do cabeçalho com a origem e data dos dados. */
  function atualizarSeloFonte(meta) {
    const selo = document.getElementById("selo-fonte");
    const texto = document.getElementById("selo-fonte-texto");
    if (!selo || !texto || !meta) return;
    const origens = { api: "IBGE (atualizado agora)", cache: "Cache local", cache_expirado: "Cache local (IBGE indisponível)" };
    texto.textContent = `${origens[meta.origem] || "IBGE"} · ${dataHora(meta.atualizado_em)}`;
    selo.classList.toggle("alerta", meta.origem === "cache_expirado");
    selo.hidden = false;
    (meta.avisos || []).forEach((aviso) => mostrarAlerta(aviso, "warning"));
  }

  function notaFonte(meta) {
    const nota = document.getElementById("nota-fonte");
    if (!nota || !meta) return;
    nota.innerHTML =
      `Fonte: ${escapar(meta.fonte)} — <a href="${escapar(meta.url_fonte)}" target="_blank" rel="noopener noreferrer">tabela ${escapar(meta.tabela)}</a>. ` +
      `Dados obtidos em ${escapar(dataHora(meta.atualizado_em))}.`;
  }

  function lerOpcoes() {
    const elemento = document.getElementById("dados-opcoes");
    return elemento ? JSON.parse(elemento.textContent) : {};
  }

  /** Preenche o select de meses conforme o ano escolhido. */
  function preencherMeses(selectAno, selectMes, mesesPorAno, incluirTodos = false) {
    const selecionado = selectMes.value || selectMes.dataset.selecionado || "";
    const ano = selectAno.value;
    let html = '<option value="">Mais recente</option>';
    if (ano && mesesPorAno[ano]) {
      if (incluirTodos) html += '<option value="todos">Todos os meses</option>';
      mesesPorAno[ano].forEach((m) => { html += `<option value="${m.mes}">${escapar(m.nome)}</option>`; });
    }
    selectMes.innerHTML = html;
    if ([...selectMes.options].some((o) => o.value === selecionado)) selectMes.value = selecionado;
    selectMes.dataset.selecionado = "";
    selectMes.disabled = !ano;
  }

  global.LSPA = {
    SIMBOLOS, numero, compacto, percentual, dataHora, escapar, obterJson,
    mostrarAlerta, limparAlertas, atualizarSeloFonte, notaFonte, lerOpcoes, preencherMeses,
  };
})(window);
