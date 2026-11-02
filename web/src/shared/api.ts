import type { ValidateFunction } from "ajv";
import { validGraphDocument } from "../validators.js";
import { useSession } from "./state";
import { copy } from "../copy";
let csrf = "";
export function setToken(value: string) {
  csrf = value;
}
export function validate(_schema: unknown, value: unknown) {
  return validGraphDocument(value);
}
export async function api<T>(
  path: string,
  validator: ValidateFunction<T>,
  body?: unknown,
): Promise<T> {
  const session = useSession.getState();
  if (session.mode === "replay") throw Error(copy.replay);
  const response = await fetch("/api/v1/" + path, {
    method: body === undefined ? "GET" : "POST",
    cache: "no-store",
    headers: {
      ...(body === undefined
        ? {}
        : { "Content-Type": "application/json", "x-tresata-csrf": csrf }),
      ...(session.trace ? { "x-tresata-trace": "session" } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok)
    throw Error(response.status === 403 ? copy.noTrace : copy.unavailable);
  const value: unknown = await response.json();
  if (!validator(value)) throw Error(copy.rejected);
  return value;
}
export async function apiList<T>(
  path: string,
  validator: ValidateFunction<T>,
): Promise<T[]> {
  if (useSession.getState().mode === "replay") throw Error(copy.replay);
  const response = await fetch("/api/v1/" + path, { cache: "no-store" });
  const value: unknown = await response.json();
  if (
    !response.ok ||
    !Array.isArray(value) ||
    !value.every((item) => validator(item))
  )
    throw Error(copy.rejected);
  return value;
}
