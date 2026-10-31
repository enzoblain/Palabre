import { useId } from "react";
import type { Personality, PersonalityPreset } from "../api";
import { useI18n } from "../i18n";
import { RANDOM_PRESET, formatLevel, leaningAxes, levelBar } from "../presets";

function PresetCard({ preset, personality }: { preset: PersonalityPreset; personality: Personality }) {
  const { t } = useI18n();
  const style = Object.values(preset.style).join(" · ");
  return (
    <div className="preset-card">
      <strong>{preset.label}</strong>
      <p>{preset.description}</p>
      <ul className="preset-levels">
        {leaningAxes(preset, personality).map(({ label, level }) => (
          <li key={label}>
            <span>{label}</span>
            <span aria-hidden="true" className="preset-bar">{levelBar(level)}</span>
            <span>{formatLevel(level)}</span>
          </li>
        ))}
      </ul>
      {style && <p className="muted">{t("presets.style", { style })}</p>}
      {preset.quirks.length > 0 && (
        <p className="muted">{t("presets.quirks", { count: preset.quirks.length, list: preset.quirks.join(" ") })}</p>
      )}
    </div>
  );
}

/** Radio group to start a member's personality from a preset of the catalog, or draw one at random. */
export function PersonalityPicker({ presets, personality, selected, onSelect }: {
  presets: Record<string, PersonalityPreset>;
  personality: Personality;
  selected: string | null;
  onSelect: (presetKey: string | null) => void;
}) {
  const { t } = useI18n();
  const name = useId();
  const sorted = Object.values(presets);
  const value = selected && presets[selected] ? selected : RANDOM_PRESET;
  const current = value === RANDOM_PRESET ? null : presets[value];

  return (
    <fieldset className="preset-picker">
      <legend>{t("presets.title")}</legend>
      <div className="preset-options">
        {[{ key: RANDOM_PRESET, label: t("presets.random") }, ...sorted].map(({ key, label }) => (
          <label key={key} className="preset-option">
            <input type="radio" name={name} value={key} checked={value === key}
              onChange={() => onSelect(key === RANDOM_PRESET ? null : key)} />
            {label}
          </label>
        ))}
      </div>
      {sorted.length === 0 && <p className="muted">{t("presets.none")}</p>}
      {current ? <PresetCard preset={current} personality={personality} /> : (
        sorted.length > 0 && <p className="muted">{t("presets.randomHelp")}</p>
      )}
    </fieldset>
  );
}
