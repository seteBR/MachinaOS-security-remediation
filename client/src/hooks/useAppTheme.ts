/**
 * useAppTheme — canvas + map theme accessor.
 *
 * Returns a flat colour pack with the same shape the canvas + map +
 * grandfathered-modal call sites expect (`theme.colors.X`,
 * `theme.isDarkMode`). Under light/dark this is identity-pass; under
 * Renaissance / Greek / Edo / Steampunk / Atomic / Cyber / Wasteland
 * / Rot / Plague / Surveillance the base pack (light or dark, picked
 * by `DARK_FAMILY`) gets a small overlay of theme-specific accents
 * (primary, edges, action colours) so canvas selection rings, edge
 * strokes, and action button colours match the theme's identity.
 *
 * This is the production realisation of MIGRATION_PLAYBOOK Wave 1 —
 * the upstream playbook proposes a full per-theme NodePack record;
 * the overlay form here is the same idea expressed without forking
 * the existing 50-key Colors shape, so the existing 14+ call sites
 * keep compiling and the visual delta lives in one place.
 *
 * Adding a new theme override: drop an entry in `THEME_OVERRIDES`
 * with whichever subset of `Colors` keys you want to override. Empty
 * overrides are a no-op (theme falls back to pure light/dark).
 */

import { useMemo } from 'react';
import { useTheme, type ThemeName } from '../contexts/ThemeContext';
import { theme as baseTheme, lightColors, darkColors } from '../styles/theme';

type Colors = typeof lightColors;
/** Loose form for override entries — `lightColors` is `as const`, which
 *  narrows each value to a literal hex string. Themes need to substitute
 *  arbitrary hex / rgba strings, so the override map widens to `string`. */
type ColorOverride = Partial<Record<keyof Colors, string>>;

/** Themes whose canvas + chrome read as dark backgrounds. Mirrors the
 *  DARK_FAMILY in ThemeContext so the two stay in lockstep. */
const DARK_BASE_THEMES: ReadonlySet<ThemeName> = new Set([
  'dark', 'cyber', 'wasteland', 'rot', 'surveillance', 'steampunk',
]);

/** Theme-specific overlays. Each entry is a partial Colors object —
 *  whatever keys appear here override the chosen base pack. Missing
 *  keys fall through to lightColors / darkColors. Hex values come
 *  from the matching client/src/themes/<theme>.css token block. */
