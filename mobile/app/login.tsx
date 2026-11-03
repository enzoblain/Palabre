import { type ComponentRef, useRef, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { ApiError } from "../src/api";
import { translate } from "../src/i18n";
import { useSession } from "../src/session";
import { BUTTON_HEIGHT, FONT_SIZE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../src/theme";

const DEFAULT_DEVICE_NAME = Platform.OS === "ios" ? "iPhone" : "Android";

/** Sign-in: server address, access code and device name, then pairs the phone. */
export default function LoginScreen() {
  const colors = useColors();
  const { server: lastServer, expired, signIn } = useSession();
  const [server, setServer] = useState(lastServer);
  const [accessCode, setAccessCode] = useState("");
  const [deviceName, setDeviceName] = useState(DEFAULT_DEVICE_NAME);
  const [codeVisible, setCodeVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const accessCodeInput = useRef<ComponentRef<typeof TextInput>>(null);
  const deviceNameInput = useRef<ComponentRef<typeof TextInput>>(null);

  const canSubmit = !submitting && server.trim() !== "" && accessCode !== "" && deviceName.trim() !== "";

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      await signIn(server, accessCode, deviceName);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : translate("api.error", { status: 0 }));
      setAccessCode("");
      setSubmitting(false);
    }
  }

  function submitFromKeyboard() {
    if (canSubmit) void submit();
  }

  const inputStyle = [styles.input, { backgroundColor: colors.secondaryBackground, color: colors.text }];
  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text accessibilityRole="header" style={[styles.title, { color: colors.text }]}>
          {translate("login.title")}
        </Text>
        {expired && !error ? <Text style={{ color: colors.secondaryText }}>{translate("login.expired")}</Text> : null}

        <Text style={[styles.label, { color: colors.text }]}>{translate("login.server")}</Text>
        <TextInput
          accessibilityLabel={translate("login.server")}
          style={inputStyle}
          value={server}
          onChangeText={setServer}
          placeholder="https://"
          placeholderTextColor={colors.secondaryText}
          keyboardType="url"
          textContentType="URL"
          autoCapitalize="none"
          autoCorrect={false}
          editable={!submitting}
          returnKeyType="next"
          blurOnSubmit={false}
          onSubmitEditing={() => accessCodeInput.current?.focus()}
        />

        <Text style={[styles.label, { color: colors.text }]}>{translate("login.token")}</Text>
        <View style={styles.row}>
          <TextInput
            ref={accessCodeInput}
            accessibilityLabel={translate("login.token")}
            style={[...inputStyle, styles.flex]}
            value={accessCode}
            onChangeText={setAccessCode}
            secureTextEntry={!codeVisible}
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="off"
            textContentType="none"
            editable={!submitting}
            returnKeyType="next"
            blurOnSubmit={false}
            onSubmitEditing={() => deviceNameInput.current?.focus()}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={translate(codeVisible ? "login.hideToken" : "login.showToken")}
            onPress={() => setCodeVisible((visible) => !visible)}
            style={styles.eye}
          >
            <Text style={{ color: colors.text, fontSize: FONT_SIZE.body, textDecorationLine: "underline" }}>
              {translate(codeVisible ? "login.hideToken" : "login.showToken")}
            </Text>
          </Pressable>
        </View>
        <Text style={[styles.help, { color: colors.secondaryText }]}>{translate("login.help")}</Text>

        <Text style={[styles.label, { color: colors.text }]}>{translate("login.deviceName")}</Text>
        <TextInput
          ref={deviceNameInput}
          accessibilityLabel={translate("login.deviceName")}
          style={inputStyle}
          value={deviceName}
          onChangeText={setDeviceName}
          maxLength={100}
          editable={!submitting}
          returnKeyType="go"
          onSubmitEditing={submitFromKeyboard}
        />

        {error ? (
          <Text accessibilityRole="alert" accessibilityLiveRegion="polite" style={[styles.error, { color: colors.error }]}>
            {`⚠︎ ${error}`}
          </Text>
        ) : null}

        <Pressable
          accessibilityRole="button"
          accessibilityState={{ disabled: !canSubmit, busy: submitting }}
          disabled={!canSubmit}
          onPress={submit}
          style={[styles.button, { backgroundColor: colors.sentBubble, opacity: canSubmit ? 1 : 0.5 }]}
        >
          {submitting ? <ActivityIndicator color={colors.sentBubbleText} /> : null}
          <Text style={[styles.buttonText, { color: colors.sentBubbleText }]}>
            {translate(submitting ? "login.submitting" : "login.submit")}
          </Text>
        </Pressable>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: SPACING.lg, gap: SPACING.sm, paddingTop: SPACING.xl * 2 },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", marginBottom: SPACING.lg },
  label: { fontSize: FONT_SIZE.body, fontWeight: "600", marginTop: SPACING.md },
  input: { minHeight: MIN_TOUCH_TARGET, borderRadius: RADIUS.input, paddingHorizontal: SPACING.md, fontSize: FONT_SIZE.body },
  row: { flexDirection: "row", alignItems: "center", gap: SPACING.sm },
  eye: { minHeight: MIN_TOUCH_TARGET, justifyContent: "center" },
  help: { fontSize: FONT_SIZE.caption },
  error: { fontSize: FONT_SIZE.body, marginTop: SPACING.sm },
  button: {
    height: BUTTON_HEIGHT,
    borderRadius: RADIUS.button,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: SPACING.sm,
    marginTop: SPACING.lg,
  },
  buttonText: { fontSize: FONT_SIZE.body, fontWeight: "600" },
});
