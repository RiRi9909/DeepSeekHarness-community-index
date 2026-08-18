/**
 * Host half of the DSH sentiment cockpit plugin.
 *
 * - Exposes `remote.cockpit` (Typert RPC): getSnapshot / refresh / status.
 * - Runs the python data pipeline (fetch -> index -> snapshot html) on a
 *   configurable interval (default 60 min, settings namespace
 *   `sentimentCockpit`).
 * - Serves the last good snapshot; bundled fallback ships in assets/fallback.
 */
import { Remote, TypertRemoteService } from "@deepseek-ai/dsh-typert-protocol";
import { settingsNamespace } from "@deepseek-ai/dsh-settings";
import z from "schemastery";
import { spawn, spawnSync } from "node:child_process";
import { readFile, mkdir, access, appendFile } from "node:fs/promises";
import { existsSync, chmodSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

const NS = "sentiment-cockpit";
const __dirname = dirname(fileURLToPath(import.meta.url));
const PIPELINE = join(__dirname, "pipeline", "run_pipeline.py");
const FALLBACK_DIR = join(__dirname, "..", "assets", "fallback");
const WIDGET_BIN = join(__dirname, "..", "assets", "desktop", "DSHCockpitWidget");
const WIDGET_SRC = join(__dirname, "..", "assets", "desktop", "main.swift");
const CACHE_DIR = join(
  process.env.DSH_HOME ?? join(homedir(), ".dsh"),
  "storages",
  "dsh-sentiment-cockpit",
);
const PIPELINE_TIMEOUT_MS = 20 * 60 * 1000;

const Config = z.object({
  enabled: z.boolean().default(true),
  intervalMinutes: z.number().min(10).max(24 * 60).default(60),
  desktopEnabled: z.boolean().default(false),
  desktopMode: z.union(["desktop", "floating"]).default("desktop"),
  desktopScale: z.number().min(0.7).max(1.6).default(1),
  desktopX: z.number().min(-1).default(-1),
  desktopY: z.number().min(-1).default(-1),
});

/** Plain-JS equivalent of `@Remote("name")` — populates the same marker table. */
function markRemote(instance, method, exportName) {
  Remote(exportName)(null, {
    name: method,
    private: false,
    static: false,
    addInitializer(fn) {
      fn.call(instance);
    },
  });
}

/** Runs the python pipeline, throwing on failure. */
function runPipeline() {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [PIPELINE, "--out", CACHE_DIR], {
      stdio: ["ignore", "pipe", "pipe"],
      timeout: PIPELINE_TIMEOUT_MS,
    });
    let out = "", err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ out });
      else reject(new Error(`pipeline exit ${code}: ${String(err).slice(-800) || String(out).slice(-800)}`));
    });
  });
}

class Engine {
  constructor(ctx, getConfig) {
    this.ctx = ctx;
    this.getConfig = getConfig;
    this.running = false;
    this.cache = null;
    this.state = {
      version: 0,
      lastRun: null,
      lastError: null,
      updatedAt: null,
    };
  }

  async ensure() {
    try {
      await mkdir(CACHE_DIR, { recursive: true });
    } catch {}
    try {
      await this.loadCache();
    } catch (e) {
      this.state.lastError = `cache unreadable: ${e?.message ?? e}`;
    }
    if (!this.cache) {
      try {
        await this.loadFallback();
      } catch (e) {
        this.state.lastError = `fallback unreadable: ${e?.message ?? e}`;
      }
    }
  }

  async loadCache() {
    const snap = JSON.parse(await readFile(join(CACHE_DIR, "snapshot.json"), "utf8"));
    const html = await readFile(join(CACHE_DIR, "cockpit.html"), "utf8");
    if (typeof html !== "string" || html.length < 1000) throw new Error("bad cockpit.html");
    this.cache = { html, ...snap };
    this.state.updatedAt = snap.generatedAt ?? null;
  }

  async loadFallback() {
    const snap = JSON.parse(await readFile(join(FALLBACK_DIR, "snapshot.json"), "utf8"));
    const html = await readFile(join(FALLBACK_DIR, "cockpit.html"), "utf8");
    this.cache = { html, ...snap, fallback: true };
    this.state.updatedAt = snap.generatedAt ?? null;
  }

  async refresh() {
    if (this.running) return { ok: false, error: "refresh already running" };
    this.running = true;
    try {
      await runPipeline();
      await this.loadCache();
      this.state.lastRun = Date.now();
      this.state.lastError = null;
      this.state.version += 1;
      return { ok: true, updatedAt: this.state.updatedAt };
    } catch (e) {
      this.state.lastError = String(e?.message ?? e);
      this.state.lastRun = Date.now();
      return { ok: false, error: this.state.lastError };
    } finally {
      this.running = false;
    }
  }