const THEME_OVERRIDES: Partial<Record<ThemeName, ColorOverride>> = {
  renaissance: {
    primary: '#b8893c',          // gold accent
    focus: '#d4a030',
    focusRing: 'rgba(212, 160, 48, 0.35)',
    actionRun: '#4a6818',         // olive (success)
    actionDeploy: '#b8893c',      // gold
    actionStop: '#8a1410',        // crimson
    actionSave: '#d4a030',        // gold leaf
    edgeDefault: '#5a3a14',       // ink brown
    edgeSelected: '#d4a030',      // gold
    edgeCompleted: '#4a6818',
    edgeError: '#8a1410',
    edgeMemoryActive: '#b8893c',
    edgeToolActive: '#c08020',
  },

  greek: {
    primary: '#284b82',           // lapis
    focus: '#284b82',
    focusRing: 'rgba(40, 75, 130, 0.3)',
    actionRun: '#6a7a32',         // olive
    actionDeploy: '#284b82',      // lapis
    actionStop: '#7a1a18',        // oxblood
    actionSave: '#c8a040',        // gold
    edgeDefault: '#4a3818',       // dark stone
    edgeSelected: '#284b82',
    edgeCompleted: '#6a7a32',
    edgeError: '#7a1a18',
    edgeMemoryActive: '#284b82',
    edgeToolActive: '#c8a040',
  },

  edo: {
    primary: '#b41e1e',           // vermillion
    focus: '#b41e1e',
    focusRing: 'rgba(180, 30, 30, 0.3)',
    actionRun: '#4a6a3a',         // bamboo
    actionDeploy: '#b41e1e',
    actionStop: '#b41e1e',
    actionSave: '#1a1410',        // sumi
    edgeDefault: '#1a1410',
    edgeSelected: '#b41e1e',
    edgeCompleted: '#4a6a3a',
    edgeError: '#b41e1e',
    edgeMemoryActive: '#b41e1e',
    edgeToolActive: '#c89832',
  },

  steampunk: {
    primary: '#d8a848',           // brass
    focus: '#d8a848',
    focusRing: 'rgba(216, 168, 72, 0.4)',
    actionRun: '#6a8a3a',
    actionDeploy: '#d8a848',
    actionStop: '#8a3a1a',         // rust
    actionSave: '#b8602a',         // copper
    edgeDefault: '#b88838',
    edgeSelected: '#d8a848',
    edgeCompleted: '#6a8a3a',
    edgeError: '#8a3a1a',
    edgeMemoryActive: '#b8602a',
    edgeToolActive: '#d8a848',
  },

  atomic: {
    primary: '#e85a26',           // atomic orange
    focus: '#e85a26',
    focusRing: 'rgba(232, 90, 38, 0.4)',
    actionRun: '#5a8a5a',
    actionDeploy: '#e85a26',
    actionStop: '#e85a26',
    actionSave: '#3a9aa0',         // turquoise
    edgeDefault: '#2a3a4a',        // slate
    edgeSelected: '#e85a26',
    edgeCompleted: '#5a8a5a',
    edgeError: '#e85a26',
    edgeMemoryActive: '#3a9aa0',
    edgeToolActive: '#d8a838',     // mustard
  },

  cyber: {
    primary: '#f51eb6',            // neon magenta
    focus: '#1dd9e5',              // neon cyan
    focusRing: 'rgba(245, 30, 182, 0.5)',
    actionRun: '#26d97a',          // neon green
    actionDeploy: '#f51eb6',
    actionStop: '#ff2050',
    actionSave: '#1dd9e5',
    edgeDefault: '#f51eb6',
    edgeSelected: '#1dd9e5',
    edgeCompleted: '#26d97a',
    edgeError: '#ff2050',
    edgeMemoryActive: '#f51eb6',
    edgeToolActive: '#ffd028',     // neon yellow
  },

  wasteland: {
    primary: '#e88a28',            // ochre
    focus: '#e88a28',
    focusRing: 'rgba(232, 138, 40, 0.45)',
    actionRun: '#8a9028',
    actionDeploy: '#e88a28',
    actionStop: '#b8281a',         // rust red
    actionSave: '#c8d038',         // radioactive
    edgeDefault: '#8a3a18',
    edgeSelected: '#e88a28',
    edgeCompleted: '#8a9028',
    edgeError: '#b8281a',
    edgeMemoryActive: '#e88a28',
    edgeToolActive: '#c8d038',
  },

  rot: {
    primary: '#78c878',            // moss bloom
    focus: '#78c878',
    focusRing: 'rgba(120, 200, 120, 0.4)',
    actionRun: '#78c878',
    actionDeploy: '#e8a838',       // candleflame
    actionStop: '#a83838',
    actionSave: '#e8a838',
    edgeDefault: '#4a6a4a',
    edgeSelected: '#78c878',
    edgeCompleted: '#78c878',
    edgeError: '#a83838',
    edgeMemoryActive: '#e8a838',
    edgeToolActive: '#5898b8',
  },

  plague: {
    primary: '#783c28',            // dried blood
    focus: '#783c28',
    focusRing: 'rgba(120, 60, 40, 0.4)',
    actionRun: '#5a7028',
    actionDeploy: '#783c28',
    actionStop: '#783c28',
    actionSave: '#98a838',          // bile
    edgeDefault: '#2a1c14',
    edgeSelected: '#783c28',
    edgeCompleted: '#5a7028',
    edgeError: '#783c28',
    edgeMemoryActive: '#98a838',
    edgeToolActive: '#4a5868',
  },

  surveillance: {
    primary: '#e82626',             // REC red
    focus: '#e82626',
    focusRing: 'rgba(232, 38, 38, 0.45)',
    actionRun: '#6acc6a',           // phosphor green
    actionDeploy: '#e82626',
    actionStop: '#e82626',
    actionSave: '#6acc6a',
    edgeDefault: '#5a5e62',
    edgeSelected: '#e82626',
    edgeCompleted: '#6acc6a',
    edgeError: '#e82626',
    edgeMemoryActive: '#e82626',
    edgeToolActive: '#5a8cc8',
  },
};

export const useAppTheme = () => {
  const { theme } = useTheme();
  const isDarkMode = DARK_BASE_THEMES.has(theme);

  return useMemo(() => {
    const base = isDarkMode ? darkColors : lightColors;
    const overrides = THEME_OVERRIDES[theme] ?? {};
    return {
      ...baseTheme,
      colors: { ...base, ...overrides } as Colors,
      isDarkMode,
    };
  }, [theme, isDarkMode]);
};
