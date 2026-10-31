import { useI18n } from "../i18n";

/** Claude account of an agent: automatic (spread evenly) or a fixed one. */
export function AccountSelect({ value, effective, count, onChange }: {
  value: number | null;
  effective: number;
  count: number;
  onChange: (account: number | null) => void;
}) {
  const { t } = useI18n();
  return (
    <select className="account-select" value={value ?? ""} title={t("account.title")}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{t("account.auto", { account: effective })}</option>
      {Array.from({ length: count }, (_, i) => (
        <option key={i + 1} value={i + 1}>{t("account.n", { account: i + 1 })}</option>
      ))}
    </select>
  );
}
