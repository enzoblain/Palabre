import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { ApiError, type Employee, type ProjectDetail } from "../../api";
import { spreadAccounts } from "../../format/settings";
import { useProjectEmployees } from "../../hooks/useProjectEmployees";
import { translate } from "../../i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, SPACING, useColors } from "../../theme";
import { OptionPicker, type Option } from "./OptionPicker";
import { SettingsSection } from "./SettingsSection";
import { StatusText, type Outcome } from "./StatusText";

const AUTOMATIC: null = null; // the picker value of "spread automatically"

type Props = { count: number };

function introFor(count: number): string {
  if (count === 0) return translate("settings.accountsNone");
  if (count === 1) return translate("settings.accountsOne");
  return translate("settings.accountsMany", { count });
}

/** Claude accounts: how many there are, and with several, which one each employee runs on. */
export function AccountsSection({ count }: Props) {
  const colors = useColors();
  const { projects, failed, setAccount } = useProjectEmployees(count > 1);
  const [picking, setPicking] = useState<{ project: ProjectDetail; employee: Employee; effective: number } | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const options: Option<number | null>[] = [
    { value: AUTOMATIC, label: translate("account.auto", { account: picking?.effective ?? 1 }) },
    ...Array.from({ length: count }, (_, index) => ({ value: index + 1, label: translate("account.n", { account: index + 1 }) })),
  ];

  const pick = async (account: number | null) => {
    if (!picking) return;
    const { project, employee } = picking;
    setPicking(null);
    setOutcome(null);
    try {
      await setAccount(project.id, employee.id, account);
    } catch (err) {
      setOutcome({ ok: false, text: err instanceof ApiError ? err.message : String(err) });
    }
  };

  return (
    <SettingsSection title={translate("settings.accounts")} intro={introFor(count)}>
      {failed ? <StatusText outcome={{ ok: false, text: translate("settings.accountsError") }} /> : null}
      <StatusText outcome={outcome} />
      {count > 1
        ? projects?.map((project) => {
            const effective = spreadAccounts(project.employees.map((employee) => employee.account), count);
            return (
              <View key={project.id}>
                <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.project, { color: colors.text }]}>
                  {project.name}
                </Text>
                {project.employees.map((employee, index) => {
                  const label = employee.account === null
                    ? translate("account.auto", { account: effective[index] })
                    : translate("account.n", { account: employee.account });
                  return (
                    <Pressable
                      key={employee.id}
                      accessibilityRole="button"
                      accessibilityLabel={translate("settings.accountFor", { name: employee.name })}
                      accessibilityValue={{ text: label }}
                      onPress={() => setPicking({ project, employee, effective: effective[index] })}
                      style={styles.row}
                    >
                      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.employee, { color: colors.text }]}>
                        {employee.name} · {employee.title}
                      </Text>
                      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.account, { color: colors.link }]}>
                        {label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            );
          })
        : null}
      <OptionPicker
        title={picking ? translate("settings.accountFor", { name: picking.employee.name }) : ""}
        options={options}
        selected={picking?.employee.account ?? AUTOMATIC}
        visible={picking !== null}
        onPick={(account) => void pick(account)}
        onClose={() => setPicking(null)}
      />
    </SettingsSection>
  );
}

const styles = StyleSheet.create({
  project: { fontSize: FONT_SIZE.body, fontWeight: "700", marginTop: SPACING.sm },
  row: { minHeight: MIN_TOUCH_TARGET, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: SPACING.md },
  employee: { flex: 1, fontSize: FONT_SIZE.body },
  account: { fontSize: FONT_SIZE.body },
});
