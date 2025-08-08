<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  
  // Authentication store
  import { auth } from '$lib/stores/auth';
  
  onMount(() => {
    // Check for existing token
    auth.checkAuth();
  });
</script>

<div class="min-h-screen bg-gray-50">
  {#if $auth.isAuthenticated}
    <!-- Authenticated layout with nav -->
    <nav class="bg-white shadow-sm border-b border-gray-200">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-16">
          <div class="flex items-center">
            <h1 class="text-xl font-semibold text-gray-900">ProjectFlow AI</h1>
            
            <div class="hidden sm:ml-6 sm:flex sm:space-x-8">
              <a 
                href="/projects" 
                class="inline-flex items-center px-1 pt-1 text-sm font-medium"
                class:border-b-2={$page.url.pathname.startsWith('/projects')}
                class:border-primary-500={$page.url.pathname.startsWith('/projects')}
                class:text-gray-900={$page.url.pathname.startsWith('/projects')}
                class:text-gray-500={!$page.url.pathname.startsWith('/projects')}
              >
                Projects
              </a>
            </div>
          </div>
          
          <div class="flex items-center space-x-4">
            <span class="text-sm text-gray-700">
              {$auth.user?.username}
            </span>
            <button 
              on:click={auth.logout}
              class="text-sm text-gray-500 hover:text-gray-700"
            >
              Sign out
            </button>
          </div>
        </div>
      </div>
    </nav>
    
    <main>
      <slot />
    </main>
  {:else}
    <!-- Unauthenticated layout -->
    <slot />
  {/if}
</div>