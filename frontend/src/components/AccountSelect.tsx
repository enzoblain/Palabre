/** Claude account of an agent: automatic (spread evenly) or a fixed one. */
export function AccountSelect({ value, effective, count, onChange }: {
  value: number | null;
  effective: number;
  count: number;
  onChange: (account: number | null) => void;
}) {
  return (
    <select className="account-select" value={value ?? ""} title="Claude account this agent runs on"
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">Auto (account {effective})</option>
      {Array.from({ length: count }, (_, i) => (
        <option key={i + 1} value={i + 1}>Account {i + 1}</option>
      ))}
    </select>
  );
}
