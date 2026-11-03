import { Placeholder } from "../src/components/Placeholder";
import { translate } from "../src/i18n";

/** Conversation list: placeholder until the list task. */
export default function ConversationListScreen() {
  return <Placeholder title={translate("list.title")} message={translate("list.empty")} />;
}
