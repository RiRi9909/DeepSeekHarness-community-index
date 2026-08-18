/**
 * Browser half of dsh-sentiment-cockpit.
 * Registers a `settings.section` entry that renders the sentiment cockpit
 * (iframe srcDoc fed by `cockpit/getSnapshot` over the Typert gateway SRC
 * channel, polled every 60s).
 *
 * The host exposes `remote.cockpit` as a TypertRemoteService with SRC markers
 * (`getSnapshot` / `refresh` / `status`), which the Host gateway dispatches
 * without generated descriptors. On the client we call the same carrier the
 * typed Remote service uses — `ctx.connection.rpc.call("/api", endpoint, …)` —
 * so no generated client contribution is required.
 */
window.__ModuleLoader__.load({
  id: "dsh-sentiment-cockpit",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    let react = require("react");

    // ---- plugin css ------------------------------------------------------
    const css = [
      ".cockpit-root{display:flex;flex-direction:column;gap:10px;height:100%;min-height:560px;box-sizing:border-box}",
      ".cockpit-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}",
      ".cockpit-title{font-weight:600;font-size:14px}",
      ".cockpit-chip{font-size:11px;line-height:1;border-radius:999px;padding:4px 10px;",
      "  border:1px solid var(--dsw-alias-border-l2,rgba(255,255,255,.14));color:var(--dsw-alias-label-secondary,#8f98ab);",
      "  background:var(--dsw-alias-interactive-bg-hover,rgba(255,255,255,.05));white-space:nowrap}",
      ".cockpit-chip b{color:var(--dsw-alias-label-primary,#e9edf5)}",
      ".cockpit-chip.err{color:#ff8a80;border-color:rgba(255,92,92,.35)}",
      ".cockpit-btn{font-size:12px;line-height:1;border-radius:8px;padding:6px 12px;cursor:pointer;",
      "  border:1px solid var(--dsw-alias-border-l2,rgba(255,255,255,.14));",
      "  color:var(--dsw-alias-label-primary,#e9edf5);background:var(--dsw-alias-button-elevated-fill,rgba(255,255,255,.06))}",
      ".cockpit-btn:hover{background:var(--dsw-alias-button-floating-hover,rgba(255,255,255,.1))}",
      ".cockpit-btn:disabled{opacity:.5;cursor:default}",
      ".cockpit-frame{flex:1;min-height:480px;border:1px solid var(--dsw-alias-border-l2,rgba(255,255,255,.1));",
      "  border-radius:12px;background:#0a0d14;width:100%}",
      ".cockpit-note{font-size:11px;color:var(--dsw-alias-label-tertiary,#5d6678)}",
    ].join("\n");
    const tagId = "dsh-sentiment-cockpit/CockpitSection.css";
    if (typeof document !== "undefined" && document.querySelector("style[data-plugin-css=" + JSON.stringify(tagId) + "]") === null) {
      const tag = document.createElement("style");
      tag.dataset.plugin = "dsh-sentiment-cockpit";
      tag.dataset.pluginCss = tagId;
      tag.textContent = css;
      document.head.appendChild(tag);
    }

    // ---- dictionaries ----------------------------------------------------
    const NS = "sentiment-cockpit";
    const zh = {
      title: "社区情绪驾驶舱",
      refresh: "刷新数据",
      refreshing: "刷新中…",
      openNew: "新标签页打开",
      loading: "正在加载快照…",
      noData: "暂无数据：快照不可用。",
      lastUpdate: "数据更新",
      fallbackBadge: "内置快照",
      autoRefresh: "每 {minutes} 分钟自动刷新",
      hostUnavailable: "remote.cockpit 不可用：宿主插件未加载。",
      desktopWidget: "桌面小组件",
      running: "运行中",
      stopped: "未启动",
    };
    const en = {
      title: "Sentiment Cockpit",
      refresh: "Refresh",
      refreshing: "Refreshing…",
      openNew: "Open in new tab",
      loading: "Loading snapshot…",
      noData: "No data: snapshot unavailable.",
      lastUpdate: "Updated",
      fallbackBadge: "bundled snapshot",
      autoRefresh: "auto-refresh every {minutes} min",
      hostUnavailable: "remote.cockpit unavailable: the host plugin is not loaded.",
      desktopWidget: "Desktop widget",
      running: "running",
      stopped: "stopped",
    };

    const inject = ["slots", "locale", "connection"];

    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, { zh, en }), "sentiment-cockpit: dictionaries");
      const t = ctx.locale.bind(NS);
      const connection = ctx.connection;
      const call = async (method) => {
        const result = await connection.rpc.call("/api", `cockpit/${method}`, { args: {} }, undefined);
        if (!result?.ok) {
          const message = result?.error?.message ?? `cockpit.${method} failed`;
          const err = new Error(message);
          // The Host gateway reports an unmounted TypertRemoteService as
          // "no active Remote method exports this endpoint" — surface it as
          // the host plugin being absent rather than a raw gateway error.
          err.hostUnavailable = /no active Remote method/i.test(message);
          throw err;
        }
        return result.value;
      };
      const cockpit = {
        getSnapshot: () => call("getSnapshot"),
        refresh: () => call("refresh"),
        status: () => call("status"),
      };
      const injected = () => ({ cockpit, t });
      ctx.slots.inject("settings.section", () => ctx.slots.register({
        name: "settings.section",
        id: "sentiment-cockpit",
        order: 900,
        label: () => t("title"),
        locale: NS,
        inject: injected,
      }, CockpitSection));
    }

    function fmtTime(ts) {
      if (!ts) return "—";
      const d = new Date(ts);
      return d.toLocaleString("zh-CN", { hour12: false });
    }

    function CockpitSection(props) {
      const cockpit = props.cockpit;
      const [snap, setSnap] = react.useState(null);
      const [status, setStatus] = react.useState(null);
      const [error, setError] = react.useState(null);
      const [hostUnavailable, setHostUnavailable] = react.useState(false);
      const [busy, setBusy] = react.useState(false);

      const load = react.useCallback(async () => {
        if (!cockpit) return;
        try {
          const r = await cockpit.getSnapshot();
          if (r?.ok) { setSnap(r); setError(null); setHostUnavailable(false); }
          else setError(r?.error ?? "unknown");
        } catch (e) {
          setHostUnavailable(!!e?.hostUnavailable);
          setError(String(e?.message ?? e));
        }
      }, [cockpit]);

      const loadStatus = react.useCallback(async () => {
        if (!cockpit) return;
        try {
          const s = await cockpit.status();
          if (s) { setStatus(s); setHostUnavailable(false); }
        } catch (e) {
          if (e?.hostUnavailable) setHostUnavailable(true);
        }
      }, [cockpit]);

      react.useEffect(() => {
        void load();
        void loadStatus();
        const timer = setInterval(() => { void load(); void loadStatus(); }, 60 * 1000);
        return () => clearInterval(timer);
      }, [load, loadStatus]);

      const refresh = react.useCallback(async () => {
        if (!cockpit || busy) return;
        setBusy(true);
        try { await cockpit.refresh(); } catch (e) { setError(String(e?.message ?? e)); }
        await load();
        await loadStatus();
        setBusy(false);
      }, [cockpit, busy, load, loadStatus]);

      const openNew = react.useCallback(() => {
        if (!snap?.html) return;
        const blob = new Blob([snap.html], { type: "text/html" });
        window.open(URL.createObjectURL(blob), "_blank");
      }, [snap]);

      if (!cockpit || hostUnavailable) {
        return react.createElement("div", { className: "cockpit-root" },
          react.createElement("div", { className: "cockpit-note" },
            props.t?.("hostUnavailable") ?? "remote.cockpit 不可用：宿主插件未加载。"));
      }

      const zoneLabel = snap?.zone ?? "";
      const chips = [];
      if (snap?.ok && snap?.dsi !== undefined) {
        chips.push(react.createElement("span", { key: "dsi", className: "cockpit-chip" },
          "DSI ", react.createElement("b", null, snap.dsi), " ", zoneLabel));
        chips.push(react.createElement("span", { key: "anger", className: "cockpit-chip" },
          "愤怒指数 ", react.createElement("b", null, snap.anger)));
        chips.push(react.createElement("span", { key: "upd", className: "cockpit-chip" },
          props.t?.("lastUpdate") ?? "数据更新", " ", react.createElement("b", null, fmtTime(snap.updatedAt))));
        if (snap.fallback) chips.push(react.createElement("span", { key: "fb", className: "cockpit-chip" }, "内置快照"));
      }
      if (status?.enabled) chips.push(react.createElement("span", { key: "ar", className: "cockpit-chip cockpit-note" },
        (props.t?.("autoRefresh") ?? "auto-refresh").replace("{minutes}", status.intervalMinutes)));
      if (status?.desktop?.enabled) chips.push(react.createElement("span", { key: "dw", className: "cockpit-chip" },
        props.t?.("desktopWidget") ?? "桌面小组件", " ",
        react.createElement("b", null, status.desktop.running ? (props.t?.("running") ?? "运行中") : (props.t?.("stopped") ?? "未启动"))));
      if (error) chips.push(react.createElement("span", { key: "err", className: "cockpit-chip err" }, String(error).slice(0, 120)));

      return react.createElement("div", { className: "cockpit-root" },
        react.createElement("div", { className: "cockpit-bar" },
          chips,
          react.createElement("span", { style: { flex: 1 } }),
          react.createElement("button", {
            className: "cockpit-btn", onClick: refresh, disabled: busy,
            type: "button",
          }, busy ? (props.t?.("refreshing") ?? "Refreshing…") : (props.t?.("refresh") ?? "Refresh")),
          react.createElement("button", {
            className: "cockpit-btn", onClick: openNew, disabled: !snap?.html, type: "button",
          }, props.t?.("openNew") ?? "Open in new tab"),
        ),
        snap?.html
          ? react.createElement("iframe", { className: "cockpit-frame", srcDoc: snap.html, title: "Sentiment Cockpit" })
          : react.createElement("div", { className: "cockpit-note" }, error ? String(error) : (props.t?.("loading") ?? "Loading…")),
      );
    }

    exports.NS = NS;
    exports.apply = apply;
    exports.inject = inject;
    exports.CockpitSection = CockpitSection;
    return module.exports;
  },
});
