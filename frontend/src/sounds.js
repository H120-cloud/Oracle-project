/**
 * Alert Sound Generator — Web Audio API synthesized sounds.
 * No external audio files needed. Each alert type has a distinct tone.
 *
 * Sound types:
 *  - dip:       Descending tone (warning, stock dipping)
 *  - bullish:   Ascending triumphant chord (bounce confirmed / going up)
 *  - bearish:   Low ominous pulse (bearish shift)
 *  - volume:    Quick double-tap (volume surge)
 *  - money_up:  Money printer counting sound (stock going up)
 *  - money_down: Voice says "where's my money" (stock going down)
 *  - default:   Simple notification ping
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

export function playMoneyUpSound() {
  // Money printer / counting machine — rapid staccato clicks ascending in pitch
  const ctx = getCtx()
  const now = ctx.currentTime

  // Rapid "brrrr" clicking noise (money printer go brrr)
  for (let i = 0; i < 12; i++) {
    const t = i * 0.07
    const freq = 800 + i * 80  // ascending pitch
    playTone(freq, 0.04, 'square', 0.15, t)
  }

  // Cash register "cha-ching" finish
  playTone(1800, 0.08, 'sine', 0.25, 0.9)
  playTone(2400, 0.15, 'triangle', 0.3, 0.98)
  playTone(3200, 0.25, 'sine', 0.2, 1.05)
}

export function playMoneyDownSound() {
  // Mr. Krabs "Where's me money?!" via SpeechSynthesis
  try {
    if ('speechSynthesis' in window) {
      // Cancel any ongoing speech
      window.speechSynthesis.cancel()

      // Pick a deeper male-ish voice if available
      const voices = window.speechSynthesis.getVoices()
      const krabsVoice = voices.find(v =>
        v.lang.startsWith('en') &&
        (v.name.toLowerCase().includes('male') ||
         v.name.toLowerCase().includes('david') ||
         v.name.toLowerCase().includes('daniel') ||
         v.name.toLowerCase().includes('james') ||
         v.name.toLowerCase().includes('richard') ||
         v.name.toLowerCase().includes('microsoft'))
      ) || voices.find(v => v.lang.startsWith('en')) || null

      const utterance = new SpeechSynthesisUtterance("Where's me money?!")
      utterance.rate = 1.25      // fast & frantic
      utterance.pitch = 0.35    // deep & gruff like Krabs
      utterance.volume = 1.0
      if (krabsVoice) utterance.voice = krabsVoice

      // Tiny echo/reverb for that underwater cave effect
      const echo = new SpeechSynthesisUtterance("Money...")
      echo.rate = 1.0
      echo.pitch = 0.3
      echo.volume = 0.35
      if (krabsVoice) echo.voice = krabsVoice

      window.speechSynthesis.speak(utterance)
      setTimeout(() => window.speechSynthesis.speak(echo), 700)
    } else {
      // Fallback: ominous descending tones
      playFreqRamp(600, 150, 0.8, 'sawtooth', 0.25, 0)
      playTone(100, 0.5, 'square', 0.15, 0.8)
    }
  } catch (err) {
    // Fallback sound if speech fails
    playFreqRamp(600, 150, 0.8, 'sawtooth', 0.25, 0)
    playTone(100, 0.5, 'square', 0.15, 0.8)
  }
}

// ── Main dispatcher ────────────────────────────────────────────────────────

const SOUND_MAP = {
  dip: playDipSound,
  bullish: playBullishSound,
  bearish: playBearishSound,
  volume: playVolumeSound,
  money_up: playMoneyUpSound,
  money_down: playMoneyDownSound,
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
    playTone(1, 0.01, 'sine', 0, 0)
  } catch (err) {
    console.warn('Audio unlock failed:', err)
  }
}
