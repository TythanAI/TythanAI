import React, { useRef, useState, useEffect, useCallback } from 'react'

const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
const TOTAL_NOTES = 88
const BASE_MIDI = 21 // A0

function midiToName(midi) {
  const note = NOTE_NAMES[(midi - 12) % 12]
  const oct = Math.floor((midi - 12) / 12)
  return `${note}${oct}`
}

function nameToMidi(name) {
  const m = name.match(/^([A-G]#?)(-?\d)$/)
  if (!m) return 60
  const idx = NOTE_NAMES.indexOf(m[1])
  return idx + (parseInt(m[2]) + 1) * 12
}

const KEY_HEIGHT = 14
const BEAT_WIDTH = 80
const LEFT_PAD = 52

export default function PianoRoll({ track, notes, onChange, bpm }) {
  const canvasRef = useRef(null)
  const velCanvasRef = useRef(null)
  const [tool, setTool] = useState('draw')
  const [snap, setSnap] = useState(0.25) // quarter note
  const [zoom, setZoom] = useState(1)
  const [scrollX, setScrollX] = useState(0)
  const [scrollY, setScrollY] = useState(KEY_HEIGHT * 30)
  const [dragging, setDragging] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const containerRef = useRef(null)

  const totalBars = 4
  const totalBeats = totalBars * 4
  const gridW = BEAT_WIDTH * zoom
  const noteH = KEY_HEIGHT
  const totalH = TOTAL_NOTES * noteH

  const snapVal = (v) => Math.round(v / snap) * snap

  const posToNote = useCallback((x, y) => {
    const beat = (x - LEFT_PAD + scrollX) / gridW
    const row = Math.floor((y + scrollY) / noteH)
    const midi = BASE_MIDI + TOTAL_NOTES - 1 - row
    return { beat: snapVal(beat), midi, note: midiToName(midi) }
  }, [scrollX, scrollY, gridW, noteH, snap])

  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height

    ctx.clearRect(0, 0, W, H)

    // Background
    ctx.fillStyle = '#0f0f0f'
    ctx.fillRect(0, 0, W, H)

    // Draw piano keys
    for (let i = 0; i < TOTAL_NOTES; i++) {
      const midi = BASE_MIDI + TOTAL_NOTES - 1 - i
      const y = i * noteH - scrollY
      if (y < -noteH || y > H) continue
      const name = NOTE_NAMES[(midi - 12) % 12]
      const isBlack = name.includes('#')
      ctx.fillStyle = isBlack ? '#1a1a1a' : '#252525'
      ctx.fillRect(0, y, LEFT_PAD, noteH - 1)
      if (name === 'C') {
        ctx.fillStyle = '#ff6b00'
        ctx.font = '9px monospace'
        ctx.fillText(midiToName(midi), 2, y + noteH - 3)
      }
      ctx.fillStyle = isBlack ? '#333' : '#2a2a2a'
      ctx.fillRect(LEFT_PAD - 12, y + 1, 12, noteH - 3)
    }

    // Vertical line (piano edge)
    ctx.strokeStyle = '#333'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(LEFT_PAD, 0)
    ctx.lineTo(LEFT_PAD, H)
    ctx.stroke()

    // Grid rows
    for (let i = 0; i < TOTAL_NOTES; i++) {
      const midi = BASE_MIDI + TOTAL_NOTES - 1 - i
      const y = i * noteH - scrollY
      if (y < -noteH || y > H) continue
      const name = NOTE_NAMES[(midi - 12) % 12]
      const isBlack = name.includes('#')
      ctx.fillStyle = isBlack ? '#141414' : '#181818'
      ctx.fillRect(LEFT_PAD, y, W - LEFT_PAD, noteH - 1)
      if (name === 'C') {
        ctx.strokeStyle = '#2a2a2a'
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.moveTo(LEFT_PAD, y)
        ctx.lineTo(W, y)
        ctx.stroke()
      }
    }

    // Grid columns (bars/beats)
    for (let b = 0; b <= totalBeats; b++) {
      const x = LEFT_PAD + b * gridW - scrollX
      if (x < LEFT_PAD || x > W) continue
      const isBar = b % 4 === 0
      ctx.strokeStyle = isBar ? '#2a2a2a' : '#1e1e1e'
      ctx.lineWidth = isBar ? 1.5 : 0.5
      ctx.beginPath()
      ctx.moveTo(x, 0)
      ctx.lineTo(x, H)
      ctx.stroke()
      if (isBar) {
        ctx.fillStyle = '#444'
        ctx.font = '10px monospace'
        ctx.fillText(`${b/4 + 1}`, x + 2, 12)
      }
    }

    // Sub-grid (snap lines)
    const stepsPerBeat = 1 / snap
    for (let b = 0; b < totalBeats; b++) {
      for (let s = 1; s < stepsPerBeat; s++) {
        const x = LEFT_PAD + (b + s * snap) * gridW - scrollX
        if (x < LEFT_PAD || x > W) continue
        ctx.strokeStyle = '#1a1a1a'
        ctx.lineWidth = 0.5
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, H)
        ctx.stroke()
      }
    }

    // Notes
    notes.forEach((n, idx) => {
      const row = BASE_MIDI + TOTAL_NOTES - 1 - nameToMidi(n.note)
      const x = LEFT_PAD + n.start * gridW - scrollX
      const y = row * noteH - scrollY
      const w = Math.max(4, n.duration * gridW - 1)
      if (x + w < LEFT_PAD || x > W || y + noteH < 0 || y > H) return

      const isSelected = selected.has(idx)
      ctx.fillStyle = isSelected ? '#ffffff' : '#ff6b00'
      ctx.globalAlpha = n.velocity / 127
      ctx.fillRect(x, y + 1, w, noteH - 2)
      ctx.globalAlpha = 1

      ctx.strokeStyle = isSelected ? '#fff' : '#ff8f00'
      ctx.lineWidth = 1
      ctx.strokeRect(x, y + 1, w, noteH - 2)

      // Resize handle
      ctx.fillStyle = isSelected ? '#aaa' : '#cc5500'
      ctx.fillRect(x + w - 3, y + 2, 3, noteH - 4)
    })

    // Cursor line
    ctx.strokeStyle = '#ff6b0044'
    ctx.lineWidth = 1
    ctx.setLineDash([4, 4])
    ctx.beginPath()
    ctx.moveTo(LEFT_PAD, 0)
    ctx.lineTo(LEFT_PAD, H)
    ctx.stroke()
    ctx.setLineDash([])
  }, [notes, scrollX, scrollY, gridW, noteH, selected, snap, totalBeats])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const observer = new ResizeObserver(() => {
      canvas.width = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      draw()
    })
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [draw])

  useEffect(() => { draw() }, [draw])

  const onMouseDown = (e) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    if (x < LEFT_PAD) return

    const beat = snapVal((x - LEFT_PAD + scrollX) / gridW)
    const row = Math.floor((y + scrollY) / noteH)
    const midi = BASE_MIDI + TOTAL_NOTES - 1 - row
    const noteName = midiToName(midi)

    if (tool === 'draw') {
      if (e.button === 2) {
        // Right click = delete
        const idx = notes.findIndex(n => {
          const nr = BASE_MIDI + TOTAL_NOTES - 1 - nameToMidi(n.note)
          const nx = LEFT_PAD + n.start * gridW - scrollX
          const ny = nr * noteH - scrollY
          const nw = n.duration * gridW
          return x >= nx && x <= nx + nw && y >= ny && y <= ny + noteH
        })
        if (idx >= 0) onChange(notes.filter((_, i) => i !== idx))
        return
      }

      // Check if clicking on existing note resize handle
      let resizeIdx = -1
      for (let i = notes.length - 1; i >= 0; i--) {
        const n = notes[i]
        const nr = BASE_MIDI + TOTAL_NOTES - 1 - nameToMidi(n.note)
        const nx = LEFT_PAD + n.start * gridW - scrollX
        const ny = nr * noteH - scrollY
        const nw = n.duration * gridW
        if (x >= nx + nw - 5 && x <= nx + nw + 2 && y >= ny && y <= ny + noteH) {
          resizeIdx = i
          break
        }
      }

      if (resizeIdx >= 0) {
        setDragging({ type: 'resize', idx: resizeIdx, startX: x, origDur: notes[resizeIdx].duration })
        return
      }

      // New note
      const newNote = { note: noteName, start: beat, duration: snap, velocity: 100 }
      onChange([...notes, newNote])
      setDragging({ type: 'new', idx: notes.length, startX: x, beat })

    } else if (tool === 'select') {
      const clickedIdx = notes.findIndex(n => {
        const nr = BASE_MIDI + TOTAL_NOTES - 1 - nameToMidi(n.note)
        const nx = LEFT_PAD + n.start * gridW - scrollX
        const ny = nr * noteH - scrollY
        const nw = n.duration * gridW
        return x >= nx && x <= nx + nw && y >= ny && y <= ny + noteH
      })
      if (clickedIdx >= 0) {
        const newSel = e.shiftKey ? new Set([...selected, clickedIdx]) : new Set([clickedIdx])
        setSelected(newSel)
        setDragging({ type: 'move', startX: x, startY: y, startNotes: notes.map(n => ({...n})), sel: newSel })
      } else {
        setSelected(new Set())
      }

    } else if (tool === 'delete') {
      const idx = notes.findIndex(n => {
        const nr = BASE_MIDI + TOTAL_NOTES - 1 - nameToMidi(n.note)
        const nx = LEFT_PAD + n.start * gridW - scrollX
        const ny = nr * noteH - scrollY
        const nw = n.duration * gridW
        return x >= nx && x <= nx + nw && y >= ny && y <= ny + noteH
      })
      if (idx >= 0) onChange(notes.filter((_, i) => i !== idx))
    }
  }

  const onMouseMove = (e) => {
    if (!dragging) return
    const rect = canvasRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    if (dragging.type === 'resize') {
      const dx = (x - dragging.startX) / gridW
      const newDur = Math.max(snap, snapVal(dragging.origDur + dx))
      const updated = notes.map((n, i) => i === dragging.idx ? { ...n, duration: newDur } : n)
      onChange(updated)
    } else if (dragging.type === 'new') {
      const newBeat = snapVal((x - LEFT_PAD + scrollX) / gridW)
      const dur = Math.max(snap, newBeat - dragging.beat + snap)
      const updated = notes.map((n, i) => i === dragging.idx ? { ...n, duration: dur } : n)
      onChange(updated)
    } else if (dragging.type === 'move' && dragging.sel.size > 0) {
      const dx = (x - dragging.startX) / gridW
      const dy = Math.round((y - dragging.startY) / noteH)
      const updated = dragging.startNotes.map((n, i) => {
        if (!dragging.sel.has(i)) return n
        const newMidi = nameToMidi(n.note) - dy
        const clamped = Math.max(BASE_MIDI, Math.min(BASE_MIDI + TOTAL_NOTES - 1, newMidi))
        return { ...n, start: Math.max(0, snapVal(n.start + dx)), note: midiToName(clamped) }
      })
      onChange(updated)
    }
  }

  const onMouseUp = () => setDragging(null)

  const onKeyDown = (e) => {
    if (e.ctrlKey && e.key === 'a') {
      e.preventDefault()
      setSelected(new Set(notes.map((_, i) => i)))
    }
    if (e.key === 'Delete' && selected.size > 0) {
      onChange(notes.filter((_, i) => !selected.has(i)))
      setSelected(new Set())
    }
  }

  const onWheel = (e) => {
    e.preventDefault()
    if (e.shiftKey) {
      setScrollX(x => Math.max(0, x + e.deltaY))
    } else {
      setScrollY(y => Math.max(0, Math.min(totalH - 200, y + e.deltaY)))
    }
  }

  return (
    <div className="flex flex-col h-full bg-[#0f0f0f]" onKeyDown={onKeyDown} tabIndex={0}>
      {/* Toolbar */}
      <div className="flex items-center gap-3 px-3 py-1.5 bg-[#141414] border-b border-[#2a2a2a]">
        <span className="text-[#888] text-xs">
          {track ? `Piano Roll — ${track}` : 'Piano Roll'}
        </span>

        <div className="flex gap-1 ml-2">
          {[['draw','✏️ Рисовать'],['select','⬜ Выбрать'],['delete','🗑️ Удалить']].map(([t, label]) => (
            <button
              key={t}
              onClick={() => setTool(t)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${
                tool === t ? 'bg-[#ff6b00] text-white' : 'bg-[#222] text-[#888] hover:text-white'
              }`}
            >{label}</button>
          ))}
        </div>

        <div className="flex items-center gap-2 ml-2">
          <span className="text-[#666] text-xs">Snap:</span>
          {[[1,'1/4'],[0.5,'1/8'],[0.25,'1/16'],[0.125,'1/32']].map(([v, label]) => (
            <button
              key={v}
              onClick={() => setSnap(v)}
              className={`px-2 py-0.5 rounded text-xs transition-colors ${
                snap === v ? 'bg-[#333] text-[#ff6b00]' : 'bg-[#1a1a1a] text-[#666] hover:text-white'
              }`}
            >{label}</button>
          ))}
        </div>

        <div className="flex items-center gap-2 ml-2">
          <span className="text-[#666] text-xs">Zoom:</span>
          <input
            type="range" min={0.3} max={3} step={0.1} value={zoom}
            onChange={e => setZoom(Number(e.target.value))}
            className="w-20" style={{accentColor:'#ff6b00'}}
          />
        </div>

        <span className="text-[#555] text-xs ml-auto">Ctrl+A = выбрать все | Del = удалить | Scroll = прокрутка</span>
      </div>

      {/* Canvas */}
      <div className="flex-1 relative overflow-hidden">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
          style={{ cursor: tool === 'delete' ? 'crosshair' : tool === 'select' ? 'default' : 'crosshair' }}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onContextMenu={e => e.preventDefault()}
          onWheel={onWheel}
        />
      </div>

      {/* Velocity bar */}
      <div className="h-16 bg-[#0a0a0a] border-t border-[#222] px-2 py-1">
        <div className="flex items-end gap-px h-full" style={{paddingLeft: LEFT_PAD}}>
          {notes.map((n, i) => {
            const x = n.start * gridW - scrollX
            return (
              <div
                key={i}
                className="w-1.5 bg-[#ff6b00] rounded-t cursor-ns-resize opacity-80 hover:opacity-100"
                style={{ height: `${n.velocity / 127 * 100}%`, marginLeft: Math.max(0, x - 2) }}
                title={`Velocity: ${n.velocity}`}
              />
            )
          })}
        </div>
      </div>
    </div>
  )
}
