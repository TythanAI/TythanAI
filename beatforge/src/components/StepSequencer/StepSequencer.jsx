import React, { useState } from 'react'
import Track from './Track.jsx'
import { TRACK_LABELS, TRACK_COLORS } from '../../data/StylePresets.js'

const TRACKS = ['kick', 'snare', 'hihat', 'openhat', '808', 'clap', 'perc1', 'perc2']

const NOTES = ['C1','C#1','D1','D#1','E1','F1','F#1','G1','G#1','A1','A#1','B1',
               'C2','C#2','D2','D#2','E2','F2','F#2','G2']

export default function StepSequencer({
  pattern, currentStep, trackSettings, notes808,
  onToggleStep, onUpdateTrack, onNotes808Change,
  settings808, onSettings808Change,
  onOpenPianoRoll, onTrigger
}) {
  const [show808Notes, setShow808Notes] = useState(false)

  const handleMute = (track) => {
    onUpdateTrack(track, 'muted', !trackSettings[track]?.muted)
  }

  const handleSolo = (track) => {
    onUpdateTrack(track, 'solo', !trackSettings[track]?.solo)
  }

  return (
    <div className="flex flex-col p-3 gap-1 bg-[#111]">
      {/* Header */}
      <div className="flex items-center gap-4 mb-2 px-2">
        <span className="text-[#888] text-xs uppercase tracking-wider">Step Sequencer — 16 шагов</span>
        <div className="flex gap-0.5 ml-auto">
          {Array(16).fill(0).map((_, i) => (
            <div key={i} className="text-[9px] text-[#444] w-5 text-center" style={{minWidth:20}}>
              {i + 1}
            </div>
          ))}
          <div className="w-8" />
        </div>
      </div>

      {/* Tracks */}
      {TRACKS.map(track => (
        <Track
          key={track}
          track={track}
          name={TRACK_LABELS[track]}
          steps={pattern[track] || Array(16).fill(0)}
          currentStep={currentStep}
          settings={trackSettings[track]}
          color={TRACK_COLORS[track]}
          onToggle={onToggleStep}
          onVolumeChange={(t, v) => onUpdateTrack(t, 'volume', v)}
          onMute={handleMute}
          onSolo={handleSolo}
          onOpenPianoRoll={onOpenPianoRoll}
          onTrigger={onTrigger}
        />
      ))}

      {/* 808 Notes row */}
      <div className="mt-2 border-t border-[#222] pt-2">
        <div className="flex items-center gap-2 px-2 mb-1">
          <button
            onClick={() => setShow808Notes(v => !v)}
            className="text-xs text-[#ff4081] hover:text-white transition-colors"
          >
            808 Ноты {show808Notes ? '▲' : '▼'}
          </button>
          <span className="text-[#555] text-xs">— назначь ноту на каждый шаг 808</span>
        </div>

        {show808Notes && (
          <div className="flex gap-0.5 px-2 ml-[calc(90px+70px+8px)]">
            {(notes808 || Array(16).fill('C2')).map((note, i) => {
              const active = pattern?.['808']?.[i]
              return (
                <select
                  key={i}
                  value={note}
                  onChange={e => {
                    const arr = [...(notes808 || Array(16).fill('C2'))]
                    arr[i] = e.target.value
                    onNotes808Change(arr)
                  }}
                  className={`text-[9px] border rounded px-0 py-0 text-center transition-all ${
                    active
                      ? 'bg-[#ff408133] border-[#ff4081] text-[#ff4081]'
                      : 'bg-[#1a1a1a] border-[#2a2a2a] text-[#555]'
                  }`}
                  style={{minWidth:20, width:'calc(6.25% - 2px)', fontSize:9}}
                >
                  {NOTES.map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              )
            })}
          </div>
        )}
      </div>

      {/* 808 Controls */}
      <div className="flex items-center gap-6 px-4 py-2 mt-1 bg-[#161616] rounded border border-[#222]">
        <span className="text-[#ff4081] text-xs font-bold tracking-wider">808 ENGINE</span>

        <div className="flex items-center gap-2">
          <span className="text-[#666] text-xs">Decay</span>
          <input
            type="range" min={0.1} max={3} step={0.05}
            value={settings808.decay}
            onChange={e => onSettings808Change({ ...settings808, decay: Number(e.target.value) })}
            className="w-24" style={{accentColor:'#ff4081'}}
          />
          <span className="text-xs text-[#888] w-10">{settings808.decay.toFixed(2)}s</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[#666] text-xs">Distortion</span>
          <input
            type="range" min={0} max={1} step={0.01}
            value={settings808.distortion}
            onChange={e => onSettings808Change({ ...settings808, distortion: Number(e.target.value) })}
            className="w-24" style={{accentColor:'#ff4081'}}
          />
          <span className="text-xs text-[#888] w-10">{Math.round(settings808.distortion * 100)}%</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[#666] text-xs">Portamento</span>
          <input
            type="range" min={0} max={0.5} step={0.01}
            value={settings808.portamento}
            onChange={e => onSettings808Change({ ...settings808, portamento: Number(e.target.value) })}
            className="w-24" style={{accentColor:'#ff4081'}}
          />
          <span className="text-xs text-[#888] w-10">{Math.round(settings808.portamento * 1000)}ms</span>
        </div>
      </div>
    </div>
  )
}
