import React, { useRef, useState } from 'react'
import { TRACK_COLORS } from '../../data/StylePresets.js'

function Knob({ value, min = 0, max = 1, onChange, color = '#ff6b00', size = 32 }) {
  const dragging = useRef(false)
  const startY = useRef(0)
  const startVal = useRef(0)

  const angle = -135 + ((value - min) / (max - min)) * 270
  const r = size / 2 - 4
  const cx = size / 2
  const cy = size / 2
  const toXY = (deg) => {
    const rad = (deg - 90) * Math.PI / 180
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)]
  }
  const [sx, sy] = toXY(-135)
  const [ex, ey] = toXY(angle)
  const large = ((angle + 135) / 270) > 0.5 ? 1 : 0

  const onMouseDown = (e) => {
    dragging.current = true
    startY.current = e.clientY
    startVal.current = value
    e.preventDefault()
    const up = () => { dragging.current = false; window.removeEventListener('mouseup', up); window.removeEventListener('mousemove', move) }
    const move = (e) => {
      if (!dragging.current) return
      const delta = (startY.current - e.clientY) / 150
      const newVal = Math.max(min, Math.min(max, startVal.current + delta * (max - min)))
      onChange(Math.round(newVal * 100) / 100)
    }
    window.addEventListener('mouseup', up)
    window.addEventListener('mousemove', move)
  }

  return (
    <svg width={size} height={size} onMouseDown={onMouseDown} className="cursor-ns-resize" title={`${Math.round((value-min)/(max-min)*100)}%`}>
      <circle cx={cx} cy={cy} r={r} stroke="#2a2a2a" strokeWidth="3" fill="#1a1a1a" />
      <path d={`M ${sx} ${sy} A ${r} ${r} 0 1 1 ${ex} ${ey}`} stroke="#333" strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <path d={`M ${sx} ${sy} A ${r} ${r} 0 ${large} 1 ${ex} ${ey}`} stroke={color} strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export default function Track({
  name, track, steps, currentStep, settings, color,
  onToggle, onVolumeChange, onMute, onSolo, onOpenPianoRoll, onTrigger
}) {
  const c = color || TRACK_COLORS[track] || '#ff6b00'
  const isMuted = settings?.muted
  const isSolo = settings?.solo

  return (
    <div className={`flex items-center gap-1 px-2 py-1 border-b border-[#222] group hover:bg-[#1c1c1c] transition-colors ${isMuted ? 'opacity-50' : ''}`}>
      {/* Track name */}
      <div
        className="flex items-center gap-2 cursor-pointer min-w-[90px]"
        onClick={() => onOpenPianoRoll?.(track)}
        title="Открыть Piano Roll"
      >
        <div className="w-1.5 h-6 rounded-sm" style={{background: c}} />
        <span className="text-xs font-medium text-[#ccc] truncate hover:text-white">{name}</span>
      </div>

      {/* Mute */}
      <button
        onClick={() => onMute?.(track)}
        className={`w-5 h-5 rounded text-[10px] font-bold transition-colors ${
          isMuted ? 'bg-[#ff4444] text-white' : 'bg-[#222] text-[#666] hover:text-white'
        }`}
      >M</button>

      {/* Solo */}
      <button
        onClick={() => onSolo?.(track)}
        className={`w-5 h-5 rounded text-[10px] font-bold transition-colors mr-1 ${
          isSolo ? 'bg-[#ffd740] text-black' : 'bg-[#222] text-[#666] hover:text-white'
        }`}
      >S</button>

      {/* Volume knob */}
      <Knob
        value={settings?.volume ?? 1}
        min={0} max={1}
        onChange={v => onVolumeChange?.(track, v)}
        color={c}
        size={28}
      />

      {/* Steps */}
      <div className="flex gap-0.5 ml-2 flex-1">
        {steps.map((active, i) => {
          const isCurrent = i === currentStep
          const isBar = i % 4 === 0
          return (
            <button
              key={i}
              className="step-btn flex-1 h-7 rounded-sm border transition-all"
              style={{
                background: isCurrent
                  ? '#ffffff'
                  : active
                    ? c
                    : isBar ? '#252525' : '#1a1a1a',
                borderColor: isCurrent ? '#ffffff' : active ? c : '#2a2a2a',
                boxShadow: active && !isCurrent ? `0 0 6px ${c}55` : 'none',
                minWidth: 20,
              }}
              onClick={() => { onToggle(track, i); onTrigger?.(track) }}
            />
          )
        })}
      </div>

      {/* Trigger pad */}
      <button
        className="w-7 h-7 ml-1 rounded text-xs font-bold transition-all active:scale-95 hover:opacity-80"
        style={{ background: c + '33', color: c, border: `1px solid ${c}66` }}
        onMouseDown={() => onTrigger?.(track)}
      >▶</button>
    </div>
  )
}
