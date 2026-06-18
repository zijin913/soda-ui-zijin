import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

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

  // Teleop overlay state — pushed by /ws/teleop_ui (backend TeleopBridge),
  // populated/cleared automatically when teleopRunning flips.
  const teleopStatus = ref<string>('')         // e.g. "READY", "RECORDING", "ASK_RECORD"
  const teleopConnected = ref<boolean>(false)  // bridge ↔ teleop_quest socket up
  const teleopClosed = ref<boolean>(false)     // bridge saw socket close (session ended)
  const teleopOverlayDismissed = ref<boolean>(false)

  // ── Camera calibration (backend /calibration/*) ─────────────────────
  // calibrationOpen drives the CalibrationModal mounted at App.vue root.
  // calibStatus mirrors GET /calibration/status?target= for the selected
  // target (phase / board_detected / samples_collected / metrics / ...).
  const calibrationOpen = ref<boolean>(false)
  // Like teleopOverlayDismissed: hide the modal but keep the session (and its
  // polling) alive; a banner re-opens it. The CalibrationModal component stays
  // mounted at App root regardless, so polling survives a dismiss.
  const calibrationDismissed = ref<boolean>(false)
  const calibTarget = ref<'left' | 'right' | 'side'>('left')
  const calibStatus = ref<Record<string, any>>({ phase: 'idle' })
  const calibActive = computed(() =>
    ['positioning', 'collecting', 'solving'].includes(calibStatus.value?.phase),
  )

  // ── host policy ─────────────────────────────────────────────────────
  // hostPolicyOpen drives the HostPolicyModal mounted at App root. policyStatus
  // mirrors GET /policy/status (also pushed over /ws/policy). policyList comes
  // from GET /policy/list (the registry: dropdown + per-policy defaults).
  const hostPolicyOpen = ref<boolean>(false)
  const hostPolicyDismissed = ref<boolean>(false)
  const policyList = ref<Record<string, any>[]>([])
  const policyStatus = ref<Record<string, any>>({ phase: 'idle' })
  const policyActive = computed(() =>
    ['connecting', 'homing', 'probe', 'running'].includes(policyStatus.value?.phase),
  )

  // RecoveryModal "DISMISS OVERLAY" toggle. When true the fullscreen modal is
  // hidden but the slim ZeroGravityBanner stays visible and can re-open the
  // modal by flipping this back to false.
  const recoveryModalDismissed = ref<boolean>(false)

  // Transient flags driving RecoveryModal's STARTING and FINISHING phases.
  // recoveryStarting goes true the instant the user confirms a stop and clears
  // either when zeroGravityActive flips true or after a safety timeout.
  // recoveryFinishing goes true when the user hits DONE and clears when
  // zeroGravityActive flips false.
  const recoveryStarting = ref<boolean>(false)
  const recoveryFinishing = ref<boolean>(false)
  let recoveryStartingTimer: number | null = null

  // Global modal mount state. We mount the modal at App.vue root so it sits in
  // the same stacking context as LauncherCard (which has its own overlay) —
  // z-index alone isn't enough when modals were nested inside TopBar (whose
  // own stacking context capped them below LauncherCard's z-index: 200).
  // Components anywhere call openStopConfirm. (The old hold-to-confirm PANIC
  // modal is gone — emergency stop is now a single-click instant estop().)
  const stopConfirmOpen = ref<boolean>(false)
  function openStopConfirm() { stopConfirmOpen.value = true }
  function closeStopConfirm() { stopConfirmOpen.value = false }

  // ── teach / programming mode ──────────────────────────────────────
  // PROGRAMMING floats both arms (in-process gravity-comp freedrive, no zero-g
  // launcher); EXECUTION holds pose and resumes normal control.
  const teachActive = ref<boolean>(false)
  const teachConfirmOpen = ref<boolean>(false)

  async function pollTeachOnce(): Promise<void> {
    if (backend.value !== 'up') { teachActive.value = false; return }
    try {
      const r = await fetch(`${backendUrl.value}/api/teach/status`, { cache: 'no-store' })
      if (!r.ok) return
      const s = await r.json()
      teachActive.value = !!s.teach_active
    } catch { /* ignore */ }
  }

  // Click PROGRAMMING: confirm first on real hardware (arms go compliant and
  // may sag); float immediately in sim.
  function requestTeach(): void {
    if (mode.value === 'real') teachConfirmOpen.value = true
    else void enterTeach()
  }
  function cancelTeach(): void { teachConfirmOpen.value = false }
  async function confirmTeach(): Promise<void> {
    teachConfirmOpen.value = false
    await enterTeach()
  }

  async function enterTeach(): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/api/teach/enter`, { method: 'POST' })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        lastError.value = data?.error || `Enter teach failed (HTTP ${r.status})`
        return { ok: false, error: lastError.value }
      }
      teachActive.value = true
      return { ok: true }
    } catch (e: any) {
      lastError.value = `Enter teach failed: ${String(e?.message || e)}`
      return { ok: false, error: lastError.value }
    }
  }
  async function exitTeach(): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/api/teach/exit`, { method: 'POST' })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        lastError.value = data?.error || `Exit teach failed (HTTP ${r.status})`
        return { ok: false, error: lastError.value }
      }
      teachActive.value = false
      return { ok: true }
    } catch (e: any) {
      lastError.value = `Exit teach failed: ${String(e?.message || e)}`
      return { ok: false, error: lastError.value }
    }
  }

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
      void pollTeleopOnce(); void pollTeachOnce()
      teleopTimer = window.setInterval(() => { void pollTeleopOnce(); void pollTeachOnce() }, 2000)
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
      setTeleopRunning(false)
      teleopPid.value = null
      return
    }
    try {
      const r = await fetch(`${backendUrl.value}/api/teleop/status`, { cache: 'no-store' })
      if (!r.ok) throw new Error()
      const t = await r.json()
      setTeleopRunning(!!t.running)
      teleopPid.value = t.pid ?? null
    } catch {
      setTeleopRunning(false)
      teleopPid.value = null
    }
  }

  // Centralized teleopRunning setter so we can detect the false→true edge
  // (= "new session begins") and clear the stale flags from the previous
  // session in one place. Without this the overlay would never re-show on
  // the second teleop (teleopClosed stayed true from the first session).
  function setTeleopRunning(running: boolean) {
    const wasRunning = teleopRunning.value
    teleopRunning.value = running
    if (running && !wasRunning) {
      teleopClosed.value = false
      teleopConnected.value = false
      teleopStatus.value = ''
      teleopOverlayDismissed.value = false
    }
  }

  // ── calibration ─────────────────────────────────────────────────────
  function openCalibration() { calibrationOpen.value = true; calibrationDismissed.value = false }
  function closeCalibration() { calibrationOpen.value = false; calibrationDismissed.value = false }
  function dismissCalibration() { calibrationDismissed.value = true }
  function reopenCalibration() { calibrationDismissed.value = false }

  // Backend gone (e.g. E-STOP SIGKILLed soda_os.main — and with it the
  // in-process calibration threads). Tear the calibration UI down so it doesn't
  // falsely show a session still running and keep teleop locked out. Driven by a
  // watcher on `backend` so it fires regardless of whether the modal's poll
  // timer is active. (Mirrors how pollTeleopOnce clears teleopRunning.)
  function resetCalibrationUi(): void {
    calibStatus.value = { phase: 'idle' }
    calibrationOpen.value = false
    calibrationDismissed.value = false
  }
  watch(backend, (b) => {
    if (b !== 'up' && (calibrationOpen.value || calibActive.value)) resetCalibrationUi()
  })

  async function pollCalibrationOnce(): Promise<void> {
    if (backend.value !== 'up') return
    try {
      const r = await fetch(
        `${backendUrl.value}/calibration/status?target=${calibTarget.value}`,
        { cache: 'no-store' },
      )
      if (!r.ok) throw new Error()
      calibStatus.value = await r.json()
    } catch {
      /* keep last known status on a transient miss */
    }
  }

  let calibTimer: number | null = null
  function startCalibPolling(): void {
    if (calibTimer !== null) return
    void pollCalibrationOnce()
    calibTimer = window.setInterval(pollCalibrationOnce, 1000)
  }
  function stopCalibPolling(): void {
    if (calibTimer !== null) window.clearInterval(calibTimer)
    calibTimer = null
  }

  async function _calibPost(
    path: string, body: Record<string, any>,
  ): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) return { ok: false, error: data?.detail || `HTTP ${r.status}` }
      calibStatus.value = data
      return { ok: true }
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) }
    }
  }

  async function startCalibration(target: 'left' | 'right' | 'side') {
    calibTarget.value = target
    const r = await _calibPost('/calibration/start', { target })
    void pollCalibrationOnce()
    return r
  }
  async function confirmCalibPosition() {
    return _calibPost('/calibration/confirm_position', { target: calibTarget.value })
  }
  async function cancelCalibration() {
    return _calibPost('/calibration/cancel', { target: calibTarget.value })
  }

  // ── host policy ─────────────────────────────────────────────────────
  function openHostPolicy() { hostPolicyOpen.value = true; hostPolicyDismissed.value = false }
  function closeHostPolicy() { hostPolicyOpen.value = false; hostPolicyDismissed.value = false }
  function dismissHostPolicy() { hostPolicyDismissed.value = true }
  function reopenHostPolicy() { hostPolicyDismissed.value = false }

  function resetHostPolicyUi(): void {
    policyStatus.value = { phase: 'idle' }
    hostPolicyOpen.value = false
    hostPolicyDismissed.value = false
    closePolicyWs()
  }
  watch(backend, (b) => {
    if (b !== 'up' && (hostPolicyOpen.value || policyActive.value)) resetHostPolicyUi()
  })

  async function fetchPolicyList(): Promise<void> {
    if (backend.value !== 'up') return
    try {
      const r = await fetch(`${backendUrl.value}/policy/list`, { cache: 'no-store' })
      if (!r.ok) throw new Error()
      const data = await r.json()
      policyList.value = data?.policies || []
    } catch { /* keep last list */ }
  }

  async function pollPolicyOnce(): Promise<void> {
    if (backend.value !== 'up') return
    try {
      const r = await fetch(`${backendUrl.value}/policy/status`, { cache: 'no-store' })
      if (!r.ok) throw new Error()
      policyStatus.value = await r.json()
    } catch { /* keep last known status */ }
  }

  let policyTimer: number | null = null
  function startPolicyPolling(): void {
    if (policyTimer !== null) return
    void pollPolicyOnce()
    policyTimer = window.setInterval(pollPolicyOnce, 1000)
  }
  function stopPolicyPolling(): void {
    if (policyTimer !== null) window.clearInterval(policyTimer)
    policyTimer = null
  }

  async function _policyPost(
    path: string, body: Record<string, any> = {},
  ): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) return { ok: false, error: data?.detail || `HTTP ${r.status}` }
      policyStatus.value = data
      return { ok: true }
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) }
    }
  }

  async function startPolicy(body: Record<string, any>) {
    const r = await _policyPost('/policy/start', body)
    void pollPolicyOnce()
    return r
  }

  // Add/edit a USER policy (persisted server-side; no source access needed).
  async function savePolicy(entry: Record<string, any>): Promise<{ ok: boolean; error?: string; id?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/policy/registry`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(entry),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) return { ok: false, error: data?.detail || `HTTP ${r.status}` }
      if (data.policies) policyList.value = data.policies
      return { ok: true, id: data?.saved?.id }
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) }
    }
  }
  async function deletePolicy(id: string): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/policy/registry/${encodeURIComponent(id)}`, { method: 'DELETE' })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) return { ok: false, error: data?.detail || `HTTP ${r.status}` }
      if (data.policies) policyList.value = data.policies
      return { ok: true }
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) }
    }
  }
  async function stopPolicy() {
    return _policyPost('/policy/stop', {})
  }
  // Live-update soft tuning knobs (speed/smoothness/latch) during a rollout.
  async function updatePolicyParams(overrides: Record<string, any>) {
    return _policyPost('/policy/params', { overrides })
  }

  // /ws/policy — read-only status push (mirrors the teleop_ui ws).
  let policyWs: WebSocket | null = null
  let policyWsReconnectTimer: number | null = null
  function openPolicyWs(): void {
    if (policyWs && (policyWs.readyState === WebSocket.OPEN ||
                      policyWs.readyState === WebSocket.CONNECTING)) return
    const url = wsUrl.value.replace(/\/ws$/, '/ws/policy')
    try {
      policyWs = new WebSocket(url)
    } catch {
      policyWs = null
      return
    }
    policyWs.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.type === 'status') policyStatus.value = d
      } catch { /* ignore parse errors */ }
    }
    policyWs.onclose = () => {
      policyWs = null
      if (policyActive.value && !policyWsReconnectTimer) {
        policyWsReconnectTimer = window.setTimeout(() => {
          policyWsReconnectTimer = null
          if (policyActive.value) openPolicyWs()
        }, 800)
      }
    }
    policyWs.onerror = () => { /* let onclose handle reconnect */ }
  }
  function closePolicyWs(): void {
    if (policyWsReconnectTimer) { window.clearTimeout(policyWsReconnectTimer); policyWsReconnectTimer = null }
    if (policyWs) { try { policyWs.close() } catch { /* noop */ } policyWs = null }
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

  // Called by StopConfirmModal's CONFIRM event. Closes the modal, kicks off
  // RecoveryModal's STARTING phase (real mode only), then calls launcher /stop.
  async function confirmStop(): Promise<void> {
    closeStopConfirm()
    const isReal = mode.value === 'real'
    if (isReal) beginRecoveryStarting()
    const r = await stop()
    if (!r.ok) {
      lastError.value = `Stop failed: ${r.error}`
      endRecoveryStarting()
    }
  }

  // Mark that we just kicked off a stop so RecoveryModal can render its
  // STARTING phase (boot-log animation) until zero-gravity actually comes up.
  // Safety timeout: clear after 30s so we don't get stuck if zero-g fails.
  function beginRecoveryStarting(): void {
    recoveryStarting.value = true
    if (recoveryStartingTimer !== null) window.clearTimeout(recoveryStartingTimer)
    recoveryStartingTimer = window.setTimeout(() => {
      recoveryStarting.value = false
      recoveryStartingTimer = null
    }, 30_000)
  }
  function endRecoveryStarting(): void {
    recoveryStarting.value = false
    if (recoveryStartingTimer !== null) {
      window.clearTimeout(recoveryStartingTimer)
      recoveryStartingTimer = null
    }
  }

  // Called by RecoveryModal's "DONE" button. Kills zero-gravity launcher +
  // servers, returns the launcher to the idle state (LauncherCard reappears).
  async function finishRecovery(): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/recovery/finish`, {
        method: 'POST',
      })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      void pollOnce()
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // ── teleop key + WS ─────────────────────────────────────────────
  async function sendTeleopKey(key: string): Promise<{ ok: boolean; error?: string }> {
    if (!key || key.length === 0) return { ok: false, error: 'empty key' }
    try {
      const r = await fetch(`${backendUrl.value}/api/teleop/key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key[0] }),
      })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // Set the per-session task instruction on teleop_quest. The next save
  // (S key) consumes it for instruction.txt / info.json / HDF5 attrs. Sending
  // again before the next save just overwrites — perfect for batch collection
  // where N episodes share one task.
  async function sendTeleopInstruction(text: string): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/api/teleop/instruction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text ?? '' }),
      })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // Graceful teleop shutdown — what the original teleop_viewer.py did on 'q':
  // POST /api/teleop/stop so the backend SIGINTs teleop_quest (saves any
  // in-progress episode), closes the bridge, and clears all state. Sending a
  // raw 'q' key to teleop_quest also exits it, but bypasses bridge cleanup.
  async function stopTeleop(): Promise<{ ok: boolean; error?: string }> {
    try {
      const r = await fetch(`${backendUrl.value}/api/teleop/stop`, { method: 'POST' })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // Move both arms to home pose. Active state pinging at ~3 Hz lets the UI
  // disable the button + show "HOMING…" while the backend trajectory runs.
  const homing = ref<boolean>(false)
  async function goHome(): Promise<{ ok: boolean; error?: string }> {
    if (homing.value) return { ok: false, error: 'already homing' }
    homing.value = true
    try {
      // During teleop the command stream owns the shared ZMQ client; calling
      // /robot/home directly would race teleop's setpoint. Route through the
      // teleop_quest 'h' key instead — it clears the pending target, calls
      // /robot/home internally, then resets the controllers.
      if (teleopRunning.value) {
        const r = await sendTeleopKey('h')
        return r
      }
      const r = await fetch(`${backendUrl.value}/robot/home`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      const data = await r.json().catch(() => ({}))
      if (data && data.success === false) {
        return { ok: false, error: data.message || 'home failed' }
      }
      return { ok: true }
    } catch (e) {
      return { ok: false, error: String(e) }
    } finally {
      homing.value = false
    }
  }

  // /ws/teleop_ui client. Backend pushes:
  //   {type:"snapshot"|"status"|"connected"|"closed"|"error", ...}
  let teleopWs: WebSocket | null = null
  let teleopWsReconnectTimer: number | null = null
  function openTeleopWs(): void {
    if (teleopWs && (teleopWs.readyState === WebSocket.OPEN ||
                      teleopWs.readyState === WebSocket.CONNECTING)) return
    const url = wsUrl.value.replace(/\/ws$/, '/ws/teleop_ui')
    try {
      teleopWs = new WebSocket(url)
    } catch {
      teleopWs = null
      return
    }
    teleopWs.onopen = () => {
      // NOTE: don't reset teleopClosed here. Whether the current session is
      // truly closed is owned by the bridge's snapshot / closed messages —
      // an auto-reconnect after the session ended would otherwise blip the
      // overlay back into a "CONNECTING…" state for ~800 ms before the next
      // /api/teleop/status poll catches up.
    }
    teleopWs.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data)
        if (d.type === 'snapshot') {
          teleopStatus.value = d.status ?? ''
          teleopConnected.value = !!d.connected
          teleopClosed.value = !!d.closed
        } else if (d.type === 'status') {
          teleopStatus.value = d.status ?? ''
        } else if (d.type === 'connected') {
          teleopConnected.value = true
        } else if (d.type === 'closed') {
          teleopClosed.value = true
          teleopConnected.value = false
        } else if (d.type === 'error') {
          lastError.value = `Teleop bridge: ${d.message}`
        }
      } catch { /* ignore parse errors */ }
    }
    teleopWs.onclose = () => {
      teleopWs = null
      // Auto-reconnect only while teleop is still flagged running AND the
      // bridge hasn't told us the session is over. Otherwise we'd race the
      // /api/teleop/status poll (which takes up to 2 s to flip teleopRunning
      // to false) and briefly re-open the overlay in CONNECTING state.
      if (teleopRunning.value && !teleopClosed.value && !teleopWsReconnectTimer) {
        teleopWsReconnectTimer = window.setTimeout(() => {
          teleopWsReconnectTimer = null
          if (teleopRunning.value && !teleopClosed.value) openTeleopWs()
        }, 800)
      }
    }
    teleopWs.onerror = () => { /* let onclose handle reconnect */ }
  }
  function closeTeleopWs(): void {
    if (teleopWsReconnectTimer) {
      window.clearTimeout(teleopWsReconnectTimer)
      teleopWsReconnectTimer = null
    }
    if (teleopWs) {
      try { teleopWs.close() } catch { /* */ }
      teleopWs = null
    }
    teleopStatus.value = ''
    teleopConnected.value = false
    teleopClosed.value = false
    teleopOverlayDismissed.value = false
  }

  // Emergency stop: single-click, instant SIGKILL of the whole stack (except
  // this launcher). Called by the EmergencyStop button and the LauncherCard's
  // STOP. No confirmation, no grace period — the launcher stays alive so the
  // UI keeps polling and the operator returns to the LauncherCard to relaunch.
  async function estop(): Promise<{ ok: boolean; error?: string; killed?: number }> {
    try {
      const r = await fetch(`${launcherUrl.value}/launcher/estop`, {
        method: 'POST',
      })
      if (!r.ok) return { ok: false, error: `HTTP ${r.status}` }
      const data = await r.json().catch(() => ({}))
      void pollOnce()
      return { ok: true, killed: data.killed }
    } catch (e) {
      return { ok: false, error: String(e) }
    }
  }

  // ── log tail (used by LauncherCard while open) ─────────────────────
  const hwLogs = ref<string[]>([])
  const backendLogs = ref<string[]>([])
  // Per-feature streams (teleop / policy / calib), served by the backend's
  // /api/logs/feature. Only polled while the backend is up; the LogPanel shows
  // a tagged tab per feature, visible only while that feature is active.
  const featureLogs = ref<{ teleop: string[]; policy: string[]; calib: string[] }>(
    { teleop: [], policy: [], calib: [] },
  )

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

  async function fetchFeatureLogs(n = 200): Promise<void> {
    if (backend.value !== 'up') return
    try {
      const r = await fetch(
        `${backendUrl.value}/api/logs/feature?n=${n}`,
        { cache: 'no-store' },
      )
      if (!r.ok) return
      const body = await r.json()
      featureLogs.value = {
        teleop: body.teleop ?? [],
        policy: body.policy ?? [],
        calib: body.calib ?? [],
      }
    } catch {
      /* backend may be down — ignore */
    }
  }

  function startLogTail(intervalMs = 2000): void {
    if (logTimer !== null) return
    void fetchLogs('hw')
    void fetchLogs('backend')
    void fetchFeatureLogs()
    logTimer = window.setInterval(() => {
      void fetchLogs('hw')
      void fetchLogs('backend')
      void fetchFeatureLogs()
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
    teleopStatus, teleopConnected, teleopClosed, teleopOverlayDismissed,
    calibrationOpen, calibrationDismissed, calibTarget, calibStatus, calibActive,
    hostPolicyOpen, hostPolicyDismissed, policyList, policyStatus, policyActive,
    homing,
    recoveryModalDismissed, recoveryStarting, recoveryFinishing,
    stopConfirmOpen,
    teachActive, teachConfirmOpen,
    hwLogs, backendLogs, featureLogs,
    // urls
    launcherUrl, backendUrl, wsUrl,
    isOperational,
    // actions
    startPolling, stopPolling, pollOnce, pollMetricsOnce, pollTeleopOnce,
    launch, stop, finishRecovery, estop,
    openStopConfirm, closeStopConfirm,
    confirmStop,
    requestTeach, cancelTeach, confirmTeach, enterTeach, exitTeach, pollTeachOnce,
    beginRecoveryStarting, endRecoveryStarting,
    sendTeleopKey, sendTeleopInstruction, stopTeleop, goHome, openTeleopWs, closeTeleopWs,
    openCalibration, closeCalibration, dismissCalibration, reopenCalibration,
    startCalibPolling, stopCalibPolling,
    pollCalibrationOnce, startCalibration, confirmCalibPosition, cancelCalibration,
    openHostPolicy, closeHostPolicy, dismissHostPolicy, reopenHostPolicy,
    fetchPolicyList, pollPolicyOnce, startPolicyPolling, stopPolicyPolling,
    startPolicy, stopPolicy, updatePolicyParams, savePolicy, deletePolicy, openPolicyWs, closePolicyWs,
    startLogTail, stopLogTail, fetchLogs, fetchFeatureLogs,
    tickWsFrame, setWsConnected, setWsLatency,
  }
})
