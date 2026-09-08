import { apiFetch } from "@/shared/api/client";
import type { LoginRequest, LoginResponse, User } from "./types";

export function login(body: LoginRequest) {
  return apiFetch<LoginResponse>("/api/auth/login", { method: "POST", body, auth: false });
}

export function fetchMe() {
  return apiFetch<User>("/api/auth/me");
}
