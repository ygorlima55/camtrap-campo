/* Figura "pelagem" no estilo hairline: grade isométrica de placas finas em que as placas elevadas desenham
   rosetas de onça-pintada (contorno interrompido e pintas internas). Responde ao ponteiro.
   Implementação própria, sem dependências e sem internet, seguindo as regras da hairline:
   área de toque pela pose de repouso, atraso pela distância (40 ms), alcance limitado (1 → .31 → .09),
   um único destaque (ocre), repouso desenhado (as rosetas), plates opacos na cor do fundo,
   laço dorme fora da tela, mola k 100 / c 18 / m 1, sem texto dentro da figura.
   Decorativa: as alturas NÃO representam dados do acervo. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const N = 21, C = 12.8, CX = 200, CY = 150, COS = Math.SQRT1_2, ALCANCE = 5.4, ELEVA = 30, PASSO_MS = 28;
  const K = 100, AMORT = 18, M = 1, FATIAS = 2, R = 0.42, ESCALA = 1.6;
  const quietos = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // rosetas: centro, raio do anel, giro das falhas e deslocamento das pintas internas (assimétricas de propósito)
  const ROSETAS = [
    { x: -3.2, y: -2.6, r: 1.9, giro: 0.4, p: [[0.3, -0.2], [-0.4, 0.5]] },
    { x: 2.6, y: -3.4, r: 1.6, giro: 1.7, p: [[0.1, 0.2]] },
    { x: 0.1, y: 0.4, r: 2.1, giro: 2.6, p: [[0.4, 0.1], [-0.5, -0.4], [0, 0.6]] },
    { x: -2.8, y: 3.3, r: 1.7, giro: 4.1, p: [[-0.2, 0.2]] },
    { x: 3.6, y: 2.4, r: 1.8, giro: 5.2, p: [[0.3, -0.3], [-0.3, 0.4]] },
  ];
  function celula(x, y) {  // altura de repouso e a que roseta a célula pertence
    x /= ESCALA; y /= ESCALA;
    let h = 2 + 1.4 * Math.sin(x * 0.9 + y * 0.4) + Math.cos(y * 1.1 - x * 0.3), qual = -1, papel = "fundo";
    ROSETAS.forEach((ro, k) => {
      const dx = x - ro.x, dy = y - ro.y, d = Math.hypot(dx, dy), ang = Math.atan2(dy, dx);
      const falha = Math.sin(3 * ang + ro.giro) + 0.5 * Math.sin(5 * ang - ro.giro) > 0.85;  // contorno interrompido
      if (Math.abs(d - ro.r) < 0.62 && !falha) { h = 13 + 3 * Math.cos(2 * ang + ro.giro); qual = k; papel = "anel"; }
      for (const [px, py] of ro.p) if (Math.hypot(dx - px, dy - py) < 0.55) { h = 9; qual = k; papel = "pinta"; }
    });
    return { h, qual, papel };
  }
  function tela(gx, gy, h) {
    return [CX + (gx - gy) * C * COS, CY + (gx + gy) * C * COS * 0.5 - h];
  }
  function losango(gx, gy, h, r) {  // plate com cantos arredondados
    const pts = [[-r, 0], [0, -r], [r, 0], [0, r]].map(([dx, dy]) => tela(gx + dx, gy + dy, h));
    let d = "";
    for (let i = 0; i < 4; i++) {
      const a = pts[(i + 3) % 4], b = pts[i], c = pts[(i + 1) % 4], t = 0.24;
      const p1 = [b[0] + (a[0] - b[0]) * t, b[1] + (a[1] - b[1]) * t], p2 = [b[0] + (c[0] - b[0]) * t, b[1] + (c[1] - b[1]) * t];
      d += (i ? "L" : "M") + p1[0].toFixed(1) + " " + p1[1].toFixed(1) + "Q" + b[0].toFixed(1) + " " + b[1].toFixed(1) + " " + p2[0].toFixed(1) + " " + p2[1].toFixed(1);
    }
    return d + "Z";
  }
  function queda(d) {  // alcance limitado
    const r = d / ALCANCE;
    if (r <= 0.42) return 1 - (1 - 0.31) * (r / 0.42);
    if (r <= 1) return 0.31 - (0.31 - 0.09) * ((r - 0.42) / 0.58);
    return Math.max(0, 0.09 * (1 - (r - 1) / 0.5));
  }

  function montar(alvo) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 400 320");
    svg.setAttribute("class", "hl-svg");
    svg.setAttribute("aria-hidden", "true");
    alvo.appendChild(svg);
    const leitura = alvo.querySelector(".hl-leitura");
    const pecas = [];
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      const gx = i - (N - 1) / 2, gy = j - (N - 1) / 2, c = celula(gx, gy);
      pecas.push({ i, j, gx, gy, h0: c.h, h: c.h, v: 0, alvo: c.h, quando: 0, qual: c.qual, papel: c.papel });
    }
    pecas.sort((a, b) => (a.gx + a.gy) - (b.gx + b.gy) || (a.gx - b.gx));  // de trás para a frente
    // marca de repouso: a pinta da roseta central indica onde olhar
    const destaque = pecas.find((p) => p.qual === 2 && p.papel === "pinta") || pecas[0];
    for (const p of pecas) {
      p.fatias = Array.from({ length: FATIAS }, () => {
        const f = document.createElementNS(NS, "path"); f.setAttribute("class", "hl-plate hl-fatia"); return f;
      });
      p.topo = document.createElementNS(NS, "path");
      svg.append(...p.fatias, p.topo);
      p.cx = tela(p.gx, p.gy, p.h0);  // centro da pose de repouso: é contra ele que o ponteiro é testado
    }
    let ativa = null;

    function desenhar() {
      for (const p of pecas) {
        p.fatias.forEach((f, k) => f.setAttribute("d", losango(p.gx, p.gy, (p.h * k) / FATIAS, R)));
        p.topo.setAttribute("d", losango(p.gx, p.gy, p.h, R));
        const perto = ativa && ativa.qual >= 0 && p.qual === ativa.qual;
        const classe = p === (ativa || destaque) ? "hl-hi" : (perto || p.papel !== "fundo") ? "hl-edge" : "hl-mid";
        p.topo.setAttribute("class", "hl-plate " + classe + (p.papel === "fundo" ? " hl-fundo" : ""));
      }
    }
    function definirAlvos(agora) {
      for (const p of pecas) {
        const d = ativa ? Math.hypot(p.gx - ativa.gx, p.gy - ativa.gy) : 0;
        const bonus = ativa && ativa.qual >= 0 && p.qual === ativa.qual ? 10 : 0;  // a roseta tocada sobe inteira
        p.alvo = p.h0 + (ativa ? ELEVA * queda(d) + bonus : 0);
        p.quando = agora + (ativa ? d : Math.hypot(p.gx, p.gy)) * PASSO_MS;  // atraso pela distância
      }
    }

    let rodando = false, visivel = true, ultimo = 0;
    function passo(t) {
      const dt = Math.min(0.032, (t - ultimo) / 1000 || 0.016);
      ultimo = t;
      let parado = true;
      for (const p of pecas) {
        if (t < p.quando) { parado = false; continue; }
        p.v += ((-K * (p.h - p.alvo) - AMORT * p.v) / M) * dt;
        p.h += p.v * dt;
        if (Math.abs(p.v) > 0.02 || Math.abs(p.h - p.alvo) > 0.05) parado = false;
        else { p.h = p.alvo; p.v = 0; }
      }
      desenhar();
      if (!parado && visivel) requestAnimationFrame(passo);
      else rodando = false;
    }
    function acordar() {
      if (quietos) { for (const p of pecas) p.h = p.alvo; desenhar(); return; }
      if (!rodando && visivel) { rodando = true; ultimo = performance.now(); requestAnimationFrame(passo); }
    }

    function ponto(ev) {
      const m = svg.getScreenCTM();
      if (!m) return null;
      const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(m.inverse());
      let melhor = null, md = 1e9;
      for (const p of pecas) {
        const d = Math.hypot(pt.x - p.cx[0], pt.y - p.cx[1]);
        if (d < md) { md = d; melhor = p; }
      }
      return md < C * 1.1 ? melhor : null;
    }
    function ler(p) {
      if (!leitura) return;
      leitura.textContent = !p ? "pelagem · repouso" : p.qual >= 0 ? `roseta ${p.qual + 1} · ${p.papel}` : "pelagem";
    }
    alvo.addEventListener("pointermove", (ev) => {
      const p = ponto(ev);
      if (p === ativa) return;
      ativa = p;
      ler(p);
      definirAlvos(performance.now());
      acordar();
    });
    alvo.addEventListener("pointerleave", () => {
      ativa = null;
      ler(null);
      definirAlvos(performance.now());
      acordar();
    });
    new IntersectionObserver((es) => { visivel = es[0].isIntersecting; if (visivel) acordar(); }).observe(alvo);
    ler(null);
    desenhar();
  }

  document.querySelectorAll("[data-hairline]").forEach(montar);
})();
