import React, { useState } from 'react'
import { STYLE_PRESETS } from '../../data/StylePresets.js'

const PRESET_ICONS = {
  'Trap Atlanta': '🔥',
  'West Coast G-Funk': '🌴',
  'Drill Chicago': '🌑',
  'Boom Bap Classic': '🎧',
  'Shoreline Hyphy': '🌊',
  'Lo-Fi Chill': '☕',
}

const PRESET_COLORS = {
  'Trap Atlanta': '#ff6b00',
  'West Coast G-Funk': '#00bfff',
  'Drill Chicago': '#9c27b0',
  'Boom Bap Classic': '#ffd740',
  'Shoreline Hyphy': '#00e676',
  'Lo-Fi Chill': '#80cbc4',
}

export default function StylePresets({ onLoad }) {
  const [active, setActive] = useState(null)

  const handleLoad = (name) => {
    setActive(name)
    onLoad(name)
  }

  return (
    <div className="flex flex-col w-36 bg-[#141414] border-r border-[#222] overflow-y-auto">
      <div className="px-3 py-2 border-b border-[#222]">
        <span className="text-[10px] text-[#555] uppercase tracking-wider font-bold">Стили</span>
      </div>

      <div className="flex flex-col gap-0.5 p-1.5">
        {Object.entries(STYLE_PRESETS).map(([name, preset]) => {
          const color = PRESET_COLORS[name] || '#ff6b00'
          const isActive = active === name
          return (
            <button
              key={name}
              onClick={() => handleLoad(name)}
              className={`flex flex-col items-start px-2 py-1.5 rounded text-left transition-all group ${
                isActive
                  ? 'bg-[#222] border border-[#333]'
                  : 'hover:bg-[#1c1c1c] border border-transparent'
              }`}
            >
              <div className="flex items-center gap-1.5 w-full">
                <span className="text-sm">{PRESET_ICONS[name]}</span>
                <span
                  className="text-[11px] font-medium leading-tight"
                  style={{ color: isActive ? color : '#aaa' }}
                >
                  {name.split(' ').slice(0, 2).join(' ')}
                </span>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5 ml-5">
                <span className="text-[9px] text-[#555]">{preset.bpm} BPM</span>
                {preset.swing > 0 && (
                  <span className="text-[8px] text-[#444]">sw{preset.swing}</span>
                )}
              </div>
              <div
                className="w-full h-0.5 rounded mt-1 opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ background: color }}
              />
            </button>
          )
        })}
      </div>

      {/* Randomize */}
      <div className="mt-auto p-2 border-t border-[#222]">
        <button
          onClick={() => {
            const names = Object.keys(STYLE_PRESETS)
            handleLoad(names[Math.floor(Math.random() * names.length)])
          }}
          className="w-full py-1.5 rounded text-xs text-[#888] bg-[#1a1a1a] hover:bg-[#222] hover:text-white transition-colors"
        >
          🎲 Рандом
        </button>
      </div>
    </div>
  )
}
