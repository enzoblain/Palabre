import { Placeholder } from "../src/components/Placeholder";
import { translate } from "../src/i18n";

/** Sign-in: placeholder until the login task. */
export default function LoginScreen() {
  return <Placeholder title={translate("login.title")} message={translate("login.help")} />;
}
