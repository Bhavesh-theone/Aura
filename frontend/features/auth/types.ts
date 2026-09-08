export type User = {
  id: number;
  username: string;
  role: string;
};

export type LoginRequest = { username: string; password: string };
export type LoginResponse = { access_token: string; token_type: string };
