import { writable, get } from 'svelte/store';
import { goto } from '$app/navigation';

interface User {
  id: number;
  email: string;
  username: string;
  full_name?: string;
}

interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  token: string | null;
}

// Create auth store
function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({
    isAuthenticated: false,
    user: null,
    token: null
  });

  return {
    subscribe,
    
    login: async (email: string, password: string) => {
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            email,
            password
          })
        });

        if (!response.ok) {
          throw new Error('Login failed');
        }

        const data = await response.json();
        
        // Store token
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        // Get user info
        const userResponse = await fetch('/api/auth/me', {
          headers: {
            'Authorization': `Bearer ${data.access_token}`
          }
        });

        if (userResponse.ok) {
          const user = await userResponse.json();
          set({
            isAuthenticated: true,
            user,
            token: data.access_token
          });
          
          goto('/projects');
        }
      } catch (error) {
        console.error('Login error:', error);
        throw error;
      }
    },

    loginWithGitHub: async () => {
      try {
        const response = await fetch('/api/auth/github/login');
        const data = await response.json();
        
        // Redirect to GitHub OAuth
        window.location.href = data.auth_url;
      } catch (error) {
        console.error('GitHub login error:', error);
        throw error;
      }
    },

    handleGitHubCallback: async (code: string, state: string) => {
      try {
        const response = await fetch('/api/auth/github/callback', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ code, state })
        });

        if (!response.ok) {
          throw new Error('GitHub callback failed');
        }

        const data = await response.json();
        
        // Store tokens
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        // Get user info
        const userResponse = await fetch('/api/auth/me', {
          headers: {
            'Authorization': `Bearer ${data.access_token}`
          }
        });

        if (userResponse.ok) {
          const user = await userResponse.json();
          set({
            isAuthenticated: true,
            user,
            token: data.access_token
          });
          
          goto('/projects');
        }
      } catch (error) {
        console.error('GitHub callback error:', error);
        throw error;
      }
    },

    register: async (email: string, username: string, password: string) => {
      try {
        const response = await fetch('/api/auth/register', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            email,
            username,
            password
          })
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'Registration failed');
        }

        // Auto-login after registration
        await get(auth).login(email, password);
      } catch (error) {
        console.error('Registration error:', error);
        throw error;
      }
    },

    logout: () => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      set({
        isAuthenticated: false,
        user: null,
        token: null
      });
      goto('/login');
    },

    checkAuth: async () => {
      const token = localStorage.getItem('access_token');
      if (!token) {
        return;
      }

      try {
        const response = await fetch('/api/auth/me', {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        });

        if (response.ok) {
          const user = await response.json();
          set({
            isAuthenticated: true,
            user,
            token
          });
        } else {
          // Token invalid, clear storage
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
        }
      } catch (error) {
        console.error('Auth check error:', error);
      }
    }
  };
}

export const auth = createAuthStore();