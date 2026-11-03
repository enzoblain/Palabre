import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { ProjectListItem } from "../src/api";
import { ConversationRow, SEPARATOR_INSET } from "../src/components/ConversationRow";
import { ConversationSkeleton } from "../src/components/ConversationSkeleton";
import { ErrorBanner } from "../src/components/ErrorBanner";
import { filterConversations } from "../src/format/conversations";
import { useConversations } from "../src/hooks/useConversations";
import { translate } from "../src/i18n";
import { FONT_SIZE, MAX_FONT_SCALE, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../src/theme";

/** Conversation list, iMessage style: large title, search, rows sorted by last activity. */
export default function ConversationListScreen() {
  const colors = useColors();
  const router = useRouter();
  const { items, failed, refreshing, refresh, reload } = useConversations();
  const [query, setQuery] = useState("");
  const visible = useMemo(() => filterConversations(items ?? [], query), [items, query]);
  const open = (item: ProjectListItem) =>
    router.push({ pathname: "/conversation/[id]", params: { id: String(item.id) } });

  const header = (
    <View>
      <Text
        accessibilityRole="header"
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.title, { color: colors.text }]}
      >
        {translate("list.title")}
      </Text>
      <TextInput
        accessibilityLabel={translate("list.search")}
        placeholder={translate("list.search")}
        placeholderTextColor={colors.secondaryText}
        value={query}
        onChangeText={setQuery}
        returnKeyType="search"
        clearButtonMode="while-editing"
        autoCorrect={false}
        maxFontSizeMultiplier={MAX_FONT_SCALE}
        style={[styles.search, { backgroundColor: colors.secondaryBackground, color: colors.text }]}
      />
      {failed ? <ErrorBanner message={translate("list.error")} onRetry={reload} /> : null}
    </View>
  );

  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: colors.background }]}>
      <FlatList
        testID="conversation-list"
        data={visible}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => <ConversationRow item={item} onPress={open} />}
        ItemSeparatorComponent={() => (
          <View style={[styles.separator, { backgroundColor: colors.separator }]} />
        )}
        ListHeaderComponent={header}
        ListEmptyComponent={
          items === null ? (
            failed ? undefined : (
              <ConversationSkeleton />
            )
          ) : (
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.empty, { color: colors.secondaryText }]}>
              {items.length === 0 ? translate("list.empty") : translate("list.noResults")}
            </Text>
          )
        }
        refreshing={refreshing}
        onRefresh={refresh}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", paddingHorizontal: SPACING.lg, paddingTop: SPACING.sm },
  search: {
    minHeight: MIN_TOUCH_TARGET,
    marginHorizontal: SPACING.lg,
    marginVertical: SPACING.sm,
    paddingHorizontal: SPACING.md,
    borderRadius: RADIUS.input,
    fontSize: FONT_SIZE.body,
  },
  separator: { height: StyleSheet.hairlineWidth, marginLeft: SEPARATOR_INSET },
  empty: { fontSize: FONT_SIZE.body, padding: SPACING.lg, textAlign: "center" },
});
