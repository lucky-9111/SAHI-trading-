/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#ffffff",
        ink: "#111111",          // main text, active pills
        soft: "#f6f6f6",         // info strips, page background on desktop
        panel: "#ffffff",
        panel2: "#ececec",       // segmented-control track, round grey buttons
        line: "#e4e4e4",         // hairlines, card borders
        muted: "#6e6e6e",        // secondary text
        faint: "#9b9b9b",        // disabled segment text
        up: "#1a9a6b",           // positive change text
        down: "#d33a3a",         // negative change text
        buy: "#136b43",          // Buy button
        sell: "#c4382f",         // Sell button
        buybg: "#d8f3e6",
        sellbg: "#fde3e1",
        peach: "#fde4c8",        // bottom info banner
        brand: "#c2177a",        // magenta accent
        accent: "#111111",
      },
      fontFamily: {
        sans: ["Figtree", "Inter", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        serif: ["'Source Serif 4'", "Georgia", "serif"],
      },
      borderRadius: { card: "20px" },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,.03)",
        float: "0 6px 24px rgba(0,0,0,.12)",
        sheet: "0 -8px 32px rgba(0,0,0,.12)",
      },
      keyframes: {
        fade: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        sheet: { from: { transform: "translateY(100%)" }, to: { transform: "translateY(0)" } },
        backdrop: { from: { opacity: "0" }, to: { opacity: "1" } },
        shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } },
        flashUp: { "0%": { backgroundColor: "rgba(26,154,107,.18)" }, "100%": { backgroundColor: "transparent" } },
        flashDown: { "0%": { backgroundColor: "rgba(211,58,58,.16)" }, "100%": { backgroundColor: "transparent" } },
      },
      animation: {
        fade: "fade .28s cubic-bezier(.2,.8,.2,1) backwards",
        sheet: "sheet .32s cubic-bezier(.2,.9,.25,1) backwards",
        backdrop: "backdrop .25s ease backwards",
        shimmer: "shimmer 1.4s linear infinite",
        flashUp: "flashUp .9s ease-out",
        flashDown: "flashDown .9s ease-out",
      },
    },
  },
  plugins: [],
};
