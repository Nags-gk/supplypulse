/* SupplyPulse dashboard: renders JSON exported by the pipeline. All text comes from data files. */
(() => {
  "use strict";
  const REPO = "https://github.com/Nags-gk/supplypulse";
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---------------------------------------------------------------- formatting
  const nf = new Intl.NumberFormat("en-US");
  const int = (n) => nf.format(Math.round(n));
  const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
  const usd = (x) => "$" + nf.format(Math.round(x));
  const num = (x, d = 2) => Number(x).toFixed(d);
  const parseDay = (s) => new Date(s.slice(0, 10) + "T00:00:00Z");
  const fmtDate = d3.utcFormat("%b %-d, %Y");
  const fmtMonth = d3.utcFormat("%b %Y");
  const compact = (v) => (Math.abs(v) >= 1000 ? d3.format(".2~s")(v).replace("G", "B") : String(v));

  const h = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const setParas = (host, paras) => host.replaceChildren(...paras.map((t) => h("p", "", t)));

  // ---------------------------------------------------------------- tooltip
  const tip = $("tip");
  const showTip = (nodes, x, y) => {
    tip.replaceChildren(...nodes);
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    const left = Math.min(Math.max(8, x + 14), window.innerWidth - r.width - 8);
    const top = y - r.height - 12 < 8 ? y + 18 : y - r.height - 12;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  };
  const hideTip = () => { tip.hidden = true; };
  const tipRow = (color, label, value) => {
    const row = h("div", "row");
    const key = h("span", "key");
    key.style.background = color;
    row.append(key, h("b", "", value), h("span", "sub", label));
    return row;
  };

  // ---------------------------------------------------------------- generic table
  function table(host, { caption, cols, rows }) {
    const t = h("table");
    if (caption) t.append(h("caption", "", caption));
    const thead = h("thead");
    const tr = h("tr");
    cols.forEach((c) => { const th = h("th", c.num ? "num" : "", c.label); th.scope = "col"; tr.append(th); });
    thead.append(tr);
    const tb = h("tbody");
    rows.forEach((r) => {
      const row = h("tr");
      cols.forEach((c) => {
        const td = h("td", (c.num ? "num " : "") + (c.cls || ""));
        const v = c.render ? c.render(r) : r[c.key];
        if (v instanceof Node) td.append(v); else td.textContent = v ?? "";
        row.append(td);
      });
      tb.append(row);
    });
    t.append(thead, tb);
    host.replaceChildren(t);
  }

  // ---------------------------------------------------------------- line chart
  function lineChart(host, o) {
    host.replaceChildren();
    const W = Math.max(320, host.getBoundingClientRect().width || 800);
    const H = o.height || 340;
    const m = { t: 16, r: o.right ?? 20, b: 30, l: 48 };
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    const allX = o.series.flatMap((s) => s.points.map((p) => p.x));
    const xd = o.xDomain || d3.extent(allX);
    const x = d3.scaleUtc().domain(xd).range([m.l, W - m.r]);
    const ymax = o.yMax ?? d3.max([...o.series.flatMap((s) => s.points.map((p) => p.y)), ...(o.band ? o.band.points.map((p) => p.hi) : [])]) * 1.08;
    const y = d3.scaleLinear().domain([0, ymax]).nice().range([H - m.b, m.t]);

    svg.append("g").attr("class", "grid").selectAll("line").data(y.ticks(5)).join("line")
      .attr("x1", m.l).attr("x2", W - m.r).attr("y1", (d) => y(d)).attr("y2", (d) => y(d));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(W / 120))).tickSizeOuter(0).tickFormat(d3.utcFormat(o.xFormat || "%b %Y")));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(5).tickSize(0).tickPadding(8).tickFormat(compact)).call((g) => g.select(".domain").remove());

    if (o.band) {
      const area = d3.area().x((p) => x(p.x)).y0((p) => y(p.lo)).y1((p) => y(p.hi));
      svg.append("path").attr("d", area(o.band.points)).attr("fill", o.band.color).attr("opacity", 0.14);
    }
    (o.marks || []).forEach((mk) => {
      const px = x(mk.x);
      svg.append("line").attr("x1", px).attr("x2", px).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--ink-3")).attr("stroke-width", 1);
      const lines = mk.label.split("\n");
      const anchor = mk.side === "left" ? "end" : "start";
      lines.forEach((ln, i) => svg.append("text").attr("x", px + (mk.side === "left" ? -8 : 8)).attr("y", m.t + 14 + i * 15).attr("text-anchor", anchor).attr("class", i === 0 ? "lbl" : "").text(ln));
    });
    const line = d3.line().x((p) => x(p.x)).y((p) => y(p.y)).curve(d3.curveLinear);
    o.series.forEach((s) => {
      svg.append("path").attr("d", line(s.points)).attr("fill", "none").attr("stroke", s.color).attr("stroke-width", 2).attr("stroke-linejoin", "round").attr("stroke-linecap", "round");
      if (s.endDot) {
        const p = s.points[s.points.length - 1];
        svg.append("circle").attr("cx", x(p.x)).attr("cy", y(p.y)).attr("r", 4).attr("fill", s.color).attr("stroke", css("--paper")).attr("stroke-width", 2);
      }
    });
    (o.labels || []).forEach((lb) => {
      const g = svg.append("g").attr("transform", `translate(${x(lb.x)},${y(lb.y)})`);
      g.append("circle").attr("r", 4).attr("cx", lb.dx || 0).attr("cy", lb.dy || 0).attr("fill", lb.color).attr("stroke", css("--paper")).attr("stroke-width", 2);
      g.append("text").attr("x", (lb.dx || 0) + 10).attr("y", (lb.dy || 0) + 4).attr("class", "lbl").text(lb.text);
    });

    // crosshair + tooltip (also reachable by keyboard)
    const xs = Array.from(new Set(allX.map((d) => +d))).sort((a, b) => a - b);
    const at = (t) => o.series.map((s) => ({ s, p: s.points.find((p) => +p.x === t) })).filter((r) => r.p);
    const bandAt = (t) => (o.band ? o.band.points.find((p) => +p.x === t) : null);
    const cross = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--ink-2")).attr("stroke-width", 1).style("display", "none");
    let idx = xs.length - 1;
    const show = (i, cx, cy) => {
      idx = Math.max(0, Math.min(xs.length - 1, i));
      const t = xs[idx];
      cross.attr("x1", x(new Date(t))).attr("x2", x(new Date(t))).style("display", null);
      const nodes = [h("div", "sub", "Week of " + fmtDate(new Date(t)))];
      at(t).forEach((r) => nodes.push(tipRow(r.s.color, r.s.name, int(r.p.y))));
      const b = bandAt(t);
      if (b) nodes.push(h("div", "sub", `80% band ${int(b.lo)} to ${int(b.hi)}`));
      const rect = host.getBoundingClientRect();
      showTip(nodes, cx ?? rect.left + x(new Date(t)), cy ?? rect.top + y(at(t)[0]?.p.y ?? 0));
    };
    const hit = svg.append("rect").attr("class", "hit").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b);
    hit.on("pointermove", (ev) => {
      const t = +x.invert(d3.pointer(ev, svg.node())[0]);
      const i = d3.bisectCenter(xs, t);
      show(i, ev.clientX, ev.clientY);
    }).on("pointerleave", () => { cross.style("display", "none"); hideTip(); });
    host.tabIndex = 0;
    host.onkeydown = (ev) => {
      if (ev.key === "ArrowLeft") { ev.preventDefault(); show(idx - 1); }
      if (ev.key === "ArrowRight") { ev.preventDefault(); show(idx + 1); }
      if (ev.key === "Escape") { cross.style("display", "none"); hideTip(); }
    };
    host.onblur = () => { cross.style("display", "none"); hideTip(); };
  }

  // ---------------------------------------------------------------- horizontal bars
  function barChart(host, o) {
    host.replaceChildren();
    const W = Math.max(320, host.getBoundingClientRect().width || 600);
    const rowH = 44, thick = 20, m = { t: 6, r: 64, b: 8, l: 118 };
    const H = m.t + m.b + rowH * o.rows.length;
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    const x = d3.scaleLinear().domain([0, o.max]).range([0, W - m.l - m.r]);
    svg.append("g").attr("class", "grid").selectAll("line").data(x.ticks(4)).join("line")
      .attr("x1", (d) => m.l + x(d)).attr("x2", (d) => m.l + x(d)).attr("y1", m.t).attr("y2", H - m.b);
    o.rows.forEach((r, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      const w = Math.max(2, x(r.value)), rad = Math.min(4, w);
      const g = svg.append("g").attr("tabindex", 0).attr("role", "img").attr("aria-label", `${r.label}: ${o.format(r.value)}`);
      g.append("text").attr("x", m.l - 12).attr("y", cy + 4).attr("text-anchor", "end").text(r.label);
      g.append("path").attr("fill", o.color).attr("d", `M${m.l},${cy - thick / 2} H${m.l + w - rad} a${rad},${rad} 0 0 1 ${rad},${rad} V${cy + thick / 2 - rad} a${rad},${rad} 0 0 1 ${-rad},${rad} H${m.l} Z`);
      g.append("text").attr("x", m.l + w + 8).attr("y", cy + 4).attr("class", "lbl").text(o.format(r.value));
      const rect = g.append("rect").attr("class", "hit").attr("x", 0).attr("y", cy - rowH / 2).attr("width", W).attr("height", rowH);
      const nodes = () => [h("b", "", o.format(r.value)), h("div", "sub", r.label), ...(r.sub ? [h("div", "sub", r.sub)] : [])];
      rect.on("pointermove", (ev) => showTip(nodes(), ev.clientX, ev.clientY)).on("pointerleave", hideTip);
      g.on("focus", () => { const b = g.node().getBoundingClientRect(); showTip(nodes(), b.left + b.width / 2, b.top + b.height / 2); }).on("blur", hideTip);
    });
  }

  // ---------------------------------------------------------------- alert strip
  function stripChart(host, o) {
    host.replaceChildren();
    const W = Math.max(320, host.getBoundingClientRect().width || 800);
    const rowH = 34, m = { t: 8, r: 16, b: 58, l: 176 };
    const H = m.t + m.b + rowH * o.rows.length;
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("width", W).attr("height", H);
    const x = d3.scaleUtc().domain(o.domain).range([m.l, W - m.r]);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(W / 130))).tickSizeOuter(0).tickFormat(d3.utcFormat("%b %Y")));
    o.rows.forEach((r, i) => {
      const cy = m.t + i * rowH + rowH / 2;
      svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", cy).attr("y2", cy).attr("stroke", css("--grid"));
      svg.append("text").attr("x", m.l - 12).attr("y", cy + 4).attr("text-anchor", "end").text(r.label);
    });
    const yi = new Map(o.rows.map((r, i) => [r.key, m.t + i * rowH + rowH / 2]));
    o.points.forEach((p) => {
      const cx = x(p.date), cy = yi.get(p.kpi);
      const g = svg.append("g").attr("tabindex", 0).attr("role", "img").attr("aria-label", p.summary);
      const filled = p.type !== "level_shift";
      g.append("circle").attr("cx", cx).attr("cy", cy).attr("r", 5).attr("fill", filled ? o.color : "none").attr("stroke", o.color).attr("stroke-width", 2);
      g.append("circle").attr("class", "hit").attr("cx", cx).attr("cy", cy).attr("r", 14);
      const nodes = () => [h("b", "", p.title), h("div", "sub", p.summary)];
      g.on("pointermove", (ev) => showTip(nodes(), ev.clientX, ev.clientY)).on("pointerleave", hideTip)
        .on("focus", () => { const b = g.node().getBoundingClientRect(); showTip(nodes(), b.left + b.width / 2, b.top); }).on("blur", hideTip);
    });
    const lg = svg.append("g").attr("transform", `translate(${m.l},${H - 8})`);
    lg.append("circle").attr("cx", 4).attr("cy", -3).attr("r", 4).attr("fill", o.color);
    lg.append("text").attr("x", 14).attr("y", 0).attr("class", "muted").text("single week");
    lg.append("circle").attr("cx", 110).attr("cy", -3).attr("r", 4).attr("fill", "none").attr("stroke", o.color).attr("stroke-width", 2);
    lg.append("text").attr("x", 120).attr("y", 0).attr("class", "muted").text("three or more weeks in a row");
  }

  // ---------------------------------------------------------------- page
  const get = (f) => fetch(`data/${f}.json`).then((r) => { if (!r.ok) throw new Error(f + " " + r.status); return r.json(); });
  let D = null;

  function render() {
    const { forecast: F, anomalies: A, metrics: M, ship: S, overview: O, catalog: C } = D;
    const blue = css("--blue"), orange = css("--orange");
    const br = F.structural_break, pre = br.profile.metrics.pre, post = br.profile.metrics.post;
    const breakDate = parseDay(br.week);

    $("lede").textContent = `${int(O.orders)} orders, ${int(O.order_lines)} order lines and ${int(O.customers)} customers from ${fmtMonth(parseDay(O.first_order))} to ${fmtMonth(parseDay(O.last_order))}. This page covers the pipeline behind the numbers, the metrics, a forecast, an anomaly detector, and the places where the data limits what can be claimed.`;

    // volume
    $("volume-title").textContent = `Weekly order volume fell ${Math.abs(Math.round(br.pct_change))}% in the week of ${fmtDate(breakDate)}`;
    setParas($("volume-text"), [
      `Until then the business shipped about ${int(br.mean_weekly_before)} order lines a week and rarely strayed more than a few percent from that. Since then it has shipped about ${int(br.mean_weekly_after)}.`,
      `Service levels held steady. What changed is the catalogue: orders now cover ${int(post.distinct_products)} products instead of ${int(pre.distinct_products)}, with ${num(post.units_per_line)} unit per line instead of ${num(pre.units_per_line)}. The data cannot say why, so this is a question for the business, not a conclusion.`,
    ]);
    const facts = [
      ["Products ordered", `${int(pre.distinct_products)} to ${int(post.distinct_products)}`],
      ["Units per line", `${num(pre.units_per_line)} to ${num(post.units_per_line)}`],
      ["Average line value", `${usd(pre.avg_line_net_sales)} to ${usd(post.avg_line_net_sales)}`],
      ["Late delivery rate", `${pct(pre.late_rate)} to ${pct(post.late_rate)}`],
      ["Cancellation rate", `${pct(pre.cancel_rate, 2)} to ${pct(post.cancel_rate, 2)}`],
      ["Suspected fraud rate", `${pct(pre.fraud_rate, 2)} to ${pct(post.fraud_rate, 2)}`],
    ];
    $("volume-facts").replaceChildren(...facts.map(([k, v]) => { const d = h("div"); d.append(h("dt", "", k), h("dd", "", v)); return d; }));

    const hist = F.history_total_weekly.map((r) => ({ x: parseDay(r.ds), y: r.y }));
    const preP = hist.filter((p) => p.x < breakDate), postP = hist.filter((p) => p.x >= breakDate);
    const connect = [preP[preP.length - 1], ...postP];
    lineChart($("chart-volume"), {
      height: 360, right: 24, yMax: 1500,
      series: [
        { name: "Before the drop", color: blue, points: preP },
        { name: "After the drop", color: orange, points: connect, endDot: true },
      ],
      marks: [{ x: breakDate, label: `${fmtDate(breakDate)}\n${int(br.mean_weekly_before)} to ${int(br.mean_weekly_after)} lines a week`, side: "left" }],
    });
    table($("table-volume"), {
      caption: "Weekly order lines",
      cols: [{ key: "week", label: "Week starting" }, { key: "lines", label: "Order lines", num: true }],
      rows: hist.map((p) => ({ week: fmtDate(p.x), lines: int(p.y) })).reverse(),
    });

    // delivery
    const modes = [...S].sort((a, b) => b.late_delivery_rate - a.late_delivery_rate);
    const first = S.find((r) => r.shipping_mode === "First Class"), std = S.find((r) => r.shipping_mode === "Standard Class");
    const mk = M.metrics.find((m) => m.name === "on_time_delivery_rate").by_dimension.market.map((r) => r.value);
    $("delivery-title").textContent = "Shipping mode decides whether an order is late, not the market";
    setParas($("delivery-text"), [
      `First Class is promised in ${num(first.avg_days_scheduled, 0)} day and took ${num(first.avg_days_actual)} on average, so ${pct(first.late_delivery_rate, 0)} of its lines were late. Standard Class was late on ${pct(std.late_delivery_rate)}.`,
      `By market, the on-time rate only ranges from ${pct(Math.min(...mk))} to ${pct(Math.max(...mk))}, so geography explains almost none of it.`,
    ]);
    $("delivery-caveat").textContent = "A pattern this regular looks like how the data was generated rather than real carrier behaviour. Read it as a service-level finding, not a carrier ranking.";
    barChart($("chart-delivery"), {
      rows: modes.map((r) => ({ label: r.shipping_mode, value: r.late_delivery_rate, sub: `${int(r.order_lines)} order lines` })),
      max: 1, color: orange, format: (v) => pct(v, v === 1 ? 0 : 1),
    });
    table($("table-delivery"), {
      caption: "Shipping mode scorecard",
      cols: [
        { key: "shipping_mode", label: "Mode" },
        { label: "Promised days", num: true, render: (r) => num(r.avg_days_scheduled, 1) },
        { label: "Actual days", num: true, render: (r) => num(r.avg_days_actual, 2) },
        { label: "Late", num: true, render: (r) => pct(r.late_delivery_rate) },
        { label: "Profit margin", num: true, render: (r) => pct(r.profit_margin) },
        { label: "Order lines", num: true, render: (r) => int(r.order_lines) },
      ],
      rows: [...S].sort((a, b) => a.speed_rank - b.speed_rank),
    });

    // forecast
    const bt = F.backtest, ch = bt.champion_by_level, lb = bt.leaderboard_by_level;
    const wp = (lvl, model) => lb[lvl].find((r) => r.model === model).wape;
    const ratio = 1 + F.cost_of_ignoring_break.bias_pct_autoets / 100;
    const zs = F.intermittency_zero_week_share_pre_break, cf = F.conformal_interval_total_champion;
    $("forecast-title").textContent = "Only the weekly total can be forecast";
    setParas($("forecast-text"), [
      `Before the break, weekly order lines for the whole business stayed near ${int(br.mean_weekly_before)}. Over ${bt.windows} rolling backtests of ${bt.horizon_weeks} weeks, ${ch.TOTAL} was off by ${pct(wp("TOTAL", ch.TOTAL))} (WAPE).`,
      `Markets and departments behave differently: ${pct(zs.MARKET, 0)} of market-weeks and ${pct(zs.SEGMENT, 0)} of segment-weeks had no orders, then bursts. Errors there are ${pct(wp("MARKET", ch.MARKET), 0)} and ${pct(wp("SEGMENT", ch.SEGMENT), 0)}. Rescaling LightGBM so segments add up to the total beat the naive forecast at both levels.`,
    ]);
    const ff = [
      ["Forecasting through the break", `${num(ratio, 1)} times too high`],
      ["80% interval, holdout coverage", `${pct(cf.holdout_coverage, 1)} of ${cf.holdout_points} weeks`],
      ["Weeks since the break", `${br.post_break_weeks}, too few to learn from`],
      ["Models compared", "Naive, seasonal naive, ETS, Theta, LightGBM, ensemble"],
    ];
    $("forecast-facts").replaceChildren(...ff.map(([k, v]) => { const d = h("div"); d.append(h("dt", "", k), h("dd", "", v)); return d; }));
    const since = parseDay("2017-01-02");
    const fh = hist.filter((p) => p.x >= since);
    const fc = F.production_forecast.rows.map((r) => ({ x: parseDay(r.ds), y: r.yhat, lo: r.lo80, hi: r.hi80 }));
    const lastH = fh[fh.length - 1];
    lineChart($("chart-forecast"), {
      height: 330, right: 24, yMax: 1500, xFormat: "%b %Y",
      series: [
        { name: "Actual", color: orange, points: fh.filter((p) => p.x >= breakDate).length ? fh : fh },
        { name: "Forecast", color: blue, points: [lastH, ...fc.map((p) => ({ x: p.x, y: p.y }))], endDot: true },
      ],
      band: { color: blue, points: [{ x: lastH.x, lo: lastH.y, hi: lastH.y }, ...fc.map((p) => ({ x: p.x, lo: p.lo, hi: p.hi }))] },
      marks: [{ x: breakDate, label: "Break", side: "left" }],
    });
    $("forecast-cap").textContent = `Forecast: next ${fc.length} weeks from a non-seasonal ETS fitted on the ${br.post_break_weeks} post-break weeks only. The weekly total has been nearly flat since the break, so the band is narrow; treat it with caution.`;

    const boards = $("leaderboards");
    boards.replaceChildren();
    [["TOTAL", "Total"], ["MARKET", "Market (5 series)"], ["SEGMENT", "Market by department (38 series)"]].forEach(([lvl, name]) => {
      const host = h("div");
      boards.append(host);
      table(host, {
        caption: name,
        cols: [
          { label: "Model", render: (r) => { const s = h("span", r.model === ch[lvl] ? "champ" : "", r.model.replace("LightGBM_TD", "LightGBM reconciled")); return s; } },
          { label: "WAPE", num: true, render: (r) => { const w = h("span"); const wrap = h("span"); const barw = Math.min(r.wape, 0.6) / 0.6 * 56; const b = h("span", "bar" + (r.wape > 0.6 ? " off" : "")); b.style.width = barw + "px"; wrap.append(b, document.createTextNode(" " + (r.wape > 1 ? ">100%" : pct(r.wape, 1)))); w.append(wrap); return w; } },
        ],
        rows: lb[lvl],
      });
    });

    // anomalies
    const al = A.alerts, kp = Object.keys(A.injection_validation);
    const top = [...al].sort((a, b) => Math.abs(b.z) - Math.abs(a.z))[0];
    const r6 = kp.map((k) => A.injection_validation[k].find((x) => x.injected_sigma === 6).recall);
    const r3 = kp.map((k) => A.injection_validation[k].find((x) => x.injected_sigma === 3).recall);
    const fp = kp.flatMap((k) => A.injection_validation[k].map((x) => x.false_positive_rate));
    $("anomaly-title").textContent = "Alerts are only useful if you know how often they are wrong";
    setParas($("anomaly-text"), [
      `${al.length} alerts across ${kp.length} weekly KPIs in ${A.weeks_scanned} weeks. The largest is the volume break (${num(top.z, 1)} robust standard deviations).`,
      `To measure the detector, known spikes were injected into the ${A.injection_validation_weeks} clean pre-break weeks. It caught ${pct(Math.min(...r6), 0)} to ${pct(Math.max(...r6), 0)} of 6σ spikes with at most ${pct(Math.max(...fp), 1)} false alarms per normal week, but only ${pct(Math.min(...r3), 0)} to ${pct(Math.max(...r3), 0)} of 3σ spikes.`,
    ]);
    $("anomaly-caveat").textContent = "At this threshold roughly one normal week in a hundred is flagged by chance, so expect a few false alerts per KPI over three years.";
    const rows = Object.entries({ order_lines: "Order lines", on_time_delivery_rate: "On-time delivery rate", cancellation_rate: "Cancellation rate", suspected_fraud_rate: "Suspected fraud rate", profit_margin: "Profit margin", avg_delay_days: "Average delay (days)" }).map(([key, label]) => ({ key, label }));
    const fmtVal = (k, v) => (k === "order_lines" ? int(v) : k === "avg_delay_days" ? num(v, 2) : pct(v, 1));
    const pts = al.map((a) => ({
      date: parseDay(a.week), kpi: a.kpi, type: a.type,
      title: `${a.label}, week of ${fmtDate(parseDay(a.week))}`,
      summary: `${fmtVal(a.kpi, a.value)} against ${fmtVal(a.kpi, a.expected)} expected (z ${num(a.z, 1)}, ${a.type === "level_shift" ? "part of a sustained shift" : "single week"})`,
    }));
    stripChart($("chart-anomaly"), { rows, points: pts, color: orange, domain: d3.extent(A.weekly_kpis, (r) => parseDay(r.week)) });
    table($("table-anomaly"), {
      caption: "Alerts, largest first",
      cols: [
        { label: "Week", render: (r) => fmtDate(parseDay(r.week)) },
        { key: "label", label: "KPI" },
        { label: "Value", num: true, render: (r) => fmtVal(r.kpi, r.value) },
        { label: "Expected", num: true, render: (r) => fmtVal(r.kpi, r.expected) },
        { label: "z", num: true, render: (r) => num(r.z, 1) },
        { label: "Pattern", render: (r) => (r.type === "level_shift" ? "Sustained shift" : "Single week") },
      ],
      rows: [...al].sort((a, b) => Math.abs(b.z) - Math.abs(a.z)),
    });
    const lab = Object.fromEntries(rows.map((r) => [r.key, r.label]));
    table($("table-validation"), {
      caption: "Injection test: share of injected spikes caught, and false alarms on normal weeks",
      cols: [
        { label: "KPI", render: (r) => lab[r.k] },
        { label: "3σ", num: true, render: (r) => pct(r.v[0].recall, 0) },
        { label: "4σ", num: true, render: (r) => pct(r.v[1].recall, 0) },
        { label: "6σ", num: true, render: (r) => pct(r.v[2].recall, 0) },
        { label: "False alarms", num: true, render: (r) => pct(r.v[1].false_positive_rate, 1) },
      ],
      rows: kp.map((k) => ({ k, v: A.injection_validation[k] })),
    });

    // metrics + catalog
    $("metrics-text").textContent = `${M.metrics.length} metrics are defined once, as SQL, in metrics/metrics.yml. Each is executed against the star schema, and the ones that can be derived from the KPI marts are reconciled to them. Anything that reads these definitions agrees on what a number means.`;
    $("source-limits").replaceChildren(...C.sources[0].caveats.map((c) => h("li", "", c)));
    const unitFmt = (m) => (m.unit === "ratio" ? pct(m.overall, 1) : m.unit === "usd" ? "$" + d3.format(",.2s")(m.overall).replace("G", "B") : m.unit === "days" ? num(m.overall, 2) : int(m.overall));
    table($("table-metrics"), {
      caption: "Governed metrics, all time",
      cols: [
        { label: "Metric", render: (m) => m.label },
        { label: "Definition", cls: "dim", render: (m) => m.description },
        { label: "Value", num: true, render: unitFmt },
        { label: "Better when", render: (m) => (m.good_direction === "up" ? "Higher" : "Lower") },
      ],
      rows: M.metrics,
    });
    table($("table-catalog"), {
      caption: `Warehouse tables (${C.tables.length}), ${C.tests.dbt_test_results.pass || 0} dbt tests passing`,
      cols: [
        { label: "Table", render: (t) => t.name },
        { label: "Layer", key: "layer" },
        { label: "Rows", num: true, render: (t) => (t.rows == null ? "view" : int(t.rows)) },
        { label: "Built from", cls: "dim", render: (t) => t.upstream.join(", ") || "Parquet source" },
      ],
      rows: C.tables,
    });

    // method
    const steps = [
      "scripts/fetch_data.py downloads the DataCo CSV from a pinned commit and verifies its size and row count.",
      `PySpark removes personal fields, casts types and applies ${11} quality rules, sending failing rows to a quarantine table. All ${int(D.etl.curated_rows)} rows passed; unit tests with injected defects confirm the gate catches them.`,
      `dbt on DuckDB builds a star schema and KPI marts with ${C.tests.dbt_test_results.pass || 0} data tests.`,
      "Metrics, the forecast and the anomaly detector run against the marts, and GitHub Actions rebuilds this page on every push.",
    ];
    $("method-steps").replaceChildren(...steps.map((s) => h("li", "", s)));
    $("attribution").textContent = "Data: DataCo Smart Supply Chain for Big Data Analysis, Constante, Silva and Pereira (2019), Mendeley Data, licensed CC BY 4.0, read from a pinned GitHub mirror. The dataset has no inventory, supplier or shipped-quantity fields, so on-time-in-full and inventory turns are not computed.";
    const foot = $("foot");
    foot.replaceChildren(document.createTextNode("Built by Nagaraj Gireppa Kanni. Source and reproduction steps: "), Object.assign(h("a", "", "github.com/Nags-gk/supplypulse"), { href: REPO }), document.createTextNode("."));
  }

  // theme toggle
  const root = document.documentElement;
  try { const t = localStorage.getItem("sp-theme"); if (t) root.dataset.theme = t; } catch (e) { /* storage unavailable */ }
  $("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("sp-theme", root.dataset.theme); } catch (e) { /* ignore */ }
    if (D) render();
  });

  Promise.all(["forecast", "anomalies", "metrics", "scorecard_shipping_mode", "overview", "catalog", "etl_report"].map(get)).then(([forecast, anomalies, metrics, ship, overview, catalog, etl]) => {
    D = { forecast, anomalies, metrics, ship, overview, catalog, etl };
    render();
    let t;
    new ResizeObserver(() => { clearTimeout(t); t = setTimeout(render, 150); }).observe(document.querySelector("main"));
  }).catch((e) => { $("lede").textContent = "The data files could not be loaded: " + e.message; });
})();
