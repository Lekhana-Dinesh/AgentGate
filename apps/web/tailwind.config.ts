import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0f1722",
        steel: "#6f8294",
        signal: "#0f766e",
        ember: "#b45309",
        danger: "#b42318",
        panel: "#f7f9fb",
      },
      boxShadow: {
        panel: "0 20px 45px rgba(15, 23, 34, 0.08)",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(148,163,184,0.14) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,0.14) 1px, transparent 1px)",
      },
    },
  },
  plugins: [],
};

export default config;

