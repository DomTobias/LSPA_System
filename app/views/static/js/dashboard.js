/* Dashboard: indicadores (cards) e gráficos Chart.js alimentados por /api/dashboard. */
(function () {
  "use strict";

  const { numero, compacto, percentual, escapar, obterJson, SIMBOLOS } = window.LSPA;

  // Paleta validada (contraste e daltonismo): verde = período atual / série única,
  // azul = período de comparação.
  const COR = {
    atual: "#1f8a4c",
    comparacao: "#2a78d6",
    texto: "#556173",
    grade: "#edf0f4",
    superficie: "#ffffff",
  };

  const NOMES_INDICADOR = {
    producao: "Produção",
    area_plantada: "Área plantada",
    area_colhida: "Área colhida",
    rendimento_medio: "Rendimento médio",
  };

  const opcoes = window.LSPA.lerOpcoes();
  const form = document.getElementById("form-dashboard");
  const selAno = document.getElementById("f-ano");
  const selMes = document.getElementById("f-mes");
  const conteudo = document.getElementById("dashboard-conteudo");
  const graficos = {};
  let dados = null;
  let controlador = null;

  // ------------------------------------------------------------------ Chart.js
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = COR.texto;
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.animation.duration = 350;
  Chart.defaults.plugins.legend.labels.boxWidth = 10;
  Chart.defaults.plugins.legend.labels.boxHeight = 10;
  Chart.defaults.plugins.legend.labels.useBorderRadius = true;
  Chart.defaults.plugins.legend.labels.borderRadius = 2;
  Chart.defaults.plugins.tooltip.backgroundColor = "#1b2433";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
  Chart.defaults.plugins.tooltip.boxPadding = 4;

  function eixoValores(unidade, extra = {}) {
    return {
      beginAtZero: true,
      grid: { color: COR.grade, drawTicks: false },
      border: { display: false },
      ticks: { padding: 8, callback: (v) => compacto(v) },
      title: { display: Boolean(unidade), text: unidade, color: COR.texto, font: { size: 11 } },
      ...extra,
    };
  }

  const eixoCategorias = (extra = {}) => ({
    grid: { display: false },
    border: { color: "#cfd6e0" },
    ticks: { autoSkip: true, maxRotation: 0, ...extra.ticks },
    ...extra,
  });

  const rotuloTooltip = (unidade) => (ctx) => {
    const valor = ctx.parsed.y ?? ctx.parsed.x;
    const prefixo = ctx.dataset.label ? `${ctx.dataset.label}: ` : "";
    return valor === null || valor === undefined ? `${prefixo}sem dado` : `${prefixo}${numero(valor)} ${unidade}`;
  };

  function desenhar(id, configuracao) {
    if (graficos[id]) graficos[id].destroy();
    graficos[id] = new Chart(document.getElementById(id), configuracao);
  }

  function barras(cor) {
    return { backgroundColor: cor, hoverBackgroundColor: cor, borderRadius: 4, borderSkipped: "start", maxBarThickness: 36 };
  }

  // ------------------------------------------------------------------ Cards
  function variacaoHtml(valor, rotulo) {
    if (valor === null || valor === undefined) return "";
    const classe = valor > 0 ? "positiva" : valor < 0 ? "negativa" : "neutra";
    const icone = valor > 0 ? "bi-arrow-up-right" : valor < 0 ? "bi-arrow-down-right" : "bi-dash";
    return `<span><span class="variacao ${classe}"><i class="bi ${icone}" aria-hidden="true"></i> ${percentual(valor)}</span> ${escapar(rotulo)}</span>`;
  }

  function renderizarKpis() {
    const anoAnt = dados.periodo_ano_anterior ? `vs ${dados.periodo_ano_anterior.rotulo}` : "";
    const mesAnt = dados.periodo_mes_anterior ? `vs ${dados.periodo_mes_anterior.rotulo}` : "";
    dados.kpis.forEach((kpi) => {
      const card = document.getElementById(`kpi-${kpi.chave}`);
      if (!card) return;
      const valor = card.querySelector('[data-campo="valor"]');
      const unidade = card.querySelector('[data-campo="unidade"]');
      const variacoes = card.querySelector('[data-campo="variacoes"]');
      if (kpi.valor === null) {
        valor.classList.add("sem-valor");
        if (dados.produto.agregado && !kpi.somavel) {
          // Ex.: rendimento médio de "Cereais, leguminosas e oleaginosas" — o IBGE publica "-".
          valor.textContent = "Não publicado para grupos";
          unidade.textContent = `O IBGE não calcula ${kpi.nome.toLowerCase()} para agregados de produtos (símbolo “${kpi.simbolo || "-"}”).`;
        } else {
          valor.textContent = SIMBOLOS[kpi.simbolo] || "Sem dado";
          unidade.textContent = kpi.simbolo === ".." ? "O IBGE não publica este indicador para este produto." : kpi.unidade;
        }
        variacoes.innerHTML = "";
        return;
      }
      valor.classList.remove("sem-valor");
      valor.textContent = numero(kpi.valor);
      valor.title = `${numero(kpi.valor)} ${kpi.unidade}`;
      unidade.textContent = kpi.unidade;
      variacoes.innerHTML = variacaoHtml(kpi.variacao_anual, anoAnt) + variacaoHtml(kpi.variacao_mensal, mesAnt);
    });
  }

  // ------------------------------------------------------------------ Gráficos
  function renderizarEvolucao() {
    const modo = document.querySelector('input[name="evolucao-modo"]:checked').value;
    const indicador = document.getElementById("evolucao-indicador").value;
    const serie = dados.evolucao[modo];
    const kpi = dados.kpis.find((k) => k.chave === indicador) || {};
    const unidade = kpi.unidade || "";
    document.getElementById("evolucao-subtitulo").textContent =
      `${NOMES_INDICADOR[indicador]} · Brasil · ` +
      (modo === "anual" ? "última estimativa de cada ano (dezembro) e a estimativa selecionada"
                        : "estimativas mensais do LSPA");

    desenhar("grafico-evolucao", {
      type: "line",
      data: {
        labels: serie.rotulos,
        datasets: [{
          label: NOMES_INDICADOR[indicador],
          data: serie[indicador],
          borderColor: COR.atual,
          backgroundColor: COR.atual,
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          pointBorderColor: COR.superficie,
          pointBorderWidth: 2,
          tension: 0.25,
          spanGaps: true,
        }],
      },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (itens) => serie.descricoes[itens[0].dataIndex],
              label: rotuloTooltip(unidade),
            },
          },
        },
        scales: { x: eixoCategorias(), y: eixoValores(unidade, { beginAtZero: false }) },
      },
    });
  }

  function renderizarRegioes() {
    const r = dados.regioes;
    document.getElementById("regioes-subtitulo").textContent = r.rotulo_anterior
      ? `Produção por grande região · ${r.rotulo_anterior} vs ${r.rotulo_atual}`
      : `Produção por grande região · ${r.rotulo_atual}`;
    const datasets = [];
    if (r.rotulo_anterior) {
      datasets.push({ label: r.rotulo_anterior, data: r.itens.map((i) => i.anterior), ...barras(COR.comparacao) });
    }
    datasets.push({ label: r.rotulo_atual, data: r.itens.map((i) => i.atual), ...barras(COR.atual) });

    desenhar("grafico-regioes", {
      type: "bar",
      data: { labels: r.itens.map((i) => i.nome), datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        datasets: { bar: { categoryPercentage: 0.72, barPercentage: 0.92 } },
        plugins: {
          legend: { position: "top", align: "end" },
          tooltip: {
            callbacks: {
              label: rotuloTooltip(r.unidade),
              footer: (itens) => {
                const v = r.itens[itens[0].dataIndex].variacao_anual;
                return v === null ? "" : `Variação: ${percentual(v)}`;
              },
            },
          },
        },
        scales: { x: eixoCategorias({ ticks: { autoSkip: false } }), y: eixoValores(r.unidade) },
      },
    });
  }

  function renderizarEstados() {
    const e = dados.estados;
    document.getElementById("estados-subtitulo").textContent =
      `${dados.produto.nome} · ${dados.periodo.nome} · em ${e.unidade.toLowerCase()}`;
    desenhar("grafico-estados", {
      type: "bar",
      data: {
        labels: e.itens.map((i) => i.sigla),
        datasets: [{ label: "Produção", data: e.itens.map((i) => i.valor), ...barras(COR.atual), maxBarThickness: 28 }],
      },
      options: {
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (itens) => e.itens[itens[0].dataIndex].nome,
              label: rotuloTooltip(e.unidade),
            },
          },
        },
        scales: { x: eixoCategorias({ ticks: { autoSkip: false, font: { size: 11 } } }), y: eixoValores(e.unidade) },
      },
    });
  }

  function renderizarProdutos() {
    const p = dados.produtos;
    const anterior = dados.periodo_ano_anterior;
    document.getElementById("produtos-subtitulo").textContent =
      `${p.itens.length} maiores produções no Brasil, entre ${p.total_produtos} produtos · ` +
      (anterior ? `${anterior.rotulo} vs ${dados.periodo.rotulo}` : dados.periodo.rotulo);
    const datasets = [];
    if (anterior) datasets.push({ label: anterior.rotulo, data: p.itens.map((i) => i.anterior), ...barras(COR.comparacao) });
    datasets.push({ label: dados.periodo.rotulo, data: p.itens.map((i) => i.valor), ...barras(COR.atual) });

    desenhar("grafico-produtos", {
      type: "bar",
      data: { labels: p.itens.map((i) => i.nome), datasets },
      options: {
        indexAxis: "y",
        interaction: { mode: "index", intersect: false, axis: "y" },
        datasets: { bar: { categoryPercentage: 0.74, barPercentage: 0.9, maxBarThickness: 14 } },
        plugins: {
          legend: { position: "top", align: "end" },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${numero(ctx.parsed.x)} ${p.unidade}`,
              footer: (itens) => {
                const v = p.itens[itens[0].dataIndex].variacao_anual;
                return v === null ? "" : `Variação: ${percentual(v)}`;
              },
            },
          },
        },
        scales: {
          x: eixoValores(p.unidade, { grid: { color: COR.grade, drawTicks: false } }),
          y: { grid: { display: false }, border: { color: "#cfd6e0" }, ticks: { autoSkip: false } },
        },
      },
    });
  }

  function renderizarRanking() {
    const corpo = document.getElementById("ranking-corpo");
    if (!dados.ranking.length) {
      corpo.innerHTML = '<tr><td colspan="4" class="text-center text-secondary py-4">Sem produção estadual publicada para este período.</td></tr>';
      return;
    }
    corpo.innerHTML = dados.ranking.map((i) => {
      const largura = Math.max(0, Math.min(100, i.participacao || 0));
      const v = i.variacao_anual;
      const classe = v === null ? "neutra" : v > 0 ? "positiva" : v < 0 ? "negativa" : "neutra";
      return `<tr>
        <td class="posicao">${i.posicao}</td>
        <td><div class="ranking-nome">${escapar(i.nome)}</div>
            <div class="ranking-barra" aria-hidden="true"><span data-largura="${largura}"></span></div>
            <div class="ranking-participacao">${i.participacao === null ? "—" : percentual(i.participacao).replace("+", "")} do Brasil</div></td>
        <td class="text-end" title="${numero(i.valor)}">${compacto(i.valor)}</td>
        <td class="text-end"><span class="variacao ${classe}">${percentual(v)}</span></td>
      </tr>`;
    }).join("");
    // largura via CSSOM (compatível com a Content-Security-Policy, sem estilos inline)
    corpo.querySelectorAll("[data-largura]").forEach((el) => { el.style.width = `${el.dataset.largura}%`; });
  }

  function renderizar() {
    const p = dados.periodo;
    document.getElementById("contexto-periodo").innerHTML =
      `<strong>${escapar(dados.produto.nome)}</strong> · estimativa da safra ${p.ano} feita em ${escapar(p.mes_nome.toLowerCase())} de ${p.ano}` +
      (dados.periodo_ano_anterior ? ` · comparações com ${escapar(dados.periodo_ano_anterior.nome)}` : "");
    renderizarKpis();
    renderizarEvolucao();
    renderizarRegioes();
    renderizarEstados();
    renderizarProdutos();
    renderizarRanking();
    window.LSPA.atualizarSeloFonte(dados.meta);
    window.LSPA.notaFonte(dados.meta);
  }

  // ------------------------------------------------------------------ Carga
  function parametros() {
    const p = new URLSearchParams();
    new FormData(form).forEach((valor, chave) => { if (valor) p.set(chave, valor); });
    return p;
  }

  async function carregar() {
    if (controlador) controlador.abort();
    controlador = new AbortController();
    const params = parametros();
    history.replaceState(null, "", `${location.pathname}?${params}`);
    conteudo.classList.add("carregando");
    window.LSPA.limparAlertas();
    try {
      dados = await obterJson(`/api/dashboard?${params}`, { signal: controlador.signal });
      renderizar();
    } catch (erro) {
      if (erro.name === "AbortError") return;
      window.LSPA.mostrarAlerta(erro.message, erro.status === 503 ? "warning" : "danger");
      document.getElementById("contexto-periodo").textContent = "Não foi possível carregar os dados.";
    } finally {
      conteudo.classList.remove("carregando");
    }
  }

  window.LSPA.preencherMeses(selAno, selMes, opcoes.meses_por_ano || {});
  selAno.addEventListener("change", () => window.LSPA.preencherMeses(selAno, selMes, opcoes.meses_por_ano || {}));
  form.addEventListener("submit", (e) => { e.preventDefault(); carregar(); });
  document.getElementById("f-produto").addEventListener("change", carregar);
  document.querySelectorAll('input[name="evolucao-modo"]').forEach((el) => el.addEventListener("change", () => dados && renderizarEvolucao()));
  document.getElementById("evolucao-indicador").addEventListener("change", () => dados && renderizarEvolucao());

  carregar();
})();
