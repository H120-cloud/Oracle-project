/**
 * Alert Sound Generator — Web Audio API synthesized sounds.
 * No external audio files needed. Each alert type has a distinct tone.
 *
 * Sound types:
 *  - dip:     Descending tone (warning, stock dipping)
 *  - bullish: Ascending triumphant chord (bounce confirmed / going up)
 *  - bearish: Low ominous pulse (bearish shift)
 *  - volume:  Quick double-tap (volume surge)
 *  - default: Simple notification ping
 */

let audioCtx = null

function getCtx() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)()
  }
  // Resume if suspended (browser autoplay policy)
  if (audioCtx.state === 'suspended') {
    audioCtx.resume()
  }
  return audioCtx
}

function playTone(freq, duration, type = 'sine', gainVal = 0.3, delay = 0) {
  const ctx = getCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()

  osc.type = type
  osc.frequency.setValueAtTime(freq, ctx.currentTime + delay)
  gain.gain.setValueAtTime(gainVal, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + duration)

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.start(ctx.currentTime + delay)
  osc.stop(ctx.currentTime + delay + duration)
}

function playFreqRamp(startFreq, endFreq, duration, type = 'sine', gainVal = 0.3, delay = 0) {
  const ctx = getCtx()
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()

  osc.type = type
  osc.frequency.setValueAtTime(startFreq, ctx.currentTime + delay)
  osc.frequency.linearRampToValueAtTime(endFreq, ctx.currentTime + delay + duration)
  gain.gain.setValueAtTime(gainVal, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + duration)

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.start(ctx.currentTime + delay)
  osc.stop(ctx.currentTime + delay + duration)
}

// ── Sound definitions ──────────────────────────────────────────────────────

export function playDipSound() {
  // Descending tone: high to low, sounds like "dropping"
  playFreqRamp(880, 330, 0.5, 'sawtooth', 0.2, 0)
  playTone(220, 0.3, 'sine', 0.15, 0.5)
}

export function playBullishSound() {
  // Ascending triumphant: C-E-G chord rising
  playTone(523, 0.3, 'sine', 0.2, 0)      // C5
  playTone(659, 0.3, 'sine', 0.2, 0.15)   // E5
  playTone(784, 0.4, 'sine', 0.25, 0.3)   // G5
  playTone(1047, 0.5, 'triangle', 0.2, 0.5) // C6 (triumphant finish)
}

export function playBearishSound() {
  // Low ominous double-pulse
  playTone(150, 0.4, 'sawtooth', 0.2, 0)
  playTone(120, 0.5, 'sawtooth', 0.25, 0.4)
  playTone(90, 0.6, 'square', 0.1, 0.8)
}

export function playVolumeSound() {
  // Quick sharp double-tap
  playTone(1200, 0.1, 'square', 0.2, 0)
  playTone(1400, 0.1, 'square', 0.2, 0.15)
}

export function playDefaultSound() {
  // Simple notification ping
  playTone(800, 0.15, 'sine', 0.2, 0)
  playTone(1000, 0.2, 'sine', 0.15, 0.15)
}

// ── Main dispatcher ────────────────────────────────────────────────────────

const SOUND_MAP = {
  dip: playDipSound,
  bullish: playBullishSound,
  bearish: playBearishSound,
  volume: playVolumeSound,
}

export function playAlertSound(soundType) {
  const fn = SOUND_MAP[soundType] || playDefaultSound
  try {
    fn()
  } catch (err) {
    console.warn('Failed to play alert sound:', err)
  }
}

/**
 * Must be called from a user interaction (click) to unlock audio context.
 * Call this once when the user enables notifications.
 */
export function unlockAudio() {
  try {
    const ctx = getCtx()
    if (ctx.state === 'suspended') ctx.resume()
    // Play a silent tone to unlock
    playTone(0, 0.01, 'sine', 0, 0)
  } catch (err) {
    console.warn('Audio unlock failed:', err)
  }
}