  getSnapshot() {
    if (!this.cache) return { ok: false, error: "no snapshot available" };
    return {
      ok: true,
      version: this.state.version,
      updatedAt: this.state.updatedAt,
      dsi: this.cache.dsi,
      anger: this.cache.anger,
      zone: this.cache.zone,
      fallback: !!this.cache.fallback,
      html: this.cache.html,
    };
  }

  status() {
    const config = this.getConfig();
    return {
      running: this.running,
      lastRun: this.state.lastRun,
      lastError: this.state.lastError,
      updatedAt: this.state.updatedAt,
      version: this.state.version,
      enabled: config.enabled,
      intervalMinutes: config.intervalMinutes,
      cacheDir: CACHE_DIR,
    };
  }
}

export default class CockpitGateway extends TypertRemoteService {
  static inject = ["settings", "timer"];

  constructor(ctx) {
    super(ctx, "cockpit");
    this.ctx = ctx;
    markRemote(this, "getSnapshot", "getSnapshot");
    markRemote(this, "refresh", "refresh");
    markRemote(this, "status", "status");

    // `settings.register()` returns an owner scope `{ get, watch, update }`,
    // not the resolved value — read the config through `scope.get()`.
    this.settings = ctx.settings.register(settingsNamespace(NS), Config);
    this.engine = new Engine(ctx, () => this.config);
    this.widget = null;
    void this.engine.ensure().then(() => {
      const tick = () => {
        if (this.config.enabled) void this.engine.refresh();
      };
      tick();
      this.ctx.setInterval(tick, Math.max(10, this.config.intervalMinutes) * 60 * 1000);
    });
    if (this.config.desktopEnabled) this.startWidget();
    ctx.effect(() => () => this.stopWidget(), "sentiment-cockpit: desktop widget cleanup");
  }

  get config() {
    return this.settings.get();
  }

  // ---- desktop widget ---------------------------------------------------

  resolveWidgetBinary() {
    if (existsSync(WIDGET_BIN)) {
      // GitHub web uploads and some archives drop the executable bit;
      // restore it so the widget can actually be spawned.
      try { chmodSync(WIDGET_BIN, 0o755); } catch {}
      return WIDGET_BIN;
    }
    // Fallback: compile the shipped source with the local Swift toolchain.
    try {
      const result = spawnSync("swiftc", ["-O", "-o", WIDGET_BIN, WIDGET_SRC], { timeout: 5 * 60 * 1000 });
      if (result.status === 0 && existsSync(WIDGET_BIN)) return WIDGET_BIN;
      void appendFile(join(CACHE_DIR, "widget.log"), `widget build failed: ${String(result.stderr).slice(0, 500)}\n`).catch(() => {});
    } catch (e) {
      void appendFile(join(CACHE_DIR, "widget.log"), `widget build error: ${e?.message ?? e}\n`).catch(() => {});
    }
    return null;
  }

  startWidget() {
    if (this.widget && this.widget.exitCode === null) return;
    const bin = this.resolveWidgetBinary();
    if (!bin) return;
    const cfg = this.config;
    const args = [
      CACHE_DIR,
      cfg.desktopMode === "floating" ? "floating" : "desktop",
      String(cfg.desktopX ?? -1),
      String(cfg.desktopY ?? -1),
      String(cfg.desktopScale ?? 1),
      String(process.pid),
      "0",
    ];
    let child;
    try {
      child = spawn(bin, args, { stdio: ["ignore", "ignore", "pipe"] });
    } catch (e) {
      void appendFile(join(CACHE_DIR, "widget.log"), `widget spawn failed: ${e?.message ?? e}\n`).catch(() => {});
      return;
    }
    this.widget = child;
    child.stderr.on("data", (d) => {
      void appendFile(join(CACHE_DIR, "widget.log"), String(d)).catch(() => {});
    });
    child.on("exit", () => {
      if (this.widget === child) this.widget = null;
    });
  }

  stopWidget() {
    const child = this.widget;
    this.widget = null;
    if (child && child.exitCode === null) child.kill();
  }

  getSnapshot() {
    return this.engine.getSnapshot();
  }

  refresh() {
    return this.engine.refresh();
  }

  status() {
    return {
      ...this.engine.status(),
      desktop: {
        enabled: this.config.desktopEnabled === true,
        mode: this.config.desktopMode ?? "desktop",
        running: !!this.widget && this.widget.exitCode === null,
      },
    };
  }
}

export { NS };
