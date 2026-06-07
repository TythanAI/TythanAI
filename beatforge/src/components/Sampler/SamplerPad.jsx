import React, { useState, useRef, useEffect } from 'react'
import { engine } from '../../audio/AudioEngine.js'

const PAD_KEYS = ['Q','W','E','R','A','S','D','F','Z','X','C','V','1','2','3','4']
const PAD_COLORS = [
  '#ff6b00','#ff4081','#00bfff','#00e676',
  '#ffd740','#ce93d8','#80cbc4','#ff8a65',
  '#81d4fa','#a5d6a7','#ffe082','#b39ddb',
  '#f48fb1','#80deea','#bcaaa4','#90a4ae',
]

function WaveformView({ audioBuffer }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !audioBuffer) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width = canvas.offsetWidth
    const H = canvas.height = canvas.offsetHeight
    ctx.clearRect(0, 0, W, H)
    ctx.fillStyle = '#0f0f0f'
    ctx.fillRect(0, 0, W, H)

    const data = audioBuffer.getChannelData(0)
    const step = Math.ceil(data.length / W)
    ctx.strokeStyle = '#ff6b00'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let x = 0; x < W; x++) {
      let min = 1, max = -1
      for (let j = 0; j < step; j++) {
        const v = data[x * step + j] || 0
        if (v < min) min = v
        if (v > max) max = v
      }
      const y1 = ((1 - max) / 2) * H
      const y2 = ((1 - min) / 2) * H
      if (x === 0) ctx.moveTo(x, y1)
      else { ctx.lineTo(x, y1); ctx.lineTo(x, y2) }
    }
    ctx.stroke()
    ctx.strokeStyle = '#333'
    ctx.beginPath()
    ctx.moveTo(0, H / 2)
    ctx.lineTo(W, H / 2)
    ctx.stroke()
  }, [audioBuffer])

  return <canvas ref={canvasRef} className="w-full h-full" />
}

