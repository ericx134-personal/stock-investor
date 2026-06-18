(function () {
  "use strict";

  const RANGE_ORDER = ["1D", "1W", "1M", "3M", "YTD", "1Y", "5Y", "MAX"];
  const GREEN = "#00c805";
  const RED = "#ff5a5f";
  const ORANGE = "#ff5000";
  const AMBER = "#f5b642";
  const WHITE = "#e6e6e6";
  const stateByCard = new WeakMap();
  let externalPayloads = null;
  let externalPayloadPromise = null;
  let externalPayloadAttempted = false;
  let externalPayloadComplete = false;

  function readJsonScript(selector) {
    const node = document.querySelector(selector);
    return readJsonElement(node);
  }

  function readJsonElement(node) {
    if (!node || !node.textContent.trim()) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      console.warn("Invalid K-line payload JSON", error);
      return null;
    }
  }

  function payloadForCard(card) {
    const localPayload = readJsonElement(card.querySelector(".kline-local-payload"));
    if (localPayload && localPayload.symbol === card.dataset.chartSymbol) {
      return localPayload;
    }
    if (externalPayloads && externalPayloads.symbols) {
      return externalPayloads.symbols[card.dataset.chartSymbol] || null;
    }
    const payloads = readJsonScript("#chart-payloads-v1");
    return payloads && payloads.symbols ? payloads.symbols[card.dataset.chartSymbol] || null : null;
  }

  function loadExternalPayloads() {
    const node = document.querySelector("#chart-payloads-v1");
    const source = node ? node.getAttribute("data-src") : null;
    if (!source || !window.fetch) return Promise.resolve(null);
    if (!externalPayloadPromise) {
      externalPayloadAttempted = true;
      externalPayloadPromise = fetch(source, { cache: "no-store" })
        .then((response) => {
          if (!response.ok) throw new Error(`chart payload ${response.status}`);
          return response.json();
        })
        .then((payloads) => {
          externalPayloads = payloads;
          externalPayloadComplete = true;
          return payloads;
        })
        .catch((error) => {
          console.warn("Unable to load chart-payloads-v1.json", error);
          externalPayloadComplete = true;
          return null;
        });
    }
    return externalPayloadPromise;
  }

  function addSeries(chart, type, options) {
    const library = window.LightweightCharts;
    if (chart.addSeries && library && library[type]) {
      return chart.addSeries(library[type], options);
    }
    if (type === "CandlestickSeries" && chart.addCandlestickSeries) {
      return chart.addCandlestickSeries(options);
    }
    if (type === "HistogramSeries" && chart.addHistogramSeries) {
      return chart.addHistogramSeries(options);
    }
    throw new Error(`Unsupported Lightweight Charts series API: ${type}`);
  }

  function formatMoney(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "pending";
    return `$${Number(value).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }

  function formatVolume(value) {
    const number = Number(value || 0);
    if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(1)}B`;
    if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
    if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
    return number.toFixed(0);
  }

  function parseDate(value) {
    const parts = String(value).split("-").map((part) => Number(part));
    return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  }

  function isoDate(date) {
    return date.toISOString().slice(0, 10);
  }

  function aggregateBars(bars, aggregation) {
    if (!aggregation || aggregation === "none") return bars;
    const groups = new Map();
    bars.forEach((bar) => {
      const date = parseDate(bar.time);
      let key;
      if (aggregation === "monthly") {
        key = `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-01`;
      } else {
        const monday = new Date(date);
        monday.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
        key = isoDate(monday);
      }
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(bar);
    });
    return Array.from(groups.entries()).map(([time, items]) => ({
      time,
      open: Number(items[0].open),
      high: Math.max(...items.map((item) => Number(item.high))),
      low: Math.min(...items.map((item) => Number(item.low))),
      close: Number(items[items.length - 1].close),
      volume: items.reduce((total, item) => total + Number(item.volume || 0), 0),
      source: `${aggregation}_aggregate`,
    }));
  }

  function rangeBars(payload, rangeName) {
    if (!payload || !payload.ranges || !payload.ranges[rangeName]) return [];
    const range = payload.ranges[rangeName];
    if (range.bars) return range.bars;
    const daily = payload.bars_daily || [];
    if (!daily.length) return [];
    let selected = [];
    if (rangeName === "YTD") {
      const latestYear = parseDate(daily[daily.length - 1].time).getUTCFullYear();
      selected = daily.filter((bar) => parseDate(bar.time).getUTCFullYear() === latestYear);
    } else if (rangeName === "MAX") {
      selected = daily;
    } else {
      const windows = { "1D": 5, "1W": 7, "1M": 21, "3M": 63, "1Y": 252, "5Y": 1260 };
      selected = daily.slice(-Math.min(windows[rangeName] || daily.length, daily.length));
    }
    return aggregateBars(selected, range.aggregation);
  }

  function activeRange(payload) {
    const preferred = payload.default_range || "YTD";
    if (payload.ranges && payload.ranges[preferred] && payload.ranges[preferred].available) return preferred;
    return RANGE_ORDER.find((rangeName) => (
      payload.ranges && payload.ranges[rangeName] && payload.ranges[rangeName].available
    )) || "1D";
  }

  function setStatus(card, message, isError) {
    const status = card.querySelector("[data-chart-status]");
    if (!status) return;
    status.hidden = !message;
    status.textContent = message || "";
    status.classList.toggle("error", Boolean(isError));
  }

  function showFallback(card, show) {
    const fallback = card.querySelector("[data-chart-fallback]");
    if (fallback) fallback.hidden = !show;
  }

  function markerColor(marker) {
    if (marker.outcome === "miss") return RED;
    if (marker.outcome === "hit") return GREEN;
    if (marker.signal === "buy") return GREEN;
    if (marker.signal === "sell") return ORANGE;
    return AMBER;
  }

  function renderMarkers(state, bars) {
    const timeSet = new Set(bars.map((bar) => bar.time));
    const markers = (state.payload.markers || [])
      .filter((marker) => timeSet.has(marker.time))
      .map((marker) => ({
        time: marker.time,
        position: marker.signal === "sell" ? "aboveBar" : "belowBar",
        color: markerColor(marker),
        shape: "circle",
        text: marker.label || marker.type || "",
      }));
    if (window.LightweightCharts && window.LightweightCharts.createSeriesMarkers) {
      if (state.markerApi && state.markerApi.setMarkers) state.markerApi.setMarkers(markers);
      else state.markerApi = window.LightweightCharts.createSeriesMarkers(state.candles, markers);
    } else if (state.candles.setMarkers) {
      state.candles.setMarkers(markers);
    }
  }

  function lineColor(line) {
    if (line.type === "current") return GREEN;
    if (line.type === "cost") return WHITE;
    return AMBER;
  }

  function renderPriceLines(state) {
    for (const line of state.priceLines) {
      try {
        state.candles.removePriceLine(line);
      } catch (_error) {
        /* ignore stale library handles */
      }
    }
    state.priceLines = [];
    for (const line of state.payload.lines || []) {
      if (line.price === null || line.price === undefined) continue;
      state.priceLines.push(
        state.candles.createPriceLine({
          price: Number(line.price),
          color: lineColor(line),
          lineWidth: line.type === "current" ? 2 : 1,
          lineStyle:
            window.LightweightCharts &&
            window.LightweightCharts.LineStyle &&
            window.LightweightCharts.LineStyle.Dashed !== undefined
              ? window.LightweightCharts.LineStyle.Dashed
              : 2,
          axisLabelVisible: true,
          title: line.label,
        })
      );
    }
  }

  function zoneClass(zone) {
    if (zone.type === "support") return "support";
    if (zone.type === "buy") return "buy";
    if (zone.type === "breakout") return "breakout";
    return "resistance";
  }

  function updateOverlays(state) {
    const overlay = state.card.querySelector("[data-chart-overlay]");
    const root = state.card.querySelector("[data-chart-root]");
    if (!overlay || !root || !state.candles) return;
    const rootBox = root.getBoundingClientRect();
    const cardBox = state.card.getBoundingClientRect();
    overlay.style.left = `${rootBox.left - cardBox.left}px`;
    overlay.style.top = `${rootBox.top - cardBox.top}px`;
    overlay.style.width = `${rootBox.width}px`;
    overlay.style.height = `${rootBox.height}px`;
    overlay.replaceChildren();
    for (const zone of state.payload.zones || []) {
      const topCoordinate = state.candles.priceToCoordinate(Number(zone.high));
      const bottomCoordinate = state.candles.priceToCoordinate(Number(zone.low));
      if (topCoordinate === null || bottomCoordinate === null) continue;
      const top = Math.max(0, Math.min(topCoordinate, bottomCoordinate));
      const bottom = Math.min(rootBox.height, Math.max(topCoordinate, bottomCoordinate));
      if (bottom < 0 || top > rootBox.height) continue;
      const band = document.createElement("div");
      band.className = `kline-zone ${zoneClass(zone)}`;
      band.style.top = `${top}px`;
      band.style.height = `${Math.max(2, bottom - top)}px`;
      const label = document.createElement("span");
      label.className = "kline-zone-label";
      label.textContent = `${zone.label} ${formatMoney(zone.low)}–${formatMoney(zone.high)}`;
      band.appendChild(label);
      overlay.appendChild(band);
    }
  }

  function renderTooltip(state, param) {
    const tooltip = state.card.querySelector(".chart-tooltip");
    if (!tooltip) return;
    if (!param || !param.time || !param.point) {
      tooltip.hidden = true;
      return;
    }
    const candle = param.seriesData && param.seriesData.get ? param.seriesData.get(state.candles) : null;
    const volume = param.seriesData && param.seriesData.get ? param.seriesData.get(state.volume) : null;
    if (!candle) {
      tooltip.hidden = true;
      return;
    }
    tooltip.hidden = false;
    tooltip.innerHTML = `<b>${param.time}</b><span>O ${formatMoney(candle.open)} · H ${formatMoney(candle.high)} · L ${formatMoney(candle.low)}</span><span>C ${formatMoney(candle.close)} · Vol ${formatVolume(volume && volume.value)}</span>`;
    const root = state.card.querySelector("[data-chart-root]");
    const rootWidth = root ? root.clientWidth : 0;
    tooltip.style.left = `${Math.min(Math.max(param.point.x + 12, 8), Math.max(8, rootWidth - 230))}px`;
    tooltip.style.top = `${Math.max(70, param.point.y + 8)}px`;
  }

  function renderRange(card, rangeName) {
    const state = stateByCard.get(card);
    if (!state) return;
    const range = state.payload.ranges ? state.payload.ranges[rangeName] : null;
    if (!range || !range.available) return;
    const bars = rangeBars(state.payload, rangeName);
    const candles = bars.map((bar) => ({
      time: bar.time,
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
    const volume = bars.map((bar) => ({
      time: bar.time,
      value: Number(bar.volume || 0),
      color: Number(bar.close) >= Number(bar.open) ? "rgba(0,200,5,.32)" : "rgba(255,90,95,.32)",
    }));
    state.candles.setData(candles);
    state.volume.setData(volume);
    renderPriceLines(state);
    renderMarkers(state, bars);
    card.dataset.activeChartRange = rangeName;
    card.querySelectorAll("[data-chart-range]").forEach((button) => {
      button.classList.toggle("active", button.dataset.chartRange === rangeName);
    });
    const statusParts = [];
    if (range.fallback_reason) statusParts.push(range.fallback_reason);
    if (range.aggregation !== "none") {
      statusParts.push(`${range.raw_bar_count} daily bars aggregated to ${range.bar_count} ${range.aggregation} candles.`);
    }
    setStatus(card, statusParts.join(" ") || "");
    state.chart.timeScale().fitContent();
    requestAnimationFrame(() => updateOverlays(state));
  }

  function createChart(card, payload) {
    const root = card.querySelector("[data-chart-root]");
    if (!root) return null;
    const chart = window.LightweightCharts.createChart(root, {
      autoSize: true,
      layout: {
        background: { color: "#050505" },
        textColor: "#9aa0a6",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0)" },
        horzLines: { color: "rgba(255,255,255,.08)" },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      timeScale: {
        borderVisible: false,
        fixLeftEdge: true,
        fixRightEdge: true,
      },
      crosshair: {
        mode:
          window.LightweightCharts.CrosshairMode &&
          window.LightweightCharts.CrosshairMode.Normal !== undefined
            ? window.LightweightCharts.CrosshairMode.Normal
            : 0,
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: false,
        horzTouchDrag: false,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: false,
        mouseWheel: false,
        pinch: false,
      },
    });
    const candles = addSeries(chart, "CandlestickSeries", {
      upColor: GREEN,
      downColor: ORANGE,
      borderUpColor: GREEN,
      borderDownColor: ORANGE,
      wickUpColor: "#69727d",
      wickDownColor: "#69727d",
      priceLineVisible: false,
    });
    const volume = addSeries(chart, "HistogramSeries", {
      priceFormat: { type: "volume" },
      priceScaleId: "",
      base: 0,
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    const state = {
      card,
      payload,
      chart,
      candles,
      volume,
      markerApi: null,
      priceLines: [],
    };
    chart.subscribeCrosshairMove((param) => renderTooltip(state, param));
    stateByCard.set(card, state);
    return state;
  }

  function initCard(card) {
    if (stateByCard.has(card)) {
      const state = stateByCard.get(card);
      requestAnimationFrame(() => {
        state.chart.resize(
          card.querySelector("[data-chart-root]").clientWidth,
          card.querySelector("[data-chart-root]").clientHeight
        );
        updateOverlays(state);
      });
      return;
    }
    if (!window.LightweightCharts || !window.LightweightCharts.createChart) {
      setStatus(card, "Local chart runtime is missing.", true);
      showFallback(card, true);
      return;
    }
    const payload = payloadForCard(card);
    if (!payload) {
      const node = document.querySelector("#chart-payloads-v1");
      if (node && node.getAttribute("data-src") && (!externalPayloadAttempted || !externalPayloadComplete)) {
        setStatus(card, "Loading chart payload…");
        loadExternalPayloads().then(() => initCard(card));
        return;
      }
      setStatus(card, "Chart payload missing.", true);
      showFallback(card, true);
      return;
    }
    const root = card.querySelector("[data-chart-root]");
    if (!root || root.clientWidth < 20) return;
    const state = createChart(card, payload);
    if (!state) return;
    card.querySelectorAll("[data-chart-range]").forEach((button) => {
      button.addEventListener("click", () => renderRange(card, button.dataset.chartRange));
    });
    renderRange(card, activeRange(payload));
  }

  function initVisibleCharts() {
    document.querySelectorAll(".kline-chart-card").forEach((card) => {
      if (card.closest("[hidden]")) return;
      initCard(card);
    });
  }

  window.addEventListener("resize", () => {
    document.querySelectorAll(".kline-chart-card").forEach((card) => {
      const state = stateByCard.get(card);
      if (!state) return;
      requestAnimationFrame(() => updateOverlays(state));
    });
  });

  window.StockInvestorKline = {
    initVisibleCharts,
    renderRange,
  };
})();
