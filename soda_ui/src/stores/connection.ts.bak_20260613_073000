import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// State of the launcher + backend + WS connection. The UI reads from here
// to decide what to render (LauncherCard overlay vs. operational mode) and
// what to enable (mode buttons gated on backend === 'up').
//
// URL strategy: defaults use the page's own hostname so the UI works whether
// it's served by the launcher (same-origin :8079) or by `npm run dev` (vite
// on :5173). Override with VITE_LAUNCHER_URL / VITE_BACKEND_URL / VITE_WS_URL
// in `.env` if the backend/launcher live on a different host.

export type LauncherState = 'checking' | 'up' | 'down'
export type BackendState = 'down' | 'starting' | 'up' | 'stopping' | 'unknown'
export type HwState = 'down' | 'starting' | 'up'
export type Mode = 'sim' | 'real' | null

export interface LauncherStatus {
  launcher: 'up'
  backend: BackendState
  hw: HwState
  mode: Mode
  hw_pid: number | null
  backend_pid: number | null
  uptime_s: number
  zero_gravity_active: boolean
  last_event: string
  last_error: string | null
}

const env = import.meta.env

function defaultLauncherUrl(): string {
  if (env.VITE_LAUNCHER_URL) return env.VITE_LAUNCHER_URL as string
  return `${location.protocol}//${location.hostname || 'localhost'}:8079`
}
function defaultBackendUrl(): string {
  if (env.VITE_BACKEND_URL) return env.VITE_BACKEND_URL as string
  return `${location.protocol}//${location.hostname || 'localhost'}:8080`
}
function defaultWsUrl(): string {
  if (env.VITE_WS_URL) return env.VITE_WS_URL as string
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.hostname || 'localhost'}:8080/ws`
}

export const useConnectionStore = defineStore('connection', () => {
  // Reactive state
  const launcher = ref<LauncherState>('checking')
  const backend = ref<BackendState>('down')
  const hw = ref<HwState>('down')
  const mode = ref<Mode>(null)
  const hwPid = ref<number | null>(null)
  const backendPid = ref<number | null>(null)
  const uptimeS = ref<number>(0)
  const zeroGravityActive = ref<boolean>(false)
  const lastEvent = ref<string>('—')
  const lastError = ref<string | null>(null)

  const wsConnected = ref<boolean>(false)
  const wsFps = ref<number>(0)
  const wsLatencyMs = ref<number | null>(null)

  // Host metrics (from /launcher/metrics)
  const cpuPct = ref<number | null>(null)
  const ramPct = ref<number | null>(null)
  const backendRssMb = ref<number | null>(null)
  const hwRssMb = ref<number | null>(null)

  // Teleop running state (from backend /api/teleop/status)
  const teleopRunning = ref<boolean>(false)
  const teleopPid = ref<number | null>(null)

  const launcherUrl = computed(defaultLauncherUrl)
  const backendUrl = computed(defaultBackendUrl)
  const wsUrl = computed(defaultWsUrl)
  const isOperational = computed(
    () => launcher.value === 'up' && backend.value === 'up' && wsConnected.value,
  )

  // ── polling ────────────────────────────────────────────────────────
  let pollTimer: number | null = null
  let metricsTimer: number | null = null
  let teleopTimer: number | null = null
  let logTimer: number | null = null
  let frameTimes: number[] = []

  async function pollOnce(): Promise<void> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/status`, { cache: 'no-store' })
      if (!r.ok) throw new Error(`status ${r.status}`)
      const s = (await r.json()) as LauncherStatus
      launcher.value = 'up'
      backend.value = s.backend
      hw.value = s.hw
      mode.value = s.mode
      hwPid.value = s.hw_pid
      backendPid.value = s.backend_pid
      uptimeS.value = s.uptime_s
      zeroGravityActive.value = s.zero_gravity_active
      lastEvent.value = s.last_event
      lastError.value = s.last_error
    } catch {
      launcher.value = 'down'
      backend.value = 'unknown'
      hw.value = 'down'
      mode.value = null
    }
  }

  function startPolling(intervalMs = 1000): void {
    if (pollTimer !== null) return
    void pollOnce()
    pollTimer = window.setInterval(pollOnce, intervalMs)
    // Companion pollers — lighter cadence since these change slowly.
    if (metricsTimer === null) {
      void pollMetricsOnce()
      metricsTimer = window.setInterval(pollMetricsOnce, 3000)
    }
    if (teleopTimer === null) {
      void pollTeleopOnce()
      teleopTimer = window.setInterval(pollTeleopOnce, 2000)
    }
  }

  function stopPolling(): void {
    for (const t of [pollTimer, metricsTimer, teleopTimer]) {
      if (t !== null) window.clearInterval(t)
    }
    pollTimer = metricsTimer = teleopTimer = null
  }

  async function pollMetricsOnce(): Promise<void> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/metrics`, { cache: 'no-store' })
      if (!r.ok) throw new Error()
      const m = await r.json()
      cpuPct.value = m.cpu_pct ?? null
      ramPct.value = m.ram_pct ?? null
      backendRssMb.value = m.backend_rss_mb ?? null
      hwRssMb.value = m.hw_rss_mb ?? null
    } catch {
      cpuPct.value = ramPct.value = backendRssMb.value = hwRssMb.value = null
    }
  }

  async function pollTeleopOnce(): Promise<void> {
    if (backend.value !== 'up') {
      teleopRunning.value = false
      teleopPid.value = null
      return
    }
    try {
      const r = await fetch(`${backendUrl.value}/api/teleop/status`, { cache: 'no-store' })
      if (!r.ok) throw new Error()
      const t = await r.json()
      teleopRunning.value = !!t.running
      teleopPid.value = t.pid ?? null
    } catch {
      teleopRunning.value = false
      teleopPid.value = null
    }
  }

  // ── actions ────────────────────────────────────────────────────────
  async function launch(targetMode: 'sim' | 'real'): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: targetMode }),
      })
      const body = await r.json()
      if (!r.ok || body.status === 'error') {
        return { ok: false, error: body.error ?? `HTTP ${r.status}` }
      }
      void pollOnce()
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  async function stop(): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/stop`, { method: 'POST' })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      void pollOnce()
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // ── log tail (used by LauncherCard while open) ─────────────────────
  const hwLogs = ref<string[]>([])
  const backendLogs = ref<string[]>([])

  async function fetchLogs(stream: 'hw' | 'backend', n = 50): Promise<void> {
    try {
      const r = await fetch(
        `${launcherUrl.value}/launcher/logs?stream=${stream}&n=${n}`,
        { cache: 'no-store' },
      )
      if (!r.ok) return
      const body = await r.json()
      if (stream === 'hw') hwLogs.value = body.lines ?? []
      else backendLogs.value = body.lines ?? []
    } catch {
      /* launcher may be down — ignore */
    }
  }

  function startLogTail(intervalMs = 2000): void {
    if (logTimer !== null) return
    void fetchLogs('hw')
    void fetchLogs('backend')
    logTimer = window.setInterval(() => {
      void fetchLogs('hw')
      void fetchLogs('backend')
    }, intervalMs)
  }

  function stopLogTail(): void {
    if (logTimer !== null) {
      window.clearInterval(logTimer)
      logTimer = null
    }
  }

  // ── WS helpers (called from App.vue's WebSocket handlers) ──────────
  function tickWsFrame(): void {
    const now = performance.now()
    frameTimes.push(now)
    while (frameTimes.length > 0 && now - (frameTimes[0] ?? 0) > 1000) {
      frameTimes.shift()
    }
    wsFps.value = frameTimes.length
  }

  function setWsConnected(v: boolean): void {
    wsConnected.value = v
    if (!v) {
      wsFps.value = 0
      frameTimes = []
      wsLatencyMs.value = null
    }
  }

  function setWsLatency(ms: number | null): void {
    wsLatencyMs.value = ms
  }

  return {
    // state
    launcher, backend, hw, mode, hwPid, backendPid, uptimeS,
    zeroGravityActive, lastEvent, lastError,
    wsConnected, wsFps, wsLatencyMs,
    cpuPct, ramPct, backendRssMb, hwRssMb,
    teleopRunning, teleopPid,
    hwLogs, backendLogs,
    // urls
    launcherUrl, backendUrl, wsUrl,
    isOperational,
    // actions
    startPolling, stopPolling, pollOnce, pollMetricsOnce, pollTeleopOnce,
    launch, stop,
    startLogTail, stopLogTail, fetchLogs,
    tickWsFrame, setWsConnected, setWsLatency,
  }
})
