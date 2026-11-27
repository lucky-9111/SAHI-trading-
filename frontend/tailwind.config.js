/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#ffffff",
        soft: "#f7f7f8",
        panel: "#ffffff",
        panel2: "#f1f2f4",
        line: "#e6e8eb",
        muted: "#6b7280",
        up: "#0b9d6c",
        down: "#d93636",
        accent: "#111827",
      },
      fontFamily: { sans: ["Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)" },
    },
  },
  plugins: [],
};
