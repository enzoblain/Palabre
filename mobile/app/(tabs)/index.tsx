import { useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { readLastOpenedProject, writeLastOpenedProject, type ProjectListItem } from "../../src/api";
import { ConversationRow, SEPARATOR_INSET } from "../../src/components/ConversationRow";
import { ConversationSkeleton } from "../../src/components/ConversationSkeleton";
import { CreditsBanner } from "../../src/components/CreditsBanner";
import { DeleteBar } from "../../src/components/DeleteBar";
import { ErrorBanner } from "../../src/components/ErrorBanner";
import { filterConversations, lastOpenedFirst } from "../../src/format/conversations";
import { useConversations } from "../../src/hooks/useConversations";
import { useProjectsEditing } from "../../src/hooks/useProjectsEditing";
import { translate } from "../../src/i18n";
import { FONT_SIZE, MAX_FONT_SCALE, DESTRUCTIVE_TOUCH_TARGET, MIN_TOUCH_TARGET, RADIUS, SPACING, useColors } from "../../src/theme";

const SCREEN_EDGES = ["top", "left", "right"] as const; // the tab bar owns the bottom safe area

/** Conversation list, iMessage style: large title, search, rows sorted by last activity. */
export default function ConversationListScreen() {
  const colors = useColors();
  const router = useRouter();
  const { items, failed, refreshing, refresh, reload } = useConversations();
  const [query, setQuery] = useState("");
  const [lastOpenedId, setLastOpenedId] = useState<number | null>(null);
  const editing = useProjectsEditing(reload);
  useEffect(() => {
    void readLastOpenedProject().then(setLastOpenedId);
  }, []);
  const visible = useMemo(
    () => filterConversations(lastOpenedFirst(items ?? [], lastOpenedId), query),
    [items, lastOpenedId, query],
  );
  const open = (item: ProjectListItem) => {
    setLastOpenedId(item.id);
    void writeLastOpenedProject(item.id);
    router.push({ pathname: "/conversation/[id]", params: { id: String(item.id) } });
  };
  const confirmDelete = useCallback(() => {
    Alert.alert(translate("list.deleteConfirm", { count: editing.checkedIds.size }), undefined, [
      { text: translate("common.cancel"), style: "cancel" },
      { text: translate("list.deleteForGood"), style: "destructive", onPress: () => void editing.deleteChecked() },
    ]);
  }, [editing]);

  const header = (
    <View>
      <View style={styles.titleRow}>
        <Text
          accessibilityRole="header"
          maxFontSizeMultiplier={MAX_FONT_SCALE}
          style={[styles.title, { color: colors.text }]}
        >
          {translate("list.title")}
        </Text>
        {items?.length ? (
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: editing.editing }}
            onPress={editing.toggleEditing}
            style={styles.editButton}
          >
            <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.editLabel, { color: colors.link }]}>
              {translate(editing.editing ? "list.done" : "list.edit")}
            </Text>
          </Pressable>
        ) : null}
      </View>
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
      <CreditsBanner />
      {failed ? <ErrorBanner message={translate("list.error")} onRetry={reload} /> : null}
    </View>
  );

  return (
    <SafeAreaView edges={SCREEN_EDGES} style={[styles.screen, { backgroundColor: colors.background }]}>
      <FlatList
        testID="conversation-list"
        data={visible}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => (
          <ConversationRow
            item={item}
            onPress={editing.editing ? editing.toggle : open}
            selected={editing.editing ? editing.checkedIds.has(item.id) : undefined}
          />
        )}
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
            <View>
              <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.empty, { color: colors.secondaryText }]}>
                {items.length === 0 ? translate("list.empty") : translate("list.noResults")}
              </Text>
              {items.length === 0 ? (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => router.navigate("/new")}
                  style={[styles.create, { backgroundColor: colors.link }]}
                >
                  <Text maxFontSizeMultiplier={MAX_FONT_SCALE} style={[styles.createLabel, { color: colors.sentBubbleText }]}>
                    {translate("list.create")}
                  </Text>
                </Pressable>
              ) : null}
            </View>
          )
        }
        refreshing={refreshing}
        onRefresh={refresh}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
      />
      {editing.editing ? (
        <DeleteBar
          count={editing.checkedIds.size}
          busy={editing.deleting}
          error={editing.error}
          onDelete={confirmDelete}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingRight: SPACING.sm },
  title: { fontSize: FONT_SIZE.largeTitle, fontWeight: "700", paddingHorizontal: SPACING.lg, paddingTop: SPACING.sm },
  editButton: { minHeight: DESTRUCTIVE_TOUCH_TARGET, minWidth: DESTRUCTIVE_TOUCH_TARGET, justifyContent: "center", alignItems: "center", paddingHorizontal: SPACING.md },
  editLabel: { fontSize: FONT_SIZE.body, fontWeight: "600" },
  create: { minHeight: DESTRUCTIVE_TOUCH_TARGET, marginHorizontal: SPACING.lg, borderRadius: RADIUS.button, alignItems: "center", justifyContent: "center" },
  createLabel: { fontSize: FONT_SIZE.body, fontWeight: "600" },
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
