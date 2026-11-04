import * as SecureStore from "expo-secure-store";
import type { Connection } from "@palabre/shared";

// Secure storage only (iOS Keychain, Android Keystore): never AsyncStorage for a token
const STORAGE_KEY = "palabre.connection";

export async function readStoredConnection(): Promise<Connection | null> {
  const raw = await SecureStore.getItemAsync(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return isConnection(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export async function writeStoredConnection(conn: Connection): Promise<void> {
  await SecureStore.setItemAsync(STORAGE_KEY, JSON.stringify(conn));
}

export async function deleteStoredConnection(): Promise<void> {
  await SecureStore.deleteItemAsync(STORAGE_KEY);
}

function isConnection(value: unknown): value is Connection {
  if (typeof value !== "object" || value === null) return false;
  const { server, token } = value as Record<string, unknown>;
  return typeof server === "string" && typeof token === "string";
}
