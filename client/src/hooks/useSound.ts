/**
 * useSound — React glue for the per-theme WebAudio engine.
 *
 * `useSoundSync()` mounts once at the Dashboard root. It:
 *   - mirrors the `soundEnabled` Zustand slice into `Sounds.setEnabled()`
 *   - reads `--sound-pack` from `:root` after every theme change and
 *     calls `Sounds.setPack(...)` so the active pack tracks the active
 *     theme without per-component wiring
 *
 * `useSound()` is the lightweight handle every event handler uses:
 *
 *     const play = useSound();
 *     <button onClick={() => { play('click'); onSave(); }} />
 *
 * Adding a new sound event: extend `SoundEvent` in lib/sound.ts, add
 * an entry per pack, and fire `play('<event>')` from the relevant
 * handler. No additional wiring here.
 */

import { useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { useAppStore } from '../store/useAppStore';
import { Sounds, type SoundPackName, type SoundEvent } from '../lib/sound';

const VALID_PACKS: ReadonlySet<SoundPackName> = new Set([
  'none', 'parchment', 'marble', 'ink', 'clockwork', 'vibraphone',
  'terminal', 'scrap', 'crypt', 'bell', 'telex',
]);

function readSoundPack(): SoundPackName {
  if (typeof document === 'undefined') return 'none';
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--sound-pack')
    .trim()
    .replace(/['"]/g, '');
  return VALID_PACKS.has(raw as SoundPackName) ? (raw as SoundPackName) : 'none';
}

/** Mount once at the Dashboard root. */
export function useSoundSync(): void {
  const { theme } = useTheme();
  const enabled = useAppStore((s) => s.soundEnabled);

  useEffect(() => {
    Sounds.setEnabled(enabled);
  }, [enabled]);

  useEffect(() => {
    Sounds.setPack(readSoundPack());
  }, [theme]);
}

/** Play handle. Returns the same `Sounds.play` reference each render. */
export function useSound(): (event: SoundEvent) => void {
  return Sounds.play;
}