function Pad({ index, pad, color, active, onTrigger, onLoad }) {
  const fileRef = useRef(null)

  return (
    <div className="flex flex-col rounded overflow-hidden" style={{ border: `1px solid ${active ? color : '#2a2a2a'}` }}>
      {/* Waveform */}
      <div
        className="h-12 bg-[#0a0a0a] cursor-pointer"
        style={{ borderBottom: `1px solid #222` }}
        onClick={() => fileRef.current.click()}
      >
        {pad.audioBuffer
          ? <WaveformView audioBuffer={pad.audioBuffer} />
          : <div className="w-full h-full flex items-center justify-center text-[#333] text-xs">клик для загрузки</div>
        }
        <input
          ref={fileRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={e => { if (e.target.files[0]) onLoad(index, e.target.files[0]) }}
        />
      </div>

      {/* Pad button */}
      <button
        className="py-2 font-bold text-sm transition-all active:scale-95 active:brightness-125"
        style={{
          background: active ? color : color + '22',
          color: active ? '#fff' : color,
        }}
        onMouseDown={() => onTrigger(index)}
      >
        <div className="text-[9px] opacity-60 mb-0.5">[{PAD_KEYS[index]}]</div>
        <div className="text-xs truncate px-1">{pad.name || `Pad ${index + 1}`}</div>
      </button>
    </div>
  )
}

export default function Sampler({ onTrigger }) {
  const [pads, setPads] = useState(Array(16).fill(null).map((_, i) => ({
    name: null, audioBuffer: null, volume: 1, pitch: 0, pan: 0, reverse: false, loop: false
  })))
  const [activePad, setActivePad] = useState(null)
  const [selectedPad, setSelectedPad] = useState(0)
  const audioCtxRef = useRef(null)

  const getCtx = () => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = engine.ctx || new (window.AudioContext || window.webkitAudioContext)()
    }
    return audioCtxRef.current
  }

  const loadSample = async (index, file) => {
    const ctx = getCtx()
    const ab = await file.arrayBuffer()
    const audioBuffer = await ctx.decodeAudioData(ab)
    setPads(pads => pads.map((p, i) => i === index ? { ...p, audioBuffer, name: file.name.replace(/\.[^.]+$/, '') } : p))
  }

  const triggerPad = (index) => {
    const pad = pads[index]
    if (!pad.audioBuffer) return
    setActivePad(index)
    setTimeout(() => setActivePad(null), 120)

    const ctx = getCtx()
    if (ctx.state === 'suspended') ctx.resume()

    let buffer = pad.audioBuffer
    if (pad.reverse) {
      const reversed = ctx.createBuffer(buffer.numberOfChannels, buffer.length, buffer.sampleRate)
      for (let c = 0; c < buffer.numberOfChannels; c++) {
        const data = buffer.getChannelData(c).slice().reverse()
        reversed.getChannelData(c).set(data)
      }
      buffer = reversed
    }

    const src = ctx.createBufferSource()
    const gainNode = ctx.createGain()
    const panNode = ctx.createStereoPanner()

    src.buffer = buffer
    src.loop = pad.loop
    src.playbackRate.value = Math.pow(2, pad.pitch / 12)
    gainNode.gain.value = pad.volume
    panNode.pan.value = pad.pan

    src.connect(gainNode)
    gainNode.connect(panNode)
    panNode.connect(engine.masterGain || ctx.destination)

    src.start()
  }

  useEffect(() => {
    const handler = (e) => {
      const idx = PAD_KEYS.indexOf(e.key.toUpperCase())
      if (idx >= 0) triggerPad(idx)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [pads])

  const pad = pads[selectedPad]

  return (
    <div className="flex gap-3 p-3 bg-[#111] h-full overflow-auto">
      {/* Pads grid */}
      <div className="grid grid-cols-4 gap-1.5 flex-shrink-0" style={{width: 340}}>
        {pads.map((p, i) => (
          <div key={i} onClick={() => setSelectedPad(i)}>
            <Pad
              index={i}
              pad={p}
              color={PAD_COLORS[i]}
              active={activePad === i}
              onTrigger={triggerPad}
              onLoad={loadSample}
            />
          </div>
        ))}
      </div>

      {/* Selected pad editor */}
      <div className="flex-1 flex flex-col gap-3 bg-[#161616] rounded border border-[#222] p-4">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full" style={{background: PAD_COLORS[selectedPad]}} />
          <span className="text-sm font-bold text-[#ccc]">
            Pad {selectedPad + 1} — {pads[selectedPad].name || 'пусто'}
          </span>
          <span className="text-[#555] text-xs ml-auto">[{PAD_KEYS[selectedPad]}]</span>
        </div>

        {/* Waveform large */}
        <div className="h-28 bg-[#0a0a0a] rounded border border-[#222] overflow-hidden">
          {pad.audioBuffer
            ? <WaveformView audioBuffer={pad.audioBuffer} />
            : (
              <label className="flex flex-col items-center justify-center h-full cursor-pointer text-[#444] hover:text-[#666] transition-colors">
                <span className="text-2xl mb-1">+</span>
                <span className="text-xs">Перетащи WAV/MP3 или кликни</span>
                <input
                  type="file" accept="audio/*" className="hidden"
                  onChange={e => { if (e.target.files[0]) loadSample(selectedPad, e.target.files[0]) }}
                />
              </label>
            )
          }
        </div>

        {/* Controls */}
        <div className="grid grid-cols-2 gap-4">
          {[
            ['volume', 'Громкость', 0, 1, 0.01],
            ['pitch', 'Питч (полутона)', -24, 24, 1],
            ['pan', 'Панорама', -1, 1, 0.01],
          ].map(([key, label, min, max, step]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[#666] text-xs w-20">{label}</span>
              <input
                type="range" min={min} max={max} step={step}
                value={pad[key]}
                onChange={e => setPads(ps => ps.map((p, i) => i === selectedPad ? {...p, [key]: Number(e.target.value)} : p))}
                className="flex-1" style={{accentColor: PAD_COLORS[selectedPad]}}
              />
              <span className="text-xs text-[#888] w-10 text-right">
                {key === 'pan' ? (pad.pan > 0 ? `+${Math.round(pad.pan*100)}R` : pad.pan < 0 ? `${Math.round(pad.pan*100)}L` : 'C')
                  : key === 'pitch' ? `${pad.pitch > 0 ? '+' : ''}${pad.pitch}st`
                  : Math.round(pad[key] * 100) + '%'}
              </span>
            </div>
          ))}
        </div>

        <div className="flex gap-3 mt-1">
          {[['reverse', '⏮ Реверс'], ['loop', '🔁 Луп']].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setPads(ps => ps.map((p, i) => i === selectedPad ? {...p, [key]: !p[key]} : p))}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                pad[key] ? 'bg-[#ff6b00] text-white' : 'bg-[#222] text-[#888] hover:text-white'
              }`}
            >{label}</button>
          ))}
        </div>
      </div>
    </div>
  )
}
