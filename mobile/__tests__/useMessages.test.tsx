import { act, renderHook, waitFor } from "@testing-library/react-native";
import { api, type Message } from "../src/api";
import { useMessages } from "../src/hooks/useMessages";

jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "fr" }] }));
jest.mock("expo-secure-store", () => ({}));
jest.mock("../src/api", () => ({
  ...jest.requireActual("../src/api"),
  api: { getProject: jest.fn(), listConversations: jest.fn(), listMessages: jest.fn(), postMessage: jest.fn() },
}));

const mocked = api as unknown as Record<"getProject" | "listConversations" | "listMessages" | "postMessage", jest.Mock>;

const message = (id: number, content = "Salut", employeeId: number | null = 5): Message => ({
  id,
  conversation_id: 9,
  employee_id: employeeId,
  author_name: "Élise",
  content,
  created_at: "2026-01-01T10:00:00Z",
  is_system: false,
  request_kind: null,
  request_status: null,
  request_comment: null,
  request_answered_at: null,
  request_merged_into: null,
  request_decision_id: null,
});

beforeEach(() => {
  jest.clearAllMocks();
  mocked.getProject.mockResolvedValue({ name: "Alpha", employees: [], rooms: [{ id: 3, kind: "team" }, { id: 4, kind: "direction" }] });
  mocked.listConversations.mockResolvedValue([{ id: 9 }]);
});

describe("useMessages", () => {
  it("loads the direction conversation, then asks only for what is after the last id", async () => {
    jest.useFakeTimers();
    mocked.listMessages.mockResolvedValueOnce([message(1), message(2)]).mockResolvedValue([message(3, "Nouveau")]);
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.messages?.map((m) => m.id)).toEqual([1, 2]));
    expect(mocked.listConversations).toHaveBeenCalledWith(4);
    expect(mocked.listMessages).toHaveBeenLastCalledWith(9, undefined);
    expect(result.current.name).toBe("Alpha");

    await act(async () => {
      jest.advanceTimersByTime(2000);
    });
    await waitFor(() => expect(result.current.messages?.map((m) => m.id)).toEqual([1, 2, 3]));
    expect(mocked.listMessages).toHaveBeenLastCalledWith(9, 2);
    jest.useRealTimers();
  });

  it("reports a failed load and recovers on reload", async () => {
    mocked.listMessages.mockRejectedValueOnce(new Error("down"));
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.failed).toBe(true));
    mocked.listMessages.mockResolvedValue([message(1)]);
    await act(async () => result.current.reload());
    expect(result.current.failed).toBe(false);
    expect(result.current.messages).toHaveLength(1);
  });

  it("shows a sent message at once as pending, then replaces it with the server's", async () => {
    mocked.listMessages.mockResolvedValue([]);
    let resolvePost: (value: Message) => void = () => {};
    mocked.postMessage.mockReturnValue(new Promise<Message>((resolve) => (resolvePost = resolve)));
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => {
      void result.current.send("Go");
    });
    expect(result.current.pending).toMatchObject([{ content: "Go", status: "sending" }]);
    await act(async () => resolvePost(message(5, "Go", null)));
    expect(result.current.pending).toEqual([]);
    expect(result.current.messages?.map((m) => m.id)).toEqual([5]);
  });

  it("keeps a failed message and sends it again on retry", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.postMessage.mockRejectedValueOnce(new Error("down"));
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.messages).toEqual([]));

    await act(async () => result.current.send("Go"));
    expect(result.current.pending).toMatchObject([{ content: "Go", status: "failed" }]);

    mocked.postMessage.mockResolvedValue(message(6, "Go", null));
    await act(async () => result.current.retry(result.current.pending[0].key));
    expect(mocked.postMessage).toHaveBeenCalledTimes(2);
    expect(result.current.pending).toEqual([]);
    expect(result.current.messages?.map((m) => m.id)).toEqual([6]);
  });

  it("does not skip a team message that lands before the boss's own send", async () => {
    jest.useFakeTimers();
    mocked.listMessages.mockResolvedValueOnce([message(1)]);
    mocked.postMessage.mockResolvedValue(message(3, "Go", null));
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.messages?.map((m) => m.id)).toEqual([1]));

    await act(async () => result.current.send("Go"));
    expect(result.current.messages?.map((m) => m.id)).toEqual([1, 3]);

    mocked.listMessages.mockResolvedValue([message(2, "Entre"), message(3, "Go", null)]);
    await act(async () => {
      jest.advanceTimersByTime(2000);
    });
    expect(mocked.listMessages).toHaveBeenLastCalledWith(9, 1);
    await waitFor(() => expect(result.current.messages?.map((m) => m.id)).toEqual([1, 2, 3]));
    jest.useRealTimers();
  });

  it("posts only once when retry is tapped twice quickly", async () => {
    mocked.listMessages.mockResolvedValue([]);
    mocked.postMessage.mockRejectedValueOnce(new Error("down"));
    const { result } = await renderHook(() => useMessages(1));
    await waitFor(() => expect(result.current.messages).toEqual([]));
    await act(async () => result.current.send("Go"));

    mocked.postMessage.mockResolvedValue(message(6, "Go", null));
    const key = result.current.pending[0].key;
    await act(async () => {
      void result.current.retry(key);
      void result.current.retry(key);
    });
    expect(mocked.postMessage).toHaveBeenCalledTimes(2);
  });
});
