import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AccessibilityInfo,
  FlatList,
  KeyboardAvoidingView,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import * as Clipboard from "expo-clipboard";
import { api } from "../../src/api";
import { ConversationInfo } from "../../src/components/ConversationInfo";
import { ConversationHeader } from "../../src/components/ConversationHeader";
import { ErrorBanner } from "../../src/components/ErrorBanner";
import { MessageActions } from "../../src/components/MessageActions";
import { MessageBubble } from "../../src/components/MessageBubble";
import { MessageInput, type MentionRequest } from "../../src/components/MessageInput";
import { MessageSkeleton } from "../../src/components/MessageSkeleton";
import { SystemMessage } from "../../src/components/SystemMessage";
import { TypingDots } from "../../src/components/TypingDots";
import { buildChatItems, type ChatItem, type DisplayMessage, toDisplayMessage } from "../../src/format/messages";
import { useLeadWriting } from "../../src/hooks/useLeadWriting";
import { useMessages } from "../../src/hooks/useMessages";
import { translate } from "../../src/i18n";
import { bossNames } from "../../src/markdown/parse";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../src/theme";

const SCROLL_EVENT_THROTTLE_MS = 100;
const NEAR_BOTTOM_PX = 80; // closer than this to the end counts as "at the bottom"

/** The boss's name, read once; the team can mention them with it (empty until known or when unset). */
function useBossName(): string {
  const [bossName, setBossName] = useState("");
  useEffect(() => {
    api.getSettings().then((settings) => setBossName(settings.boss_name)).catch(() => {});
  }, []);
  return bossName;
}

