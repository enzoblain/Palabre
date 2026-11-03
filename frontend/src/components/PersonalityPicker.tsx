import { useId, useState } from "react";
import type { PersonalityPreset } from "../api";
import { useI18n } from "../i18n";
import { RANDOM_PRESET, filterPresets } from "../presets";

/** Radio list to give a member a personality of the catalog (name and one-line description), searchable, or a random one. */
export function PersonalityPicker({ presets, selected, onSelect }: {
  presets: Record<string, PersonalityPreset>;
  selected: string | null;
  onSelect: (presetKey: string | null) => void;
}) {
  const { t } = useI18n();
  const name = useId();
  const [query, setQuery] = useState("");
  const matches = filterPresets(presets, query);
  const value = selected && presets[selected] ? selected : RANDOM_PRESET;
  const options = [{ key: RANDOM_PRESET, label: t("presets.random"), description: t("presets.randomHelp") }, ...matches];

  return (
    <fieldset className="preset-picker">
      <legend>{t("presets.title")}</legend>
      <input type="search" value={query} placeholder={t("presets.searchPlaceholder")}
        aria-label={t("presets.searchAria")} onChange={(e) => setQuery(e.target.value)} />
      <div className="preset-options">
        {options.map(({ key, label, description }) => (
          <label key={key} className={value === key ? "preset-option selected" : "preset-option"}>
            <input type="radio" name={name} value={key} checked={value === key}
              onChange={() => onSelect(key === RANDOM_PRESET ? null : key)} />
            <span>
              <strong>{label}</strong>
              <span className="muted preset-description">{description}</span>
            </span>
          </label>
        ))}
      </div>
      <p role="status" className="muted">
        {Object.keys(presets).length === 0 ? t("presets.none") : matches.length === 0 ? t("presets.noMatch") : ""}
      </p>
    </fieldset>
  );
}
