import { request } from "./request";

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface CurrentUser {
  user_id: string;
}

export const authApi = {
  async login(username: string, password: string): Promise<LoginResponse> {
    return request.post<LoginResponse>("/api/auth/login", { username, password });
  },

  async me(): Promise<CurrentUser> {
    return request.get<CurrentUser>("/api/auth/me");
  },
};
