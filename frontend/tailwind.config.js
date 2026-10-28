/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#03060d", 900: "#060b16", 850: "#0a1120", 800: "#0d1628", 700: "#14203a", 600: "#1d2c4d" },
        accent: { DEFAULT: "#22d3ee", soft: "#67e8f9", deep: "#0891b2", blue: "#3b82f6" },
        prio: { critical: "#ef4444", high: "#f87171", medium: "#fb923c", low: "#facc15", unassessed: "#94a3b8", normal: "#34d399" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: { glow: "0 0 0 1px rgba(34,211,238,.25), 0 0 24px -6px rgba(34,211,238,.35)" },
      keyframes: { pulseRing: { "0%": { transform: "scale(.8)", opacity: ".9" }, "100%": { transform: "scale(2.2)", opacity: "0" } } },
      animation: { pulseRing: "pulseRing 1.8s ease-out infinite" },
    },
  },
  plugins: [],
};
