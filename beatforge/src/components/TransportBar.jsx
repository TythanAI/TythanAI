import React from 'react'

export default function TransportBar({ isPlaying, bpm, onBpmChange, onPlayStop, currentStep, swing, onSwingChange }) {
  const bar = currentStep < 0 ? 1 : Math.floor(currentStep / 4) + 1
  const beat = currentStep < 0 ? 1 : (currentStep % 4) + 1

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-[#141414] border-b border-[#2a2a2a] select-none" style={{minHeight:52}}>
      {/* Logo */}
      <div className="text-[#ff6b00] font-black text-lg tracking-widest mr-2">
        BEAT<span className="text-white">FORGE</span>
      </div>

      {/* Play/Stop */}
      <button
        onClick={onPlayStop}
        className={`flex items-center justify-center w-10 h-10 rounded font-bold text-lg transition-all ${
          isPlaying
            ? 'bg-[#ff6b00] text-white hover:bg-[#cc5500]'
            : 'bg-[#2a2a2a] text-[#e0e0e0] hover:bg-[#3a3a3a]'
        }`}
        title="Space"
      >
        {isPlaying ? '■' : '▶'}
      </button>

      {/* Divider */}
      <div className="w-px h-8 bg-[#333]" />

      {/* BPM */}
      <div className="flex items-center gap-2">
        <span className="text-[#888] text-xs uppercase tracking-wider">BPM</span>
        <input
          type="range"
          min={60} max={200} value={bpm}
          onChange={e => onBpmChange(Number(e.target.value))}
          className="w-28 accent-[#ff6b00] cursor-pointer"
          style={{accentColor:'#ff6b00'}}
        />
        <input
          type="number"
          min={60} max={200} value={bpm}
          onChange={e => onBpmChange(Number(e.target.value))}
          className="w-14 text-center bg-[#222] border border-[#333] rounded px-1 py-0.5 text-sm text-[#ff6b00] font-mono font-bold focus:outline-none focus:border-[#ff6b00]"
        />
      </div>

      {/* Divider */}
      <div className="w-px h-8 bg-[#333]" />

      {/* Swing */}
      <div className="flex items-center gap-2">
        <span className="text-[#888] text-xs uppercase tracking-wider">Swing</span>
        <input
          type="range"
          min={0} max={50} value={swing}
          onChange={e => onSwingChange(Number(e.target.value))}
          className="w-20"
          style={{accentColor:'#00bfff'}}
        />
        <span className="text-xs text-[#888] w-6">{swing}%</span>
      </div>

      {/* Divider */}
      <div className="w-px h-8 bg-[#333]" />

      {/* Position display */}
      <div className="font-mono text-sm bg-[#0a0a0a] border border-[#333] rounded px-3 py-1 text-[#00e676]">
        {String(bar).padStart(2,'0')}:{beat}
        <span className="text-[#444] mx-1">|</span>
        <span className="text-[#888] text-xs">{currentStep < 0 ? '--' : String(currentStep + 1).padStart(2,'0')}</span>
      </div>

      <div className="flex-1" />

      {/* Step grid indicator mini */}
      <div className="flex gap-0.5">
        {Array(16).fill(0).map((_, i) => (
          <div
            key={i}
            className="w-2 h-2 rounded-sm transition-all"
            style={{
              background: i === currentStep ? '#ff6b00' : (i % 4 === 0 ? '#333' : '#222')
            }}
          />
        ))}
      </div>

      <span className="text-[#555] text-xs ml-2">SPACE = Play/Stop</span>
    </div>
  )
}
