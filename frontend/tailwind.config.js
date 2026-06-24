/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Near-black with a faint violet tint — the "AI control room at night" base
        ink: {
          900: '#0B0A10',
          800: '#15131F',
          700: '#262335',
          600: '#383350',
          500: '#5C5775',
          400: '#9490AC',
        },
        bone: {
          DEFAULT: '#F1EFF7',
          50: '#FFFFFF',
          200: '#D6D3E3',
        },
        // Primary accent — vivid violet (was coral). Token name kept for
        // minimal call-site churn; only the value changed.
        coral: {
          DEFAULT: '#7C5CFC',
          dark: '#6344D9',
        },
        // Used sparingly — only for "agent active right now" / in-progress
        live: '#FFA557',
      },
      fontFamily: {
        // Clean sans throughout — matches the reference's all-sans dashboard
        // look. Kept as a separate token (vs. `sans`) for weight/tracking
        // hierarchy on headlines, not a different typeface.
        display: ['"Inter Tight"', 'system-ui', 'sans-serif'],
        sans: ['"Inter Tight"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.04em',
      },
      keyframes: {
        livePulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        handoff: {
          '0%': { transform: 'translateX(-100%)', opacity: '0' },
          '50%': { opacity: '1' },
          '100%': { transform: 'translateX(100%)', opacity: '0' },
        },
        shimmer: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(220%)' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
      },
      animation: {
        'live-pulse': 'livePulse 1.4s ease-in-out infinite',
        'slide-up': 'slideUp 240ms cubic-bezier(0.2, 0.7, 0.3, 1)',
        'handoff': 'handoff 1.6s ease-in-out',
        'shimmer': 'shimmer 1.6s ease-in-out infinite',
        'glow-pulse': 'glowPulse 2.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};
