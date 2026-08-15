import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Create axios instance
export const apiClient = axios.create({
  baseURL: `${API_URL}/api`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Track if refresh is in progress to prevent multiple simultaneous refreshes
let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function onRefreshed(token: string) {
  refreshSubscribers.forEach(callback => callback(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(callback: (token: string) => void) {
  refreshSubscribers.push(callback);
}

// Request interceptor - Add Authorization header from localStorage
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // Get access token from localStorage
    const accessToken = localStorage.getItem('access_token');

    // Add Authorization header if token exists
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }

    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor - handle 401 with automatic token refresh
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Handle 401 Unauthorized
    if (error.response?.status === 401 && !originalRequest._retry) {
      // Prevent refresh on public routes
      const isPublicRoute = originalRequest.url?.includes('/auth/login') ||
                           originalRequest.url?.includes('/auth/signup') ||
                           originalRequest.url?.includes('/auth/me');  // Allow /auth/me to fail silently

      if (isPublicRoute) {
        return Promise.reject(error);
      }

      // Prevent infinite loops on refresh endpoint
      if (originalRequest.url?.includes('/auth/refresh')) {
        // Refresh failed, logout user
        if (typeof window !== 'undefined') {
          window.location.href = '/auth/login';
        }
        return Promise.reject(error);
      }

      originalRequest._retry = true;

      // If already refreshing, queue this request
      if (isRefreshing) {
        return new Promise((resolve) => {
          addRefreshSubscriber(() => {
            resolve(apiClient(originalRequest));
          });
        });
      }

      isRefreshing = true;

      try {
        // Get refresh token from localStorage
        const refreshToken = localStorage.getItem('refresh_token');

        if (!refreshToken) {
          throw new Error('No refresh token available');
        }

        // Attempt to refresh token
        const response = await apiClient.post('/auth/refresh', {
          refresh_token: refreshToken
        });

        // Store new tokens
        localStorage.setItem('access_token', response.data.access_token);
        localStorage.setItem('refresh_token', response.data.refresh_token);

        // Refresh successful
        isRefreshing = false;
        onRefreshed(response.data.access_token);

        // Retry original request with new token
        originalRequest.headers.Authorization = `Bearer ${response.data.access_token}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        // Refresh failed, clear tokens and redirect to login
        isRefreshing = false;
        refreshSubscribers = [];

        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');

        if (typeof window !== 'undefined') {
          window.location.href = '/auth/login';
        }

        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

/**
 * Fetch wrapper with automatic token refresh on 401.
 * Use this instead of raw fetch() for authenticated API calls
 * that can't use Axios (e.g., SSE streaming).
 */
export async function fetchWithRefresh(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const accessToken = localStorage.getItem("access_token");

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }

  let response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    // Try refreshing the token
    const refreshToken = localStorage.getItem("refresh_token");
    if (!refreshToken) {
      window.location.href = "/auth/login";
      throw new Error("No refresh token");
    }

    try {
      const refreshRes = await apiClient.post("/auth/refresh", {
        refresh_token: refreshToken,
      });

      localStorage.setItem("access_token", refreshRes.data.access_token);
      localStorage.setItem("refresh_token", refreshRes.data.refresh_token);

      // Retry the original request with the new token
      headers["Authorization"] = `Bearer ${refreshRes.data.access_token}`;
      response = await fetch(url, { ...options, headers });
    } catch {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      window.location.href = "/auth/login";
      throw new Error("Token refresh failed");
    }
  }

  return response;
}

export default apiClient;
