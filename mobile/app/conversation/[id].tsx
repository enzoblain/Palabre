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
import { api } from "../../src/api";
import { ConversationHeader } from "../../src/components/ConversationHeader";
import { ErrorBanner } from "../../src/components/ErrorBanner";
import { MessageBubble } from "../../src/components/MessageBubble";
import { MessageInput } from "../../src/components/MessageInput";
import { MessageSkeleton } from "../../src/components/MessageSkeleton";
import { buildChatItems, type ChatItem, type DisplayMessage, toDisplayMessage } from "../../src/format/messages";
import { useMessages } from "../../src/hooks/useMessages";
import { translate } from "../../src/i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../src/theme";

const SCROLL_EVENT_THROTTLE_MS = 100;
const NEAR_BOTTOM_PX = 80; // closer than this to the end counts as "at the bottom"

/** One conversation: bubbles, new messages by polling, and the input bar. */
export default function ConversationScreen() {
  const colors = useColors();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const projectId = Number(id);
  const { name, messages, pending, failed, reload, send, retry } = useMessages(projectId);
  const list = useRef<FlatList<ChatItem>>(null);
  const atBottom = useRef(true);
  const [unseen, setUnseen] = useState(false);

  const display = useMemo<DisplayMessage[]>(
    () => [
      ...(messages ?? []).map(toDisplayMessage),
      ...pending.map((item) => ({
        key: item.key,
        author: "",
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
    const { contentOffset, contentSize, layoutMeasurement } = event.nativeEvent;
    atBottom.current = contentSize.height - contentOffset.y - layoutMeasurement.height < NEAR_BOTTOM_PX;
    if (atBottom.current) setUnseen(false);
  };

  const sendAndStick = (content: string) => {
    atBottom.current = true;
    void send(content);
  };

  const renderItem = ({ item }: { item: ChatItem }) => {
    if (item.kind === "bubble") return <MessageBubble item={item} onRetry={retry} />;
    const text = item.kind === "timestamp" ? item.label : item.message.content;
    return (
      <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.centered, { color: colors.secondaryText }]}>
        {text}
      </Text>
    );
  };

  const loading = messages === null && !failed;
  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
      <ConversationHeader name={name} onBack={() => router.back()} />
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
              onScroll={onScroll}
              scrollEventThrottle={SCROLL_EVENT_THROTTLE_MS}
              keyboardDismissMode="interactive"
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={styles.content}
              ListEmptyComponent={
                messages === null ? undefined : (
                  <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.empty, { color: colors.secondaryText }]}>
                    {translate("conversation.empty")}
                  </Text>
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
        <MessageInput onSend={sendAndStick} />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { paddingVertical: SPACING.sm },
  centered: { fontSize: FONT_SIZE.caption, textAlign: "center", marginVertical: SPACING.sm },
  empty: { fontSize: FONT_SIZE.body, padding: SPACING.lg, textAlign: "center" },
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
