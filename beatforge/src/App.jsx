import React, { useState, useEffect, useCallback, useRef } from 'react'
import TransportBar from './components/TransportBar.jsx'
import StepSequencer from './components/StepSequencer/StepSequencer.jsx'
import PianoRoll from './components/PianoRoll/PianoRoll.jsx'
import Sampler from './components/Sampler/SamplerPad.jsx'
import Mixer from './components/Mixer/Mixer.jsx'
import StylePresets from './components/Sidebar/StylePresets.jsx'
import { engine } from './audio/AudioEngine.js'
import { STYLE_PRESETS } from './data/StylePresets.js'

const EMPTY_PATTERN = () => ({
  kick:    Array(16).fill(0),
  snare:   Array(16).fill(0),
  hihat:   Array(16).fill(0),
  openhat: Array(16).fill(0),
  '808':   Array(16).fill(0),
  clap:    Array(16).fill(0),
  perc1:   Array(16).fill(0),
  perc2:   Array(16).fill(0),
})

const DEFAULT_TRACK_SETTINGS = () => {
  const s = {}
  ;['kick','snare','hihat','openhat','808','clap','perc1','perc2'].forEach(t => {
    s[t] = { volume: 1, muted: false, solo: false }
  })
  return s
}

export default function App() {
  const [isPlaying, setIsPlaying] = useState(false)
  const [bpm, setBpm] = useState(140)
  const [currentStep, setCurrentStep] = useState(-1)
  const [pattern, setPattern] = useState(EMPTY_PATTERN())
  const [trackSettings, setTrackSettings] = useState(DEFAULT_TRACK_SETTINGS())
  const [notes808, setNotes808] = useState(Array(16).fill('C2'))
  const [activeTab, setActiveTab] = useState('sequencer')
  const [pianoRollTrack, setPianoRollTrack] = useState(null)
  const [pianoNotes, setPianoNotes] = useState([])
  const [settings808, setSettings808] = useState({ decay: 1.2, distortion: 0.3, portamento: 0.1 })
  const [toast, setToast] = useState(null)
  const [swing, setSwing] = useState(0)
  const engineReady = useRef(false)

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2000)
  }

  const initEngine = useCallback(async () => {
    if (!engineReady.current) {
      await engine.init()
      engineReady.current = true
      engine.onStep(step => setCurrentStep(step))
    }
  }, [])

  useEffect(() => {
    engine.bpm = bpm
  }, [bpm])

  useEffect(() => {
    engine.getPattern = () => pattern
  }, [pattern])

  useEffect(() => {
    engine.getTrackSettings = () => ({ ...trackSettings, swing })
  }, [trackSettings, swing])

  useEffect(() => {
    engine['808Notes'] = notes808
    engine.get808Notes = () => notes808
  }, [notes808])

  useEffect(() => {
    engine.get808Settings = () => settings808
  }, [settings808])

  useEffect(() => {
    const handler = (e) => {
      if (e.code === 'Space' && e.target.tagName !== 'INPUT') {
        e.preventDefault()
        handlePlayStop()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isPlaying])

  const handlePlayStop = async () => {
    await initEngine()
    if (isPlaying) {
      engine.stop()
      setIsPlaying(false)
      setCurrentStep(-1)
    } else {
      engine.start()
      setIsPlaying(true)
    }
  }

  const toggleStep = (track, step) => {
    setPattern(p => ({
      ...p,
      [track]: p[track].map((v, i) => i === step ? (v ? 0 : 1) : v)
    }))
    initEngine().then(() => engine.triggerPad(track))
  }

  const loadPreset = (name) => {
    const preset = STYLE_PRESETS[name]
    if (!preset) return
    setBpm(preset.bpm)
    setSwing(preset.swing || 0)
    setPattern({ ...EMPTY_PATTERN(), ...preset.pattern })
    if (preset.notes808) setNotes808(preset.notes808)
    showToast(`${name} загружен ✓`)
  }

  const updateTrackSetting = (track, key, value) => {
    setTrackSettings(s => ({ ...s, [track]: { ...s[track], [key]: value } }))
  }

  const tabs = [
    { id: 'sequencer', label: 'Секвенсор' },
    { id: 'pianoroll', label: 'Piano Roll' },
    { id: 'sampler', label: 'Sampler' },
    { id: 'mixer', label: 'Mixer' },
  ]

  return (
    <div className="flex flex-col h-screen bg-[#0f0f0f] select-none overflow-hidden">
      {/* Transport */}
      <TransportBar
        isPlaying={isPlaying}
        bpm={bpm}
        onBpmChange={setBpm}
        onPlayStop={handlePlayStop}
        currentStep={currentStep}
        swing={swing}
        onSwingChange={setSwing}
      />

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <StylePresets onLoad={loadPreset} />

        {/* Main area */}
        <div className="flex flex-col flex-1 overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-[#2a2a2a] bg-[#141414]">
            {tabs.map(t => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`px-5 py-2 text-sm font-medium transition-colors ${
                  activeTab === t.id
                    ? 'text-[#ff6b00] border-b-2 border-[#ff6b00] bg-[#1a1a1a]'
                    : 'text-[#888] hover:text-[#ccc]'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-auto">
            {activeTab === 'sequencer' && (
              <StepSequencer
                pattern={pattern}
                currentStep={currentStep}
                trackSettings={trackSettings}
                notes808={notes808}
                onToggleStep={toggleStep}
                onUpdateTrack={updateTrackSetting}
                onNotes808Change={setNotes808}
                settings808={settings808}
                onSettings808Change={setSettings808}
                onOpenPianoRoll={(track) => { setPianoRollTrack(track); setActiveTab('pianoroll') }}
                onTrigger={(track) => initEngine().then(() => engine.triggerPad(track))}
              />
            )}
            {activeTab === 'pianoroll' && (
              <PianoRoll
                track={pianoRollTrack}
                notes={pianoNotes}
                onChange={setPianoNotes}
                bpm={bpm}
              />
            )}
            {activeTab === 'sampler' && (
              <Sampler onTrigger={(note) => initEngine().then(() => engine.synth?.play808(0, note, 0.5, 0.3, 1, 1))} />
            )}
            {activeTab === 'mixer' && (
              <Mixer
                trackSettings={trackSettings}
                onUpdateTrack={updateTrackSetting}
              />
            )}
          </div>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-[#ff6b00] text-white px-4 py-2 rounded-lg text-sm font-medium shadow-xl z-50 pointer-events-none">
          {toast}
        </div>
      )}
    </div>
  )
}
