import { useCallback, useState } from "react";
import { api, type ProjectListItem } from "../api";
import { sortByActivity } from "../format/conversations";
import { usePolling } from "./usePolling";

const LIST_POLL_MS = 5000; // same as the web app

export type ConversationsState = {
  items: ProjectListItem[] | null; // null until the first load; kept across errors as a cache
  failed: boolean;
  refreshing: boolean;
  refresh: () => Promise<void>;
  reload: () => Promise<void>;
};

/** The conversation list, polled while the app is in the foreground. */
export function useConversations(): ConversationsState {
  const [items, setItems] = useState<ProjectListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(async () => {
    try {
      setItems(sortByActivity(await api.listProjects()));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  usePolling(reload, LIST_POLL_MS);

  return { items, failed, refreshing, refresh, reload };
}