/** One conversation: bubbles, new messages by polling, and the input bar. */
export default function ConversationScreen() {
  const colors = useColors();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const projectId = Number(id);
  const { name, info, messages, pending, failed, reload, refreshInfo, send, retry } = useMessages(projectId);
  const leadWriting = useLeadWriting(projectId);
  const bossName = useBossName();
  const selfNames = useMemo(() => bossNames(bossName), [bossName]);
  const [infoOpen, setInfoOpen] = useState(false);
  const [menuMessage, setMenuMessage] = useState<DisplayMessage | null>(null);
  const [mention, setMention] = useState<MentionRequest | null>(null);
  const titles = useMemo(
    () => new Map((info?.employees ?? []).map((employee) => [employee.id, employee.title])),
    [info?.employees],
  );
  const list = useRef<FlatList<ChatItem>>(null);
  const atBottom = useRef(true);
  const userScrolling = useRef(false); // only user gestures may move us off the bottom
  const [unseen, setUnseen] = useState(false);

  const display = useMemo<DisplayMessage[]>(
    () => [
      ...(messages ?? []).map(toDisplayMessage),
      ...pending.map((item) => ({
        key: item.key,
        author: "",
        employeeId: null,
        content: item.content,
        createdAt: item.createdAt,
        own: true,
        system: false,
        isRequest: false,
        status: item.status,
      })),
    ],
    [messages, pending],
  );
  const items = useMemo(() => buildChatItems(display), [display]);

  const newestId = messages?.[messages.length - 1]?.id;
  useEffect(() => {
    if (newestId !== undefined) api.markDirectionRead(projectId).catch(() => {});
  }, [projectId, newestId]);

  const announced = useRef<number | undefined>(undefined);
  useEffect(() => {
    const newest = messages?.[messages.length - 1];
    if (!newest) return;
    if (announced.current !== undefined && newest.id > announced.current && newest.employee_id !== null) {
      AccessibilityInfo.announceForAccessibility(`${newest.author_name}: ${newest.content}`);
    }
    announced.current = newest.id;
  }, [messages]);

  const scrollToEnd = () => {
    list.current?.scrollToEnd({ animated: false });
    setUnseen(false);
  };

  const onContentSizeChange = () => {
    if (atBottom.current) scrollToEnd();
    else if (items.length > 0) setUnseen(true);
  };

  const onScroll = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    // Layout changes (first render, keyboard, new content) also emit scroll events: ignore them.
    if (!userScrolling.current) return;
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    atBottom.current = contentSize.height - contentOffset.y - layoutMeasurement.height < NEAR_BOTTOM_PX;
    if (atBottom.current) setUnseen(false);
  };

  const startUserScroll = () => {
    userScrolling.current = true;
  };
  const endUserScroll = () => {
    userScrolling.current = false;
  };

  const onListLayout = () => {
    if (atBottom.current) scrollToEnd();
  };

  const sendAndStick = (content: string) => {
    atBottom.current = true;
    void send(content);
  };

  const copyMessage = async (message: DisplayMessage): Promise<boolean> => {
    try {
      const copied = await Clipboard.setStringAsync(message.content);
      AccessibilityInfo.announceForAccessibility(translate(copied ? "conversation.copied" : "conversation.copyFailed"));
      return copied;
    } catch {
      AccessibilityInfo.announceForAccessibility(translate("conversation.copyFailed"));
      return false;
    }
  };

  // The room is read once by the poll: re-read it each time the sheet opens, as the web does
  const openInfo = () => {
    setInfoOpen(true);
    void refreshInfo();
  };

  const insertMention = (name: string) => {
    setInfoOpen(false);
    setMention((previous) => ({ name, nonce: (previous?.nonce ?? 0) + 1 }));
  };

  const openProject = () => {
    setInfoOpen(false);
    router.push({ pathname: "/project/[id]", params: { id: String(projectId) } });
  };

  const renderItem = ({ item }: { item: ChatItem }) => {
    if (item.kind === "bubble") {
      const { employeeId } = item.message;
      return (
        <MessageBubble
          item={item}
          title={employeeId === null ? undefined : titles.get(employeeId)}
          selfNames={selfNames}
          onRetry={retry}
          onMenu={setMenuMessage}
          onCopy={copyMessage}
        />
      );
    }
    if (item.kind === "system") return <SystemMessage content={item.message.content} />;
    return (
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.centered, { color: colors.secondaryText }]}>
        {item.label}
      </Text>
    );
  };

  const empty = messages !== null && messages.length === 0 && pending.length === 0;
  const placeholder = empty
    ? translate("conversation.placeholderEmpty")
    : translate("conversation.placeholder", { project: name ?? "", boss: bossName || translate("conversation.bossFallback") });
  const typing = leadWriting && info?.room.kind === "direction";
  const loading = messages === null && !failed;
  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
      <ConversationHeader name={name} onBack={() => router.back()} onInfo={info ? openInfo : undefined} />
      {info ? (
        <ConversationInfo
          room={info.room}
          conversationId={info.conversationId}
          visible={infoOpen}
          onClose={() => setInfoOpen(false)}
          onMention={insertMention}
          onOpenProject={openProject}
        />
      ) : null}
      <MessageActions message={menuMessage} onCopy={copyMessage} onClose={() => setMenuMessage(null)} />
      <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        {failed ? <ErrorBanner message={translate("conversation.unavailable")} onRetry={reload} /> : null}
        {loading ? (
          <MessageSkeleton />
        ) : (
          <View style={styles.screen}>
            <FlatList
              ref={list}
              testID="message-list"
              data={items}
              keyExtractor={(item) => item.key}
              renderItem={renderItem}
              onContentSizeChange={onContentSizeChange}
              onLayout={onListLayout}
              onScroll={onScroll}
              onScrollBeginDrag={startUserScroll}
              onScrollEndDrag={(event) => {
                // Without momentum the gesture is over; otherwise wait for the momentum to end.
                if (!event.nativeEvent.velocity?.y) endUserScroll();
              }}
              onMomentumScrollEnd={endUserScroll}
              scrollEventThrottle={SCROLL_EVENT_THROTTLE_MS}
              keyboardDismissMode="interactive"
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={styles.content}
              ListFooterComponent={typing && info?.leadName ? <TypingDots name={info.leadName} /> : undefined}
              ListEmptyComponent={
                messages === null ? undefined : (
                  <View style={styles.empty}>
                    <Text accessibilityRole="header" maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.introTitle, { color: colors.text }]}>
                      {translate("conversation.introTitle", { project: name ?? "" })}
                    </Text>
                    <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.introBody, { color: colors.secondaryText }]}>
                      {[
                        translate("conversation.intro"),
                        info?.leadName && translate("conversation.introLead", { name: info.leadName, title: info.leadTitle ?? "" }),
                      ]
                        .filter(Boolean)
                        .join(" ")}
                    </Text>
                  </View>
                )
              }
            />
            {unseen ? (
              <Pressable
                accessibilityRole="button"
                onPress={scrollToEnd}
                style={[styles.pill, { backgroundColor: colors.secondaryBackground }]}
              >
                <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.pillText, { color: colors.link }]}>
                  {translate("conversation.newMessages")}
                </Text>
              </Pressable>
            ) : null}
          </View>
        )}
        <MessageInput placeholder={placeholder} mention={mention} onSend={sendAndStick} />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingVertical: SPACING.sm },
  centered: { fontSize: FONT_SIZE.caption, textAlign: "center", marginVertical: SPACING.sm },
  empty: { padding: SPACING.lg, gap: SPACING.sm },
  introTitle: { fontSize: FONT_SIZE.body, fontWeight: "600", textAlign: "center" },
  introBody: { fontSize: FONT_SIZE.body, textAlign: "center" },
  pill: {
    position: "absolute",
    bottom: SPACING.sm,
    alignSelf: "center",
    minHeight: MIN_TOUCH_TARGET,
    justifyContent: "center",
    paddingHorizontal: SPACING.lg,
    borderRadius: RADIUS.bubble,
  },
  pillText: { fontSize: FONT_SIZE.body, fontWeight: "600" },
});
