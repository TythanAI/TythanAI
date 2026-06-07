export class SynthEngine {
  constructor(ctx) {
    this.ctx = ctx
  }

  noteToHz(note) {
    const map = { C:0,'C#':1,Db:1,D:2,'D#':3,Eb:3,E:4,F:5,'F#':6,Gb:6,G:7,'G#':8,Ab:8,A:9,'A#':10,Bb:10,B:11 }
    const m = note.match(/^([A-G]#?b?)(\d)$/)
    if (!m) return 440
    const semitone = map[m[1]] + (parseInt(m[2]) + 1) * 12
    return 440 * Math.pow(2, (semitone - 69) / 12)
  }

  makeDistortionCurve(amount) {
    const n = 256
    const curve = new Float32Array(n)
    for (let i = 0; i < n; i++) {
      const x = (i * 2) / n - 1
      curve[i] = ((Math.PI + amount) * x) / (Math.PI + amount * Math.abs(x))
    }
    return curve
  }

  playKick(when = 0, style = 'trap', volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination

    const osc = this.ctx.createOscillator()
    const gain = this.ctx.createGain()
    const punch = this.ctx.createGain()

    const startFreq = style === 'trap' ? 220 : style === 'drill' ? 200 : 160
    const endFreq = style === 'boom_bap' ? 50 : 40
    const decay = style === 'boom_bap' ? 0.6 : 0.45

    osc.frequency.setValueAtTime(startFreq, t)
    osc.frequency.exponentialRampToValueAtTime(endFreq, t + 0.08)

    punch.gain.setValueAtTime(1.4, t)
    punch.gain.exponentialRampToValueAtTime(1, t + 0.01)

    gain.gain.setValueAtTime(volume * 1.2, t)
    gain.gain.exponentialRampToValueAtTime(0.001, t + decay)

    osc.connect(punch)
    punch.connect(gain)
    gain.connect(out)

    osc.start(t)
    osc.stop(t + decay + 0.05)
  }

  playSnare(when = 0, style = 'trap', volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination

    // Noise layer
    const bufSize = this.ctx.sampleRate * 0.2
    const buf = this.ctx.createBuffer(1, bufSize, this.ctx.sampleRate)
    const data = buf.getChannelData(0)
    for (let i = 0; i < bufSize; i++) data[i] = Math.random() * 2 - 1

    const noise = this.ctx.createBufferSource()
    const noiseFilter = this.ctx.createBiquadFilter()
    const noiseGain = this.ctx.createGain()

    noiseFilter.type = 'bandpass'
    noiseFilter.frequency.value = style === 'trap' ? 3000 : 2000
    noiseFilter.Q.value = 0.8

    noise.buffer = buf
    noiseGain.gain.setValueAtTime(volume * 0.8, t)
    noiseGain.gain.exponentialRampToValueAtTime(0.001, t + (style === 'trap' ? 0.15 : 0.25))

    noise.connect(noiseFilter)
    noiseFilter.connect(noiseGain)
    noiseGain.connect(out)
    noise.start(t)
    noise.stop(t + 0.3)

    // Tone layer
    const osc = this.ctx.createOscillator()
    const oscGain = this.ctx.createGain()
    osc.frequency.setValueAtTime(200, t)
    osc.frequency.exponentialRampToValueAtTime(100, t + 0.06)
    oscGain.gain.setValueAtTime(volume * 0.5, t)
    oscGain.gain.exponentialRampToValueAtTime(0.001, t + 0.1)
    osc.connect(oscGain)
    oscGain.connect(out)
    osc.start(t)
    osc.stop(t + 0.15)
  }

  playClap(when = 0, volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination

    for (let i = 0; i < 3; i++) {
      const delay = i * 0.012
      const bufSize = Math.floor(this.ctx.sampleRate * 0.04)
      const buf = this.ctx.createBuffer(1, bufSize, this.ctx.sampleRate)
      const data = buf.getChannelData(0)
      for (let j = 0; j < bufSize; j++) data[j] = Math.random() * 2 - 1

      const src = this.ctx.createBufferSource()
      const filter = this.ctx.createBiquadFilter()
      const gain = this.ctx.createGain()

      filter.type = 'bandpass'
      filter.frequency.value = 1200
      filter.Q.value = 0.5

      src.buffer = buf
      gain.gain.setValueAtTime(volume * (i === 2 ? 0.9 : 0.5), t + delay)
      gain.gain.exponentialRampToValueAtTime(0.001, t + delay + 0.08)

      src.connect(filter)
      filter.connect(gain)
      gain.connect(out)
      src.start(t + delay)
      src.stop(t + delay + 0.1)
    }
  }

  playHihat(when = 0, open = false, volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination
    const duration = open ? 0.35 : 0.05

    const bufSize = Math.floor(this.ctx.sampleRate * duration)
    const buf = this.ctx.createBuffer(1, bufSize, this.ctx.sampleRate)
    const data = buf.getChannelData(0)
    for (let i = 0; i < bufSize; i++) data[i] = Math.random() * 2 - 1

    const src = this.ctx.createBufferSource()
    const hpf = this.ctx.createBiquadFilter()
    const gain = this.ctx.createGain()

    hpf.type = 'highpass'
    hpf.frequency.value = 8000

    src.buffer = buf
    gain.gain.setValueAtTime(volume * 0.35, t)
    gain.gain.exponentialRampToValueAtTime(0.001, t + duration)

    src.connect(hpf)
    hpf.connect(gain)
    gain.connect(out)
    src.start(t)
    src.stop(t + duration + 0.01)
  }

  playPerc(when = 0, variant = 1, volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination
    const freq = variant === 1 ? 400 : 300

    const osc = this.ctx.createOscillator()
    const gain = this.ctx.createGain()
    osc.frequency.setValueAtTime(freq, t)
    osc.frequency.exponentialRampToValueAtTime(freq * 0.3, t + 0.15)
    gain.gain.setValueAtTime(volume * 0.6, t)
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15)
    osc.connect(gain)
    gain.connect(out)
    osc.start(t)
    osc.stop(t + 0.2)
  }

  play808(when = 0, note = 'C2', duration = 0.5, distortion = 0.3, decay = 1.2, volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination
    const freq = this.noteToHz(note)

    const osc = this.ctx.createOscillator()
    const waveshaper = this.ctx.createWaveShaper()
    const lpf = this.ctx.createBiquadFilter()
    const gain = this.ctx.createGain()

    osc.type = 'sine'
    osc.frequency.setValueAtTime(freq, t)

    waveshaper.curve = this.makeDistortionCurve(distortion * 300)
    waveshaper.oversample = '4x'

    lpf.type = 'lowpass'
    lpf.frequency.value = 200

    gain.gain.setValueAtTime(0, t)
    gain.gain.linearRampToValueAtTime(volume * 1.1, t + 0.005)
    gain.gain.exponentialRampToValueAtTime(0.001, t + decay)

    osc.connect(waveshaper)
    waveshaper.connect(lpf)
    lpf.connect(gain)
    gain.connect(out)

    osc.start(t)
    osc.stop(t + decay + 0.05)

    return osc
  }

  play808Slide(when = 0, fromNote = 'C2', toNote = 'A1', duration = 0.5, slideTime = 0.15, distortion = 0.3, decay = 1.2, volume = 1, dest = null) {
    const t = when || this.ctx.currentTime
    const out = dest || this.ctx.destination
    const fromHz = this.noteToHz(fromNote)
    const toHz = this.noteToHz(toNote)

    const osc = this.ctx.createOscillator()
    const waveshaper = this.ctx.createWaveShaper()
    const lpf = this.ctx.createBiquadFilter()
    const gain = this.ctx.createGain()

    osc.type = 'sine'
    osc.frequency.setValueAtTime(fromHz, t)
    osc.frequency.exponentialRampToValueAtTime(toHz, t + slideTime)

    waveshaper.curve = this.makeDistortionCurve(distortion * 300)
    lpf.type = 'lowpass'
    lpf.frequency.value = 200

    gain.gain.setValueAtTime(0, t)
    gain.gain.linearRampToValueAtTime(volume * 1.1, t + 0.005)
    gain.gain.exponentialRampToValueAtTime(0.001, t + decay)

    osc.connect(waveshaper)
    waveshaper.connect(lpf)
    lpf.connect(gain)
    gain.connect(out)

    osc.start(t)
    osc.stop(t + decay + 0.05)
  }
}
