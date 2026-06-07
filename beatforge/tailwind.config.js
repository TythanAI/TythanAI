/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0f0f0f',
        panel: '#1a1a1a',
        panel2: '#222222',
        panel3: '#2a2a2a',
        border: '#333333',
        accent: '#ff6b00',
        'accent-dim': '#cc5500',
        text: '#e0e0e0',
        muted: '#888888',
        active: '#ff6b00',
      }
    }
  },
  plugins: []
}
