/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Primary backgrounds
        'bg-primary': '#09090B',
        'bg-secondary': '#0D0D0F',
        'bg-sidebar': '#0B0B0D',
        'bg-panel': '#111113',
        'bg-elevated': '#151518',
        
        // Borders
        'border-primary': '#242428',
        'border-subtle': '#1B1B1F',
        
        // Text
        'text-primary': '#F4F4F5',
        'text-secondary': '#A1A1AA',
        'text-muted': '#71717A',
        'text-disabled': '#52525B',
        
        // Accents
        'accent': '#FF6B3D',
        'accent-secondary': '#FF8A5B',
        'accent-muted': 'rgba(255, 107, 61, 0.15)',
        
        // Status
        'success': '#22C55E',
        'warning': '#F59E0B',
        'error': '#EF4444',
        'info': '#60A5FA',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      fontSize: {
        'page-title': ['24px', { lineHeight: '32px', fontWeight: '600' }],
        'section-title': ['16px', { lineHeight: '24px', fontWeight: '600' }],
        'body': ['13px', { lineHeight: '20px' }],
        'body-sm': ['12px', { lineHeight: '18px' }],
        'metadata': ['11px', { lineHeight: '16px' }],
        'table': ['12px', { lineHeight: '18px' }],
        'code': ['12px', { lineHeight: '18px', fontFamily: 'JetBrains Mono, monospace' }],
      },
      spacing: {
        '0': '0',
        '1': '4px',
        '2': '8px',
        '3': '12px',
        '4': '16px',
        '5': '20px',
        '6': '24px',
        '8': '32px',
      },
      borderRadius: {
        'panel': '8px',
        'panel-lg': '10px',
      },
      boxShadow: {
        'subtle': '0 1px 3px rgba(0, 0, 0, 0.3)',
        'drawer': '0 4px 20px rgba(0, 0, 0, 0.4)',
      },
      transitionDuration: {
        'fast': '120ms',
        'normal': '160ms',
        'slow': '200ms',
      },
    },
  },
  plugins: [],
}