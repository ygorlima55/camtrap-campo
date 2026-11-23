/* Menu com traço fino (inspirado em indicadores de aba desenhados a lápis):
   um trilho de 1 px ao lado dos itens, com um nó por item, e um marcador ocre que desliza até o item ativo
   ("trilho") ou faz o trilho se curvar em volta de um ponto ("entalhe"). Ao passar o mouse, o marcador
   antecipa o destino; ao sair, volta ao item ativo. Mesma mola da figura hairline (k 100, c 18, m 1). */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const menu = document.querySelector(".lateral-app .menu");
  if (!menu) return;
  const quietos = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const itens = [...menu.querySelectorAll("a.item")];
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", "traco-menu");
  svg.setAttribute("aria-hidden", "true");
  menu.prepend(svg);
  const trilho = document.createElementNS(NS, "path"); trilho.setAttribute("class", "traco-trilho");
  const marca = document.createElementNS(NS, "path"); marca.setAttribute("class", "traco-marca");
  const ponto = document.createElementNS(NS, "circle"); ponto.setAttribute("class", "traco-ponto"); ponto.setAttribute("r", "3");
  const nos = itens.map(() => { const c = document.createElementNS(NS, "circle"); c.setAttribute("class", "traco-no"); c.setAttribute("r", "1.6"); return c; });
  svg.append(trilho, ...nos, marca, ponto);

  const X = 9, BOJO = 9, MEIA = 15;
  let geo = [], topo = 0, fim = 0, y = 0, v = 0, alvo = 0, rodando = false, ultimo = 0;
  const ativo = itens.find((a) => a.classList.contains("ativo")) || itens[0];

  function medir() {
    const r = menu.getBoundingClientRect();
    svg.setAttribute("width", 24); svg.setAttribute("height", menu.scrollHeight);
    geo = itens.map((a) => { const b = a.getBoundingClientRect(); return b.top - r.top + menu.scrollTop + b.height / 2; });
    topo = geo[0] - 22; fim = geo[geo.length - 1] + 22;
    nos.forEach((c, i) => { c.setAttribute("cx", X); c.setAttribute("cy", geo[i]); });
  }
  function estilo() { return document.documentElement.dataset.menu || "trilho"; }
  function desenhar() {
    if (estilo() === "entalhe") {
      const a = y - MEIA, b = y + MEIA;
      trilho.setAttribute("d", `M${X} ${topo}V${a}C${X} ${y - 7} ${X + BOJO} ${y - 9} ${X + BOJO} ${y}C${X + BOJO} ${y + 9} ${X} ${y + 7} ${X} ${b}V${fim}`);
      marca.setAttribute("d", "");
      ponto.setAttribute("cx", X + BOJO - 6); ponto.setAttribute("cy", y); ponto.style.display = "";
      nos.forEach((c, i) => { c.style.opacity = Math.abs(geo[i] - y) < MEIA ? 0 : 1; });
    } else {
      trilho.setAttribute("d", `M${X} ${topo}V${fim}`);
      marca.setAttribute("d", `M${X} ${y - 11}V${y + 11}`);
      ponto.style.display = "none";
      nos.forEach((c, i) => { c.style.opacity = Math.abs(geo[i] - y) < 12 ? 0 : 1; });
    }
  }
  function passo(t) {
    const dt = Math.min(0.032, (t - ultimo) / 1000 || 0.016); ultimo = t;
    v += (-100 * (y - alvo) - 18 * v) * dt; y += v * dt;
    if (Math.abs(v) < 0.02 && Math.abs(y - alvo) < 0.05) { y = alvo; v = 0; rodando = false; }
    desenhar();
    if (rodando) requestAnimationFrame(passo);
  }
  function ir(destino) {
    alvo = destino;
    if (quietos) { y = alvo; desenhar(); return; }
    if (!rodando) { rodando = true; ultimo = performance.now(); requestAnimationFrame(passo); }
  }

  medir();
  const i0 = itens.indexOf(ativo);
  let anterior = null;
  try { anterior = sessionStorage.getItem("traco-menu-y"); } catch (e) { /* sem armazenamento: começa parado */ }
  y = anterior !== null ? Number(anterior) : geo[i0];
  desenhar();
  ir(geo[i0]);  // chega deslizando do item da página anterior

  itens.forEach((a, i) => {
    a.addEventListener("pointerenter", () => ir(geo[i]));
    a.addEventListener("focus", () => ir(geo[i]));
    a.addEventListener("click", () => { try { sessionStorage.setItem("traco-menu-y", String(y)); } catch (e) { /* ignora */ } });
  });
  menu.addEventListener("pointerleave", () => ir(geo[i0]));
  window.addEventListener("resize", () => { medir(); y = alvo = geo[i0]; desenhar(); });
  window.redesenharTracoMenu = () => { medir(); desenhar(); };
})();
