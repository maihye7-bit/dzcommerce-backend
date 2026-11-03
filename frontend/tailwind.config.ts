import type { Config } from "tailwindcss";

const withOpacity = (token: string) => `hsl(var(--${token}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: withOpacity("background"),
        sidebar: withOpacity("sidebar"),
        surface: withOpacity("surface"),
        "surface-elevated": withOpacity("surface-elevated"),
        foreground: withOpacity("foreground"),
        border: withOpacity("border"),
        input: withOpacity("input"),
        ring: withOpacity("ring"),
        primary: {
          DEFAULT: withOpacity("primary"),
          foreground: withOpacity("primary-foreground"),
        },
        muted: {
          DEFAULT: withOpacity("muted"),
          foreground: withOpacity("muted-foreground"),
        },
        card: {
          DEFAULT: withOpacity("surface"),
          foreground: withOpacity("foreground"),
        },
        accent: {
          DEFAULT: withOpacity("accent"),
          foreground: withOpacity("accent-foreground"),
        },
        destructive: withOpacity("destructive"),
        success: withOpacity("success"),
        warning: withOpacity("warning"),
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 0.125rem)",
        sm: "calc(var(--radius) - 0.25rem)",
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "Noto Sans Arabic",
          "Segoe UI",
          "Tahoma",
          "Arial",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
