import type { Config } from "tailwindcss";

const radius = "0.5rem";

// Liquid Glass color palette inspired by iOS 26 + GitHub Dark/Light
const glassColors = {
  light: {
    background: "hsl(0 0% 100%)",
    foreground: "hsl(220 10% 20%)",
    card: "hsl(0 0% 100%)",
    cardForeground: "hsl(220 10% 20%)",
    primary: "hsl(210 70% 45%)", // GitHub Blue
    primaryForeground: "hsl(0 0% 100%)",
    muted: "hsl(210 30% 90%)",
    mutedForeground: "hsl(210 10% 40%)",
    border: "hsl(210 30% 85%)",
    input: "hsl(0 0% 100%)",
    ring: "hsl(210 70% 60%)",
    destructive: "hsl(0 72% 51%)",
    accent: "hsl(140 60% 45%)", // GitHub Green
    accentForeground: "hsl(0 0% 100%)",
  },
  dark: {
    background: "hsl(220 20% 12%)",
    foreground: "hsl(210 20% 90%)",
    card: "hsl(220 20% 16%)",
    cardForeground: "hsl(210 20% 90%)",
    primary: "hsl(210 70% 55%)", // GitHub Blue adapted for dark
    primaryForeground: "hsl(0 0% 100%)",
    muted: "hsl(210 20% 20%)",
    mutedForeground: "hsl(210 10% 60%)",
    border: "hsl(210 20% 25%)",
    input: "hsl(220 20% 15%)",
    ring: "hsl(210 70% 60%)",
    destructive: "hsl(0 70% 50%)",
    accent: "hsl(140 60% 45%)", // GitHub Green
    accentForeground: "hsl(0 0% 100%)",
  },
};

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ...glassColors.light,
        ...glassColors.dark,
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
      },
      borderRadius: {
        lg: radius,
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [
    // Add custom blur plugin for Liquid Glass effects
    function ({ matchUtilities, theme }) {
      matchUtilities(
        {
          "glass": (opacity?: string) => {
            const glassOpacity = opacity === undefined ? "0.6" : opacity;
            return {
              backdropFilter: `blur(12px) saturate(180%)`,
              WebkitBackdropFilter: `blur(12px) saturate(180%)`,
              backgroundColor: `rgba(255, 255, 255, ${glassOpacity})`,
              border: "1px solid rgba(255, 255, 255, 0.2)",
            };
          },
          "glass-dark": (opacity?: string) => {
            const glassOpacity = opacity === undefined ? "0.4" : opacity;
            return {
              backdropFilter: `blur(12px) saturate(180%)`,
              WebkitBackdropFilter: `blur(12px) saturate(180%)`,
              backgroundColor: `rgba(34, 39, 51, ${glassOpacity})`,
              border: "1px rgba(255, 255, 255, 0.1)",
            };
          },
        },
        { values: theme("colors") }
      );
    },
  ],
} satisfies Config;
