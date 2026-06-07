import React, { useState } from 'react'
import { TRACK_LABELS, TRACK_COLORS } from '../../data/StylePresets.js'
import { engine } from '../../audio/AudioEngine.js'

const TRACKS = ['kick', 'snare', 'hihat', 'openhat', '808', 'clap', 'perc1', 'perc2']

function VUMeter({ level = 0 }) {
  const segs = 12
  return (
    <div className="flex flex-col-reverse gap-px h-24 w-3">
      {Array(segs).fill(0).map((_, i) => {
        const threshold = i / segs
        const active = level > threshold
        const color = i >= 10 ? '#ff4444' : i >= 7 ? '#ffd740' : '#00e676'
        return (
          <div
            key={i}
            className="flex-1 rounded-sm transition-all"
            style={{ background: active ? color : '#222' }}
          />
        )
      })}
    </div>
  )
}

function Fader({ value, onChange, color }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[10px] text-[#888]">{Math.round(value * 100)}%</span>
      <input
        type="range"
        min={0} max={1} step={0.01}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="h-20 cursor-pointer"
        style={{ writingMode: 'vertical-lr', direction: 'rtl', accentColor: color, width: 20 }}
      />
    </div>
  )
}

function EQBand({ label, freq, value, onChange, color }) {
  return (
    <div className="flex flex-col items-center gap-0.5">
      <span className="text-[9px] text-[#555]">{freq}</span>
      <input
        type="range" min={-12} max={12} step={0.5}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="h-12"
        style={{ writingMode: 'vertical-lr', direction: 'rtl', accentColor: color, width: 14 }}
      />
      <span className="text-[9px] text-[#666]">{value > 0 ? `+${value}` : value}</span>
      <span className="text-[8px] text-[#444]">{label}</span>
    </div>
  )
}

function MixerChannel({ track, settings, onUpdate, color }) {
  const [eq, setEq] = useState({ low: 0, mid: 0, high: 0 })
  const [comp, setComp] = useState({ threshold: -20, ratio: 4, attack: 10, release: 100 })
  const [showEQ, setShowEQ] = useState(false)

  const level = settings?.volume ?? 1

  return (
    <div
      className="flex flex-col items-center gap-1 px-2 py-2 bg-[#1a1a1a] rounded border transition-colors"
      style={{ borderColor: settings?.solo ? color : '#2a2a2a', minWidth: 70 }}
    >
      {/* Track name */}
      <div className="w-full h-1 rounded-full mb-1" style={{ background: color }} />
      <span className="text-[10px] text-[#ccc] font-medium text-center leading-tight">
        {TRACK_LABELS[track]}
      </span>

      {/* VU + Fader */}
      <div className="flex gap-1 items-end">
        <VUMeter level={settings?.muted ? 0 : level} />
        <Fader
          value={level}
          onChange={v => onUpdate(track, 'volume', v)}
          color={color}
        />
      </div>

      {/* Pan */}
      <div className="flex flex-col items-center w-full gap-0.5">
        <span className="text-[9px] text-[#555]">PAN</span>
        <input
          type="range" min={-1} max={1} step={0.01}
          value={settings?.pan ?? 0}
          onChange={e => onUpdate(track, 'pan', Number(e.target.value))}
          className="w-full" style={{ accentColor: color }}
        />
        <span className="text-[9px] text-[#666]">
          {(() => { const p = settings?.pan ?? 0; return p > 0.05 ? `${Math.round(p*100)}R` : p < -0.05 ? `${Math.abs(Math.round(p*100))}L` : 'C' })()}
        </span>
      </div>

      {/* Mute / Solo */}
      <div className="flex gap-1 w-full mt-0.5">
        <button
          onClick={() => onUpdate(track, 'muted', !settings?.muted)}
          className={`flex-1 py-0.5 rounded text-[10px] font-bold transition-colors ${
            settings?.muted ? 'bg-[#ff4444] text-white' : 'bg-[#222] text-[#666] hover:text-white'
          }`}
        >M</button>
        <button
          onClick={() => onUpdate(track, 'solo', !settings?.solo)}
          className={`flex-1 py-0.5 rounded text-[10px] font-bold transition-colors ${
            settings?.solo ? 'bg-[#ffd740] text-black' : 'bg-[#222] text-[#666] hover:text-white'
          }`}
        >S</button>
      </div>

      {/* EQ toggle */}
      <button
        onClick={() => setShowEQ(v => !v)}
        className={`w-full py-0.5 rounded text-[9px] transition-colors ${
          showEQ ? 'bg-[#333] text-[#ff6b00]' : 'bg-[#1a1a1a] text-[#555] hover:text-white'
        }`}
      >EQ</button>

      {showEQ && (
        <div className="flex gap-1 mt-1">
          <EQBand label="Lo" freq="80Hz" value={eq.low} onChange={v => setEq({...eq, low: v})} color="#ff6b00" />
          <EQBand label="Mid" freq="1kHz" value={eq.mid} onChange={v => setEq({...eq, mid: v})} color="#00bfff" />
          <EQBand label="Hi" freq="10kHz" value={eq.high} onChange={v => setEq({...eq, high: v})} color="#00e676" />
        </div>
      )}
    </div>
  )
}

export default function Mixer({ trackSettings, onUpdateTrack }) {
  const [masterVol, setMasterVol] = useState(0.85)

  const handleMasterVol = (v) => {
    setMasterVol(v)
    if (engine.masterGain) engine.masterGain.gain.value = v
  }

  return (
    <div className="flex gap-2 p-3 bg-[#111] h-full overflow-x-auto items-start">
      {TRACKS.map(track => (
        <MixerChannel
          key={track}
          track={track}
          settings={trackSettings[track]}
          onUpdate={onUpdateTrack}
          color={TRACK_COLORS[track]}
        />
      ))}

      {/* Master channel */}
      <div className="flex flex-col items-center gap-1 px-2 py-2 bg-[#222] rounded border border-[#ff6b0066] ml-4" style={{minWidth:70}}>
        <div className="w-full h-1 rounded-full mb-1" style={{background:'#ff6b00'}} />
        <span className="text-[10px] text-[#ff6b00] font-bold">MASTER</span>
        <div className="flex gap-1 items-end">
          <VUMeter level={masterVol} />
          <Fader value={masterVol} onChange={handleMasterVol} color="#ff6b00" />
        </div>
        <span className="text-[9px] text-[#666]">LIMITER</span>
        <div className="w-full h-1 rounded bg-[#ff6b0033] mt-0.5">
          <div className="h-full rounded bg-[#ff6b00]" style={{width: `${masterVol*100}%`}} />
        </div>
      </div>
    </div>
  )
}
