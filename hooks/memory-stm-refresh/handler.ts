import { execSync, spawn } from "child_process";
import { readFileSync, writeFileSync, existsSync, statSync, openSync, appendFileSync } from "fs";
import { join } from "path";

const SCRIPT = "memory_consolidation.py";
const STATE_FILE = "/tmp/memory-stm-last-session.json";
const DEBUG_LOG = "/tmp/memory-hook-debug.log";

let dailyTimerSet = false;

function log(msg: string): void {
  try {
    appendFileSync(DEBUG_LOG, new Date().toISOString() + " " + msg + "\n");
  } catch {}
}

function getResetHour(): number {
  try {
    const cfgPath = join(process.env.HOME || "/root", ".openclaw", "openclaw.json");
    const cfg = JSON.parse(readFileSync(cfgPath, "utf-8"));
    return cfg?.session?.reset?.atHour ?? 4;
  } catch {
    return 4;
  }
}

function scheduleDailyRun(scriptPath: string, workspaceDir: string): void {
  if (dailyTimerSet) return;
  dailyTimerSet = true;

  const atHour = getResetHour();
  const randomOffsetMs = Math.floor(Math.random() * 30 * 60 * 1000); // 0-30 min before

  const target = new Date();
  target.setHours(atHour, 0, 0, 0);
  target.setTime(target.getTime() - randomOffsetMs);

  // If target already passed today, schedule for tomorrow
  if (target.getTime() <= Date.now()) {
    target.setDate(target.getDate() + 1);
  }

  const delayMs = target.getTime() - Date.now();
  const offsetMin = Math.round(randomOffsetMs / 60000);
  log(`timer set: ${target.toISOString()} (${Math.round(delayMs / 60000)}min, offset -${offsetMin}min)`);

  setTimeout(() => {
    dailyTimerSet = false; // allow re-scheduling
    log("timer fired: running compact + diary");

    // diary first → compact second (so compact's USER.md includes new diary)
    const cwd = join(workspaceDir, "memory_consolidation");
    try {
      const logFile = openSync("/tmp/memory-ltm-diary.log", "a");
      const d = spawn("python3", [scriptPath, "diary"], {
        cwd, stdio: ["ignore", logFile, logFile], detached: true
      });
      d.on("close", () => {
        log("diary done, starting compact");
        try {
          const c = spawn("python3", [scriptPath, "compact"], {
            cwd, stdio: ["ignore", logFile, logFile], detached: true
          });
          c.unref();
        } catch {}
      });
      d.unref();
    } catch (e) {
      log("spawn error: " + String(e));
    }

    // Re-schedule for tomorrow
    scheduleDailyRun(scriptPath, workspaceDir);
  }, delayMs);
}

const handler = async (event: any) => {
  const workspaceDir = event?.context?.workspaceDir;
  if (!workspaceDir) return;

  const scriptPath = join(workspaceDir, "memory_consolidation", SCRIPT);
  if (!existsSync(scriptPath)) return;

  // --- Schedule daily compact + diary (once per gateway lifetime) ---
  scheduleDailyRun(scriptPath, workspaceDir);

  // --- STM on session change ---
  const sessionsPath = join(
    process.env.HOME || "/root",
    ".openclaw", "agents", "main", "sessions", "sessions.json"
  );

  let currentSessionId = "";
  try {
    const store = JSON.parse(readFileSync(sessionsPath, "utf-8"));
    for (const [key, entry] of Object.entries(store)) {
      if (key.includes("cron:")) continue;
      const sid = (entry as any)?.sessionId;
      if (sid) currentSessionId = sid;
    }
  } catch { return; }

  let lastSessionId = "";
  try {
    const state = JSON.parse(readFileSync(STATE_FILE, "utf-8"));
    lastSessionId = state.sessionId || "";
  } catch {}

  if (currentSessionId === lastSessionId) return;

  const cwd = join(workspaceDir, "memory_consolidation");
  try {
    execSync(`python3 "${scriptPath}" stm`, { timeout: 10000, cwd, stdio: "ignore" });
  } catch {}

  writeFileSync(STATE_FILE, JSON.stringify({ sessionId: currentSessionId }));
};

export default handler;
