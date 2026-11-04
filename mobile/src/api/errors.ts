import { type ErrorCode, isErrorCode } from "@palabre/shared";

import { translate } from "../i18n";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The backend's own text (English), kept for logs and debugging, never shown as is. */
    public detail?: string,
    public code?: ErrorCode,
  ) {
    super(message);
  }
}

/** The message in the phone's language: by code, else a generic one with the status. */
export function errorMessage(status: number, code: unknown): string {
  if (!isErrorCode(code)) return translate("api.error", { status });
  return translate(`error.${code}`);
}

/** The error code of a response body, when it carries a known one. */
export function readErrorCode(code: unknown): ErrorCode | undefined {
  return isErrorCode(code) ? code : undefined;
}
