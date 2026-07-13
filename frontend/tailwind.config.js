/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        dark: {
          900: '#090d16',
          800: '#0f172a',
          700: '#1e293b',
          600: '#334155',
        },
        brand: {
          blue: '#3b82f6',
          cyan: '#06b6d4',
          green: '#10b981',
          orange: '#f97316',
          red: '#ef4444',
          purple: '#a855f7',
        },
        transcope: {
          canvas: '#CECEC9',
          bg: '#101114',
          card: '#16171B',
          cardHover: '#1D1E24',
          border: '#222328',
          text: {
            primary: '#FFFFFF',
            secondary: '#8B8C8F',
            muted: '#525356',
          },
          accent: {
            electronics: '#CCA43B',
            medical: '#00F5D4',
            food: '#A0A0A0',
            docs: '#8E8E93',
          }
        }
      },
      fontFamily: {
        sans: ['Outfit', 'Inter', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        glass: '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
        'glass-glow': '0 0 20px 0 rgba(59, 130, 246, 0.15)',
        'dashboard': '0 20px 50px rgba(0, 0, 0, 0.4)',
      },
      backdropBlur: {
        xs: '2px',
      }
    },
  },
  plugins: [],
}
