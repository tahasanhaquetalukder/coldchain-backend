/** @type {import('tailwindcss').Config} */
// Every colour here is a CSS variable from index.css, so the only thing a theme change has to do is
// repoint the variables. No component may name a hex value or a slate-* shade again.
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        page: "var(--page)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        border: "var(--border)",
        sidebar: "var(--sidebar)",
        text: "var(--text)",
        "text-2": "var(--text-2)",
        muted: "var(--muted)",
        primary: "var(--primary)",
        "primary-ink": "var(--primary-ink)",
        "primary-soft": "var(--primary-soft)",
        accent: "var(--accent)",
        "accent-2": "var(--accent-2)",
        safe: "var(--safe)",
        "safe-strong": "var(--safe-strong)",
        "safe-soft": "var(--safe-soft)",
        warn: "var(--warn)",
        "warn-strong": "var(--warn-strong)",
        "warn-soft": "var(--warn-soft)",
        danger: "var(--danger)",
        "danger-strong": "var(--danger-strong)",
        "danger-soft": "var(--danger-soft)",
        neutral: "var(--neutral)",
        "neutral-strong": "var(--neutral-strong)",
        "neutral-soft": "var(--neutral-soft)",
        field: "var(--field)",
        scrim: "var(--scrim)",
        "on-dark": "var(--on-dark)",
        "on-dark-2": "var(--on-dark-2)",
        "on-status": "var(--on-status)",
      },
      // `border` and `divide` on their own are what the tables and cards already use; defaulting
      // them to the token means a theme switch cannot leave a light grey hairline behind.
      borderColor: { DEFAULT: "var(--border)" },
      divideColor: { DEFAULT: "var(--border)" },
      ringColor: { DEFAULT: "var(--accent)" },
      outlineColor: { DEFAULT: "var(--accent)" },
      fontFamily: {
        display: ["Fraunces", "serif"],
        body: ["Public Sans", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
}
