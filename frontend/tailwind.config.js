/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Semantic, CSS-var driven (dark-first; light theme overrides the vars).
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        surface2: 'var(--surface-2)',
        line: 'var(--border)',
        line2: 'var(--border-2)',
        txt: 'var(--txt)',
        muted: 'var(--muted)',
        faint: 'var(--faint)',
        brand: { DEFAULT: 'var(--brand)', hover: 'var(--brand-hover)', soft: 'var(--brand-soft)' },
        teal: 'var(--accent)',
        danger: { DEFAULT: 'var(--danger)', soft: 'var(--danger-soft)' },
        success: 'var(--success)',
        warn: 'var(--warning)',

        // Aurora identity hues (12, themed for dark+light via CSS vars). Use as
        // text-h-rose / bg-h-rose-soft / border-h-rose; runtime-dynamic hues go
        // through hueStyle() + .vo-chip-hue/.vo-accent instead.
        h: {
          rose: { DEFAULT: 'var(--hue-rose)', soft: 'var(--hue-rose-soft)' },
          orange: { DEFAULT: 'var(--hue-orange)', soft: 'var(--hue-orange-soft)' },
          amber: { DEFAULT: 'var(--hue-amber)', soft: 'var(--hue-amber-soft)' },
          lime: { DEFAULT: 'var(--hue-lime)', soft: 'var(--hue-lime-soft)' },
          emerald: { DEFAULT: 'var(--hue-emerald)', soft: 'var(--hue-emerald-soft)' },
          teal: { DEFAULT: 'var(--hue-teal)', soft: 'var(--hue-teal-soft)' },
          cyan: { DEFAULT: 'var(--hue-cyan)', soft: 'var(--hue-cyan-soft)' },
          sky: { DEFAULT: 'var(--hue-sky)', soft: 'var(--hue-sky-soft)' },
          indigo: { DEFAULT: 'var(--hue-indigo)', soft: 'var(--hue-indigo-soft)' },
          violet: { DEFAULT: 'var(--hue-violet)', soft: 'var(--hue-violet-soft)' },
          fuchsia: { DEFAULT: 'var(--hue-fuchsia)', soft: 'var(--hue-fuchsia-soft)' },
          pink: { DEFAULT: 'var(--hue-pink)', soft: 'var(--hue-pink-soft)' },
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system',
          'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      // ---- Type scale (the vertical-rhythm system; see index.css §type) ----
      // display > title (page h1) > heading (panel h2) > body > caption > micro.
      // Prefer these over ad-hoc text-[Npx] so pages stay on one rhythm.
      fontSize: {
        display: ['2.125rem', { lineHeight: '1.15', letterSpacing: '-0.025em', fontWeight: '700' }],
        title: ['1.625rem', { lineHeight: '1.2', letterSpacing: '-0.02em', fontWeight: '700' }],
        heading: ['1.0625rem', { lineHeight: '1.35', letterSpacing: '-0.01em', fontWeight: '600' }],
        body: ['0.9375rem', { lineHeight: '1.55' }],
        caption: ['0.8125rem', { lineHeight: '1.45' }],
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.05em' }],
      },
      borderRadius: { control: '0.625rem', card: '0.875rem', pane: '1.25rem' },
      boxShadow: {
        soft: '0 1px 2px rgba(0,0,0,0.25), 0 8px 24px rgba(0,0,0,0.20)',
        pop: '0 8px 40px rgba(0,0,0,0.45)',
        glow: '0 0 0 1px var(--brand-soft), 0 8px 30px rgba(224,177,58,0.18)',
        lift: '0 2px 6px rgba(0,0,0,0.18), 0 12px 32px rgba(0,0,0,0.22)',
      },
      // ---- Motion system (mirrors the CSS vars in index.css §motion) ----
      transitionTimingFunction: {
        out: 'cubic-bezier(0.16, 1, 0.3, 1)', // expo-out: fast start, long settle
        spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)', // playful overshoot
      },
      keyframes: {
        'fade-in': { '0%': { opacity: '0', transform: 'translateY(4px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        'slide-in': { '0%': { opacity: '0', transform: 'translateY(6px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        rise: { '0%': { opacity: '0', transform: 'translateY(12px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        'pop-in': { '0%': { opacity: '0', transform: 'scale(0.92) translateY(8px)' }, '100%': { opacity: '1', transform: 'scale(1) translateY(0)' } },
        'scale-in': { '0%': { opacity: '0', transform: 'scale(0.6)' }, '100%': { opacity: '1', transform: 'scale(1)' } },
        'drawer-in': { '0%': { transform: 'translateX(-100%)' }, '100%': { transform: 'translateX(0)' } },
        pulsedot: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.3' } },
        shimmer: { '0%': { backgroundPosition: '-400px 0' }, '100%': { backgroundPosition: '400px 0' } },
        'dial-in': { '0%': { strokeDashoffset: 'var(--dial-start, 283)' }, '100%': { strokeDashoffset: 'var(--dial-end, 0)' } },
      },
      animation: {
        'fade-in': 'fade-in 0.25s cubic-bezier(0.16,1,0.3,1)',
        'slide-in': 'slide-in 0.22s cubic-bezier(0.16,1,0.3,1)',
        rise: 'rise 0.45s cubic-bezier(0.16,1,0.3,1) both',
        'pop-in': 'pop-in 0.35s cubic-bezier(0.16,1,0.3,1) both',
        'scale-in': 'scale-in 0.3s cubic-bezier(0.34,1.56,0.64,1) both',
        'drawer-in': 'drawer-in 0.28s cubic-bezier(0.16,1,0.3,1) both',
        pulsedot: 'pulsedot 1.4s ease-in-out infinite',
        shimmer: 'shimmer 1.4s linear infinite',
      },
    },
  },
  plugins: [],
}
