import { Placeholder } from "../../src/components/Placeholder";
import { translate } from "../../src/i18n";

/** One conversation: placeholder until the conversation task. */
export default function ConversationScreen() {
  return <Placeholder title={translate("conversation.title")} message={translate("conversation.empty")} />;
}
