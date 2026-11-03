import { renderHook } from "@testing-library/react-native";
import { AppState, type AppStateStatus } from "react-native";
import { usePolling } from "../src/hooks/usePolling";

const INTERVAL_MS = 1000;

describe("usePolling", () => {
  let changeListener: (state: AppStateStatus) => void;
  const removeSubscription = jest.fn();

  const setAppState = (state: AppStateStatus) => {
    Object.defineProperty(AppState, "currentState", { value: state, configurable: true });
  };

  beforeEach(() => {
    jest.useFakeTimers();
    setAppState("active");
    jest.spyOn(AppState, "addEventListener").mockImplementation((_type, listener) => {
      changeListener = listener as (state: AppStateStatus) => void;
      return { remove: removeSubscription };
    });
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
    removeSubscription.mockClear();
  });

  it("calls now, then again after each interval", async () => {
    const callback = jest.fn();
    await renderHook(() => usePolling(callback, INTERVAL_MS));
    expect(callback).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(INTERVAL_MS);
    expect(callback).toHaveBeenCalledTimes(2);
  });

  it("does not call while the app is in the background", async () => {
    setAppState("background");
    const callback = jest.fn();
    await renderHook(() => usePolling(callback, INTERVAL_MS));
    jest.advanceTimersByTime(INTERVAL_MS * 3);
    expect(callback).not.toHaveBeenCalled();
  });

  it("pauses in the background and calls again on return to active", async () => {
    const callback = jest.fn();
    await renderHook(() => usePolling(callback, INTERVAL_MS));
    changeListener("background");
    jest.advanceTimersByTime(INTERVAL_MS * 3);
    expect(callback).toHaveBeenCalledTimes(1);
    changeListener("active");
    expect(callback).toHaveBeenCalledTimes(2);
    jest.advanceTimersByTime(INTERVAL_MS);
    expect(callback).toHaveBeenCalledTimes(3);
  });

  it("clears the interval and the subscription on unmount", async () => {
    const callback = jest.fn();
    const { unmount } = await renderHook(() => usePolling(callback, INTERVAL_MS));
    await unmount();
    jest.advanceTimersByTime(INTERVAL_MS * 3);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(removeSubscription).toHaveBeenCalled();
  });
});
