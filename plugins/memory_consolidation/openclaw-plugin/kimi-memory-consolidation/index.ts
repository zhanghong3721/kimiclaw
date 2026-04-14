/**
 * Memory Consolidation — OpenClaw Gateway Plugin
 *
 * Uses `api.on("message_received")` to detect new sessions.
 * On every inbound message, checks TWO conditions:
 *   1. Session is stale (daily reset / idle timeout)
 *   2. SessionId changed since last check (/reset, /new)
 * Either condition triggers: stm sync (blocking) + compact async.
 *
 * Covers ALL new session triggers: /reset, /new, daily, idle.
 * No fs.watch, no cron, no Pi extension.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { execSync, spawn } from "child_process";
import { readFileSync, existsSync } from "fs";
import * as path from "path";

const SCRIPT_NAME = "memory_consolidation.py";
const STM_TIMEOUT = 30_000;

function findScript(api: OpenClawPluginApi): string | null {
  const workspace = api.config?.agents?.defaults?.workspace ||
    path.join(process.env.HOME || "~", ".openclaw", "workspace");
  const candidate = path.join(workspace, "memory_consolidation", SCRIPT_NAME);
  return existsSync(candidate) ? candidate : null;
}

function getResetPolicy(api: OpenClawPluginApi): { atHour: number; idleMinutes: number | null } {
  const session = api.config?.session ?? {};
  const reset = (session as any).reset ?? {};
  return {
    atHour: reset.atHour ?? 4,
    idleMinutes: reset.idleMinutes ?? null,
  };
}

function getSessionStore(api: OpenClawPluginApi): Record<string, any> {
  const stateDir = process.env.OPENCLAW_STATE_DIR ||
    path.join(process.env.HOME || "~", ".openclaw");
  const storePath = path.join(stateDir, "agents", "main", "sessions", "sessions.json");
  try {
    return JSON.parse(readFileSync(storePath, "utf-8"));
  } catch {
    return {};
  }
}

function isSessionStale(updatedAt: number, policy: { atHour: number; idleMinutes: number | null }): boolean {
  const now = Date.now();

  // Daily reset check
  const resetToday = new Date();
  resetToday.setHours(policy.atHour, 0, 0, 0);
  if (resetToday.getTime() > now) {
    resetToday.setDate(resetToday.getDate() - 1);
  }
  if (updatedAt < resetToday.getTime()) return true;

  // Idle reset check
  if (policy.idleMinutes != null) {
    const idleMs = policy.idleMinutes * 60_000;
    if (now > updatedAt + idleMs) return true;
  }

  return false;
}

function runStm(scriptPath: string, logger: OpenClawPluginApi["logger"]): boolean {
  try {
    const result = execSync(`python3 "${scriptPath}" stm`, {
      timeout: STM_TIMEOUT,
      encoding: "utf-8",
      stdio: ["ignore", "pipe", "pipe"],
      cwd: path.dirname(scriptPath),
    });
    const summary = result.trim().split("\n").pop() || "done";
    logger.info(`stm done: ${summary}`);
    return true;
  } catch (err: any) {
    logger.warn(`stm failed: ${(err.message || "").slice(0, 200)}`);
    return false;
  }
}

function runCompactAsync(scriptPath: string, logger: OpenClawPluginApi["logger"]): void {
  const child = spawn("python3", [scriptPath, "compact"], {
    cwd: path.dirname(scriptPath),
    stdio: "ignore",
    detached: true,
  });
  child.unref();
  logger.info("compact launched async");
}

export default function memoryConsolidation(api: OpenClawPluginApi) {
  const scriptPath = findScript(api);
  if (!scriptPath) {
    api.logger.warn("memory_consolidation.py not found, plugin disabled");
    return;
  }

  const policy = getResetPolicy(api);
  api.logger.info(`script: ${scriptPath}, reset: atHour=${policy.atHour} idle=${policy.idleMinutes ?? "off"}`);

  // Track known sessionIds and refresh state per session key
  const knownSessions = new Map<string, string>();   // key → sessionId
  const refreshed = new Map<string, number>();        // key → refreshedAt

  // Cold-start: seed knownSessions from current sessions.json
  // so the first /reset after gateway restart is detected
  const initialStore = getSessionStore(api);
  for (const [key, entry] of Object.entries(initialStore)) {
    const sid = (entry as any)?.sessionId;
    if (sid) knownSessions.set(key, sid);
  }
  api.logger.info(`seeded ${knownSessions.size} session baselines`);

  api.on("message_received", (event, _ctx) => {
    const store = getSessionStore(api);

    // Scan all sessions, collect reasons to trigger
    let needsRefresh = false;
    let hasStale = false;
    const reasons: string[] = [];

    for (const [key, entry] of Object.entries(store)) {
      if (key.includes("cron:")) continue;
      const updatedAt = (entry as any)?.updatedAt;
      const sessionId = (entry as any)?.sessionId;
      if (!updatedAt) continue;

      // Check 1: sessionId changed (/reset, /new)
      const prevSessionId = knownSessions.get(key);
      const sessionChanged = prevSessionId != null && sessionId != null && sessionId !== prevSessionId;

      // Check 2: session is stale (daily reset / idle timeout)
      const stale = isSessionStale(updatedAt, policy);
      const lastRefresh = refreshed.get(key) ?? 0;
      const staleUnrefreshed = stale && lastRefresh <= updatedAt;

      if (sessionChanged || staleUnrefreshed) {
        needsRefresh = true;
        if (staleUnrefreshed) hasStale = true;
        const reason = sessionChanged
          ? `changed: ${prevSessionId?.slice(0, 8)}→${sessionId?.slice(0, 8)}`
          : "stale";
        reasons.push(`${key.split(":").slice(-1)[0]}(${reason})`);
        refreshed.set(key, Date.now());
      }

      // Always update known sessionId (after check, not before)
      if (sessionId) knownSessions.set(key, sessionId);
    }

    if (!needsRefresh) return;

    // STM is global — run once regardless of how many sessions triggered
    api.logger.info(`triggers: ${reasons.join(", ")}, running stm sync...`);
    const ok = runStm(scriptPath, api.logger);

    // Only run compact on stale sessions (daily/idle, ~once/day).
    // /reset and /new only need STM (frequent, no need to re-distill LTM).
    if (ok && hasStale) {
      runCompactAsync(scriptPath, api.logger);
    }
  });
}
