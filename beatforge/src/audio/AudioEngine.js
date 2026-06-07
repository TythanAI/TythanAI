import { SynthEngine } from './SynthEngine.js'

const TRACKS = ['kick', 'snare', 'hihat', 'openhat', '808', 'clap', 'perc1', 'perc2']

export class AudioEngine {
  constructor() {
    this.ctx = null
    this.synth = null
    this.isPlaying = false
    this.bpm = 140
    this.currentStep = 0
    this.nextStepTime = 0
    this.scheduleAheadTime = 0.1
    this.lookahead = 25
    this.timerID = null
    this.stepCallbacks = []
    this.stepsPerBar = 16
    this.bars = 2

    // State provided by React
    this.getPattern = () => ({})
    this.getPianoNotes = () => []
    this.getTrackSettings = () => ({})
    this.get808Settings = () => ({ decay: 1.2, distortion: 0.3, portamento: 0.1 })

    // Gain nodes per track (for mixer)
    this.trackGains = {}
    this.masterGain = null
    this.masterLimiter = null

    // Piano roll note tracking
    this.scheduledNotes = new Set()
  }

  async init() {
    if (this.ctx) return
    this.ctx = new (window.AudioContext || window.webkitAudioContext)()
    this.synth = new SynthEngine(this.ctx)

    this.masterGain = this.ctx.createGain()
    this.masterGain.gain.value = 0.85

    this.masterLimiter = this.ctx.createDynamicsCompressor()
    this.masterLimiter.threshold.value = -3
    this.masterLimiter.knee.value = 3
    this.masterLimiter.ratio.value = 20
    this.masterLimiter.attack.value = 0.001
    this.masterLimiter.release.value = 0.1

    this.masterGain.connect(this.masterLimiter)
    this.masterLimiter.connect(this.ctx.destination)

    for (const track of TRACKS) {
      const g = this.ctx.createGain()
      g.gain.value = 1
      g.connect(this.masterGain)
      this.trackGains[track] = g
    }
  }

  get stepDuration() {
    return (60 / this.bpm) / 4
  }

  get totalSteps() {
    return this.stepsPerBar * this.bars
  }

  start() {
    if (this.isPlaying) return
    if (this.ctx?.state === 'suspended') this.ctx.resume()
    this.isPlaying = true
    this.currentStep = 0
    this.nextStepTime = this.ctx.currentTime + 0.05
    this.timerID = setInterval(() => this._scheduler(), this.lookahead)
  }

  stop() {
    this.isPlaying = false
    if (this.timerID) clearInterval(this.timerID)
    this.timerID = null
    this.currentStep = 0
    this.stepCallbacks.forEach(cb => cb(-1))
  }

  toggle() {
    if (this.isPlaying) this.stop()
    else this.start()
  }

  _scheduler() {
    while (this.nextStepTime < this.ctx.currentTime + this.scheduleAheadTime) {
      this._scheduleStep(this.currentStep, this.nextStepTime)
      this._advance()
    }
  }

  _scheduleStep(step, when) {
    const pattern = this.getPattern()
    const settings = this.getTrackSettings()
    const s808 = this.get808Settings()

    // Notify UI of current step
    this.stepCallbacks.forEach(cb => cb(step))

    const dest = (track) => {
      const s = settings[track] || {}
      if (s.muted) return null
      return this.trackGains[track] || this.masterGain
    }

    const vol = (track) => {
      const s = settings[track] || {}
      return (s.volume ?? 1) * (s.solo ? 1 : this._hasSolo() ? 0 : 1)
    }

    if (pattern.kick?.[step]) {
      const d = dest('kick')
      if (d) this.synth.playKick(when, settings.kick?.style || 'trap', vol('kick'), d)
    }

    if (pattern.snare?.[step]) {
      const d = dest('snare')
      if (d) this.synth.playSnare(when, settings.snare?.style || 'trap', vol('snare'), d)
    }

    if (pattern.hihat?.[step]) {
      const d = dest('hihat')
      if (d) this.synth.playHihat(when, false, vol('hihat'), d)
    }

    if (pattern.openhat?.[step]) {
      const d = dest('openhat')
      if (d) this.synth.playHihat(when, true, vol('openhat'), d)
    }

    if (pattern.clap?.[step]) {
      const d = dest('clap')
      if (d) this.synth.playClap(when, vol('clap'), d)
    }

    if (pattern.perc1?.[step]) {
      const d = dest('perc1')
      if (d) this.synth.playPerc(when, 1, vol('perc1'), d)
    }

    if (pattern.perc2?.[step]) {
      const d = dest('perc2')
      if (d) this.synth.playPerc(when, 2, vol('perc2'), d)
    }

    if (pattern['808']?.[step]) {
      const d = dest('808')
      if (d) {
        const notes808 = this.get808Notes()
        const note = notes808?.[step] || 'C2'
        this.synth.play808(when, note, this.stepDuration * 3, s808.distortion, s808.decay, vol('808'), d)
      }
    }

    // Piano roll notes
    this._schedulePianoNotes(step, when)
  }

  _schedulePianoNotes(step, when) {
    const notes = this.getPianoNotes()
    const totalSteps = this.totalSteps
    notes.forEach(note => {
      const noteStep = Math.round(note.start * 16)
      if (noteStep % totalSteps === step % totalSteps) {
        const dur = note.duration * this.stepDuration * 4
        this.synth.play808(when, note.note, dur, 0, dur * 0.9, note.velocity / 127, this.masterGain)
      }
    })
  }

  _advance() {
    const swing = this.getTrackSettings()?.swing || 0
    let swingOffset = 0
    if (this.currentStep % 2 === 1) swingOffset = (swing / 100) * this.stepDuration * 0.5

    this.nextStepTime += this.stepDuration + swingOffset
    this.currentStep = (this.currentStep + 1) % this.totalSteps
  }

  _hasSolo() {
    const settings = this.getTrackSettings()
    return TRACKS.some(t => settings[t]?.solo)
  }

  onStep(cb) {
    this.stepCallbacks.push(cb)
    return () => { this.stepCallbacks = this.stepCallbacks.filter(c => c !== cb) }
  }

  setTrackGain(track, value) {
    if (this.trackGains[track]) this.trackGains[track].gain.setValueAtTime(value, this.ctx?.currentTime || 0)
  }

  setMasterVolume(value) {
    if (this.masterGain) this.masterGain.gain.setValueAtTime(value, this.ctx?.currentTime || 0)
  }

  get808Notes() {
    return this._808notes || []
  }

  set808Notes(notes) {
    this._808notes = notes
  }

  triggerPad(track, when) {
    if (!this.ctx) return
    const t = when || this.ctx.currentTime
    const dest = this.trackGains[track] || this.masterGain
    switch(track) {
      case 'kick': this.synth.playKick(t, 'trap', 1, dest); break
      case 'snare': this.synth.playSnare(t, 'trap', 1, dest); break
      case 'hihat': this.synth.playHihat(t, false, 1, dest); break
      case 'openhat': this.synth.playHihat(t, true, 1, dest); break
      case 'clap': this.synth.playClap(t, 1, dest); break
      case 'perc1': this.synth.playPerc(t, 1, 1, dest); break
      case 'perc2': this.synth.playPerc(t, 2, 1, dest); break
      case '808': this.synth.play808(t, 'C2', 0.5, 0.3, 1.0, 1, dest); break
    }
  }
}

export const engine = new AudioEngine()
